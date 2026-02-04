"""Tests for cache utilities."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.cache import (
    CacheManager,
    HTMLCacheEntry,
    PSICacheEntry,
    _cache_key,
    _is_expired,
    _utc_now,
    load_existing_leads,
    create_html_cache_data,
    create_psi_cache_data,
    CACHE_SCHEMA_VERSION,
    DEFAULT_TTL_SECONDS,
    CacheMetadata,
)
from src.utils.url import normalize_url, extract_domain, urls_match, TRACKING_PARAMS


# ---------------------------------------------------------------------------
# URL Normalization Tests
# ---------------------------------------------------------------------------

class TestUrlNormalization:
    """Test URL normalization functions."""

    def test_normalize_basic_url(self):
        """Basic URL should be normalized consistently."""
        url = "https://example.com"
        normalized = normalize_url(url)
        assert normalized == "https://example.com/"

    def test_normalize_lowercase_host(self):
        """Host should be lowercased."""
        url = "https://EXAMPLE.COM/Path"
        normalized = normalize_url(url)
        assert "example.com" in normalized

    def test_normalize_removes_utm_params(self):
        """UTM parameters should be removed."""
        url = "https://example.com/page?utm_source=google&utm_medium=cpc&real=param"
        normalized = normalize_url(url)
        assert "utm_source" not in normalized
        assert "utm_medium" not in normalized
        assert "real=param" in normalized

    def test_normalize_removes_gclid(self):
        """Google click ID should be removed."""
        url = "https://example.com/page?gclid=abc123&other=value"
        normalized = normalize_url(url)
        assert "gclid" not in normalized
        assert "other=value" in normalized

    def test_normalize_removes_fbclid(self):
        """Facebook click ID should be removed."""
        url = "https://example.com/page?fbclid=xyz789&other=value"
        normalized = normalize_url(url)
        assert "fbclid" not in normalized
        assert "other=value" in normalized

    def test_normalize_removes_mc_params(self):
        """Mailchimp params should be removed."""
        url = "https://example.com/page?mc_cid=abc&mc_eid=xyz&other=value"
        normalized = normalize_url(url)
        assert "mc_cid" not in normalized
        assert "mc_eid" not in normalized
        assert "other=value" in normalized

    def test_normalize_strips_default_ports(self):
        """Default ports should be stripped."""
        url_443 = "https://example.com:443/page"
        url_80 = "http://example.com:80/page"
        assert ":443" not in normalize_url(url_443)
        assert ":80" not in normalize_url(url_80, prefer_https=False)

    def test_normalize_keeps_non_default_ports(self):
        """Non-default ports should be kept."""
        url = "https://example.com:8443/page"
        normalized = normalize_url(url)
        assert ":8443" in normalized

    def test_normalize_removes_fragment(self):
        """Fragments should be removed."""
        url = "https://example.com/page#section"
        normalized = normalize_url(url)
        assert "#" not in normalized

    def test_normalize_uses_final_url(self):
        """Should use final_url when provided."""
        url = "http://old.example.com"
        final_url = "https://new.example.com/redirected"
        normalized = normalize_url(url, final_url=final_url)
        assert "new.example.com" in normalized

    def test_normalize_upgrades_http_to_https(self):
        """HTTP should be upgraded to HTTPS by default."""
        url = "http://example.com/page"
        normalized = normalize_url(url)
        assert normalized.startswith("https://")

    def test_normalize_adds_trailing_slash_to_root(self):
        """Root path should have trailing slash."""
        url = "https://example.com"
        normalized = normalize_url(url)
        assert normalized.endswith("/")

    def test_normalize_preserves_query_param_order(self):
        """Query params should be sorted for consistency."""
        url1 = "https://example.com/page?b=2&a=1"
        url2 = "https://example.com/page?a=1&b=2"
        assert normalize_url(url1) == normalize_url(url2)

    def test_extract_domain(self):
        """Domain extraction should work correctly."""
        assert extract_domain("https://www.example.com/page") == "www.example.com"
        assert extract_domain("https://EXAMPLE.COM") == "example.com"

    def test_urls_match_with_tracking_params(self):
        """URLs differing only by tracking params should match."""
        url1 = "https://example.com/page"
        url2 = "https://example.com/page?utm_source=test&fbclid=xyz"
        assert urls_match(url1, url2)

    def test_all_tracking_params_stripped(self):
        """All known tracking params should be stripped."""
        base = "https://example.com/page"
        for param in list(TRACKING_PARAMS)[:10]:  # Test subset
            url = f"{base}?{param}=value"
            normalized = normalize_url(url)
            assert param not in normalized


# ---------------------------------------------------------------------------
# Cache Key Tests
# ---------------------------------------------------------------------------

class TestCacheKey:
    """Test cache key generation."""

    def test_cache_key_deterministic(self):
        """Same input should produce same key."""
        key1 = _cache_key("https://example.com/", "html")
        key2 = _cache_key("https://example.com/", "html")
        assert key1 == key2

    def test_cache_key_different_for_different_urls(self):
        """Different URLs should produce different keys."""
        key1 = _cache_key("https://example.com/", "html")
        key2 = _cache_key("https://other.com/", "html")
        assert key1 != key2

    def test_cache_key_different_for_different_suffix(self):
        """Different suffix should produce different keys."""
        key1 = _cache_key("https://example.com/", "html")
        key2 = _cache_key("https://example.com/", "psi")
        assert key1 != key2

    def test_cache_key_is_sha1_hex(self):
        """Key should be a 40-char hex string (SHA1)."""
        key = _cache_key("https://example.com/", "html")
        assert len(key) == 40
        assert all(c in "0123456789abcdef" for c in key)

    def test_cache_key_same_for_normalized_urls(self):
        """Normalized URLs should produce same cache key."""
        url1 = "https://example.com"
        url2 = "https://EXAMPLE.COM/"
        # Normalize first, then generate key
        norm1 = normalize_url(url1)
        norm2 = normalize_url(url2)
        assert _cache_key(norm1, "html") == _cache_key(norm2, "html")


# ---------------------------------------------------------------------------
# TTL Expiration Tests
# ---------------------------------------------------------------------------

class TestTTLExpiration:
    """Test TTL-based cache expiration."""

    def test_is_expired_false_for_fresh_entry(self):
        """Fresh entry should not be expired."""
        now = _utc_now()
        assert _is_expired(now, 3600) is False

    def test_is_expired_true_for_old_entry(self):
        """Old entry should be expired."""
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        assert _is_expired(old_time, 3600) is True  # 1 hour TTL

    def test_is_expired_false_when_ttl_zero(self):
        """TTL of 0 means never expire."""
        old_time = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        assert _is_expired(old_time, 0) is False

    def test_is_expired_handles_invalid_timestamp(self):
        """Invalid timestamp should be treated as expired."""
        assert _is_expired("not-a-timestamp", 3600) is True
        assert _is_expired("", 3600) is True
        assert _is_expired(None, 3600) is True

    def test_expired_cache_is_ignored(self, tmp_path):
        """Expired cache entries should return None."""
        cache = CacheManager(tmp_path, enabled=True, ttl_seconds=1)

        # Write an entry
        entry_data = create_html_cache_data(
            url="https://example.com",
            http_status=200,
            final_url=None,
            response_time_ms=100,
            third_party_script_count=0,
            tracking={},
            tracking_evidence={},
            tech_cms=None,
            tech_framework=None,
            tech_ecommerce=None,
            tech_hosting_hints=[],
            tech_confidence={},
            business_signals={},
        )
        cache.set_html("https://example.com", entry_data)

        # Verify it's cached
        assert cache.get_html("https://example.com") is not None

        # Wait for TTL to expire
        time.sleep(1.5)

        # Should now be None (expired)
        result = cache.get_html("https://example.com")
        assert result is None


# ---------------------------------------------------------------------------
# Schema Version Tests
# ---------------------------------------------------------------------------

class TestSchemaVersion:
    """Test schema version handling."""

    def test_schema_version_mismatch_invalidates_cache(self, tmp_path):
        """Cache with old schema version should be invalidated."""
        cache = CacheManager(tmp_path, enabled=True)

        # Create a cache entry with old schema version
        old_entry = {
            "meta": {
                "created_utc": _utc_now(),
                "normalized_url": "https://example.com/",
                "schema_version": CACHE_SCHEMA_VERSION - 1,  # Old version
                "ttl_seconds": DEFAULT_TTL_SECONDS,
                "is_partial": False,
            },
            "url": "https://example.com",
            "http_status": 200,
            "final_url": None,
            "response_time_ms": 100,
            "third_party_script_count": 0,
            "tracking": {},
            "tracking_evidence": {},
            "tech_cms": None,
            "tech_framework": None,
            "tech_ecommerce": None,
            "tech_hosting_hints": [],
            "tech_confidence": {},
            "business_signals": {},
        }

        # Write directly to cache file
        normalized = normalize_url("https://example.com")
        cache_path = cache._html_path(normalized)
        with open(cache_path, "w") as f:
            json.dump(old_entry, f)

        # Should return None due to schema mismatch
        result = cache.get_html("https://example.com")
        assert result is None

    def test_current_schema_version_accepted(self, tmp_path):
        """Cache with current schema version should be accepted."""
        cache = CacheManager(tmp_path, enabled=True)

        entry_data = create_html_cache_data(
            url="https://example.com",
            http_status=200,
            final_url=None,
            response_time_ms=100,
            third_party_script_count=0,
            tracking={},
            tracking_evidence={},
            tech_cms=None,
            tech_framework=None,
            tech_ecommerce=None,
            tech_hosting_hints=[],
            tech_confidence={},
            business_signals={},
        )
        cache.set_html("https://example.com", entry_data)

        result = cache.get_html("https://example.com")
        assert result is not None
        assert result.meta.schema_version == CACHE_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# CacheManager Tests
# ---------------------------------------------------------------------------

class TestCacheManager:
    """Test CacheManager read/write operations."""

    def test_html_cache_round_trip(self, tmp_path):
        """Should write and read HTML cache entries."""
        cache = CacheManager(tmp_path, enabled=True)

        entry_data = create_html_cache_data(
            url="https://example.com",
            http_status=200,
            final_url="https://example.com/",
            response_time_ms=150,
            third_party_script_count=5,
            tracking={"ga4": True, "gtm": False},
            tracking_evidence={"ga4": ["G-TEST123"]},
            tech_cms="WordPress",
            tech_framework=None,
            tech_ecommerce=None,
            tech_hosting_hints=["Cloudflare"],
            tech_confidence={"cms": 0.9, "framework": 0.0, "ecommerce": 0.0, "hosting": 0.9},
            business_signals={
                "has_careers_page": True,
                "has_pricing_page": False,
                "has_services_page": True,
            },
        )

        cache.set_html("https://example.com", entry_data)

        retrieved = cache.get_html("https://example.com")
        assert retrieved is not None
        assert retrieved.url == "https://example.com"
        assert retrieved.http_status == 200
        assert retrieved.tracking["ga4"] is True
        assert retrieved.tracking_evidence["ga4"] == ["G-TEST123"]
        assert retrieved.tech_cms == "WordPress"
        assert retrieved.business_signals["has_careers_page"] is True
        # Check metadata
        assert retrieved.meta.schema_version == CACHE_SCHEMA_VERSION
        assert retrieved.meta.is_partial is False

    def test_psi_cache_round_trip(self, tmp_path):
        """Should write and read PSI cache entries."""
        cache = CacheManager(tmp_path, enabled=True)

        entry_data = create_psi_cache_data(
            url="https://example.com",
            strategy="mobile",
            performance=65,
            seo=78,
            accessibility=85,
            best_practices=90,
            lcp_ms=3500,
            inp_ms=250,
            cls=0.15,
            ttfb_ms=800,
            fcp_ms=2000,
            opportunities=[{"id": "uses-webp-images", "title": "Use WebP images"}],
            diagnostics=[{"id": "dom-size", "title": "Reduce DOM size"}],
        )

        cache.set_psi("https://example.com", "mobile", entry_data)

        retrieved = cache.get_psi("https://example.com", "mobile")
        assert retrieved is not None
        assert retrieved.performance == 65
        assert retrieved.seo == 78
        assert retrieved.lcp_ms == 3500
        assert len(retrieved.opportunities) == 1
        assert retrieved.opportunities[0]["id"] == "uses-webp-images"

    def test_psi_cache_strategy_specific(self, tmp_path):
        """PSI cache should be strategy-specific."""
        cache = CacheManager(tmp_path, enabled=True)

        mobile_data = create_psi_cache_data(
            url="https://example.com", strategy="mobile", performance=50,
            seo=None, accessibility=None, best_practices=None,
            lcp_ms=None, inp_ms=None, cls=None, ttfb_ms=None, fcp_ms=None,
            opportunities=[], diagnostics=[],
        )

        desktop_data = create_psi_cache_data(
            url="https://example.com", strategy="desktop", performance=80,
            seo=None, accessibility=None, best_practices=None,
            lcp_ms=None, inp_ms=None, cls=None, ttfb_ms=None, fcp_ms=None,
            opportunities=[], diagnostics=[],
        )

        cache.set_psi("https://example.com", "mobile", mobile_data)
        cache.set_psi("https://example.com", "desktop", desktop_data)

        mobile = cache.get_psi("https://example.com", "mobile")
        desktop = cache.get_psi("https://example.com", "desktop")

        assert mobile.performance == 50
        assert desktop.performance == 80

    def test_cache_miss_returns_none(self, tmp_path):
        """Missing cache entry should return None."""
        cache = CacheManager(tmp_path, enabled=True)

        assert cache.get_html("https://never-cached.com") is None
        assert cache.get_psi("https://never-cached.com", "mobile") is None

    def test_disabled_cache_does_not_write(self, tmp_path):
        """Disabled cache should not write files."""
        cache = CacheManager(tmp_path, enabled=False)

        entry_data = create_html_cache_data(
            url="https://example.com",
            http_status=200,
            final_url=None,
            response_time_ms=None,
            third_party_script_count=0,
            tracking={},
            tracking_evidence={},
            tech_cms=None,
            tech_framework=None,
            tech_ecommerce=None,
            tech_hosting_hints=[],
            tech_confidence={},
            business_signals={},
        )

        cache.set_html("https://example.com", entry_data)

        # Should not have written anything
        assert cache.get_html("https://example.com") is None
        assert list(tmp_path.glob("*.json")) == []

    def test_disabled_cache_always_returns_none(self, tmp_path):
        """Disabled cache should always return None on get."""
        cache = CacheManager(tmp_path, enabled=False)

        assert cache.get_html("https://example.com") is None
        assert cache.get_psi("https://example.com", "mobile") is None

    def test_cache_clear(self, tmp_path):
        """Clear should remove all cache files."""
        cache = CacheManager(tmp_path, enabled=True)

        # Write some entries
        entry_data = create_html_cache_data(
            url="https://example.com",
            http_status=200,
            final_url=None,
            response_time_ms=None,
            third_party_script_count=0,
            tracking={},
            tracking_evidence={},
            tech_cms=None,
            tech_framework=None,
            tech_ecommerce=None,
            tech_hosting_hints=[],
            tech_confidence={},
            business_signals={},
        )
        cache.set_html("https://example.com", entry_data)

        # Verify file exists
        assert len(list(tmp_path.glob("*.json"))) > 0

        # Clear
        count = cache.clear()
        assert count > 0

        # Verify cleared
        assert list(tmp_path.glob("*.json")) == []
        assert cache.get_html("https://example.com") is None

    def test_corrupted_cache_returns_none(self, tmp_path):
        """Corrupted cache file should return None, not crash."""
        cache = CacheManager(tmp_path, enabled=True)

        # Write a valid entry
        entry_data = create_html_cache_data(
            url="https://example.com",
            http_status=200,
            final_url=None,
            response_time_ms=None,
            third_party_script_count=0,
            tracking={},
            tracking_evidence={},
            tech_cms=None,
            tech_framework=None,
            tech_ecommerce=None,
            tech_hosting_hints=[],
            tech_confidence={},
            business_signals={},
        )
        cache.set_html("https://example.com", entry_data)

        # Corrupt the file
        cache_files = list(tmp_path.glob("*.json"))
        assert len(cache_files) == 1
        with open(cache_files[0], "w") as f:
            f.write("not valid json {{{")

        # Should return None, not raise
        result = cache.get_html("https://example.com")
        assert result is None

    def test_partial_results_cached_when_enabled(self, tmp_path):
        """Partial results should be cached when cache_partial=True."""
        cache = CacheManager(tmp_path, enabled=True, cache_partial=True)

        entry_data = create_html_cache_data(
            url="https://example.com",
            http_status=200,
            final_url=None,
            response_time_ms=None,
            third_party_script_count=0,
            tracking={},
            tracking_evidence={},
            tech_cms=None,
            tech_framework=None,
            tech_ecommerce=None,
            tech_hosting_hints=[],
            tech_confidence={},
            business_signals={},
        )
        cache.set_html("https://example.com", entry_data, is_partial=True)

        result = cache.get_html("https://example.com")
        assert result is not None
        assert result.meta.is_partial is True

    def test_partial_results_not_cached_when_disabled(self, tmp_path):
        """Partial results should not be cached when cache_partial=False."""
        cache = CacheManager(tmp_path, enabled=True, cache_partial=False)

        entry_data = create_html_cache_data(
            url="https://example.com",
            http_status=200,
            final_url=None,
            response_time_ms=None,
            third_party_script_count=0,
            tracking={},
            tracking_evidence={},
            tech_cms=None,
            tech_framework=None,
            tech_ecommerce=None,
            tech_hosting_hints=[],
            tech_confidence={},
            business_signals={},
        )
        cache.set_html("https://example.com", entry_data, is_partial=True)

        # Should not have cached
        assert cache.get_html("https://example.com") is None

    def test_normalized_url_produces_same_cache(self, tmp_path):
        """URLs that normalize to same value should hit same cache."""
        cache = CacheManager(tmp_path, enabled=True)

        # Write with UTM params
        entry_data = create_html_cache_data(
            url="https://example.com?utm_source=test",
            http_status=200,
            final_url=None,
            response_time_ms=100,
            third_party_script_count=0,
            tracking={},
            tracking_evidence={},
            tech_cms=None,
            tech_framework=None,
            tech_ecommerce=None,
            tech_hosting_hints=[],
            tech_confidence={},
            business_signals={},
        )
        cache.set_html("https://example.com?utm_source=test", entry_data)

        # Should be able to retrieve with different tracking params
        result = cache.get_html("https://example.com?fbclid=xyz")
        assert result is not None

        # Or without any params
        result = cache.get_html("https://example.com")
        assert result is not None

    def test_cache_stats(self, tmp_path):
        """get_stats should return correct cache statistics."""
        cache = CacheManager(tmp_path, enabled=True, ttl_seconds=3600)

        # Add some entries
        for i in range(3):
            entry_data = create_html_cache_data(
                url=f"https://example{i}.com",
                http_status=200,
                final_url=None,
                response_time_ms=100,
                third_party_script_count=0,
                tracking={},
                tracking_evidence={},
                tech_cms=None,
                tech_framework=None,
                tech_ecommerce=None,
                tech_hosting_hints=[],
                tech_confidence={},
                business_signals={},
            )
            cache.set_html(f"https://example{i}.com", entry_data)

        stats = cache.get_stats()
        assert stats["total_files"] == 3
        assert stats["total_bytes"] > 0
        assert stats["ttl_seconds"] == 3600
        assert stats["schema_version"] == CACHE_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# load_existing_leads Tests
# ---------------------------------------------------------------------------

class TestLoadExistingLeads:
    """Test resume functionality with existing leads."""

    def test_load_existing_leads(self, tmp_path):
        """Should load leads keyed by URL."""
        leads_file = tmp_path / "leads.json"
        leads_data = [
            {"url": "https://a.com", "domain": "a.com", "score_points": 50},
            {"url": "https://b.com", "domain": "b.com", "score_points": 70},
        ]
        with open(leads_file, "w") as f:
            json.dump(leads_data, f)

        result = load_existing_leads(leads_file)

        assert "https://a.com" in result
        assert "https://b.com" in result
        assert result["https://a.com"]["score_points"] == 50

    def test_load_nonexistent_file(self, tmp_path):
        """Should return empty dict for missing file."""
        result = load_existing_leads(tmp_path / "missing.json")
        assert result == {}

    def test_load_invalid_json(self, tmp_path):
        """Should return empty dict for invalid JSON."""
        leads_file = tmp_path / "leads.json"
        with open(leads_file, "w") as f:
            f.write("not json")

        result = load_existing_leads(leads_file)
        assert result == {}

    def test_load_leads_includes_normalized_urls(self, tmp_path):
        """Should include both original and normalized URLs."""
        leads_file = tmp_path / "leads.json"
        leads_data = [
            {"url": "https://example.com", "domain": "example.com"},
        ]
        with open(leads_file, "w") as f:
            json.dump(leads_data, f)

        result = load_existing_leads(leads_file)

        # Both original and normalized should work
        assert "https://example.com" in result
        assert "https://example.com/" in result  # Normalized version
