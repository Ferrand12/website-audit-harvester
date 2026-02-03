"""Tests for cache utilities."""

import json
import pytest
from pathlib import Path

from src.utils.cache import (
    CacheManager,
    HTMLCacheEntry,
    PSICacheEntry,
    _cache_key,
    load_existing_leads,
)


# ---------------------------------------------------------------------------
# Cache Key Tests
# ---------------------------------------------------------------------------

class TestCacheKey:
    """Test cache key generation."""

    def test_cache_key_deterministic(self):
        """Same input should produce same key."""
        key1 = _cache_key("https://example.com", "html")
        key2 = _cache_key("https://example.com", "html")
        assert key1 == key2

    def test_cache_key_different_for_different_urls(self):
        """Different URLs should produce different keys."""
        key1 = _cache_key("https://example.com", "html")
        key2 = _cache_key("https://other.com", "html")
        assert key1 != key2

    def test_cache_key_different_for_different_suffix(self):
        """Different suffix should produce different keys."""
        key1 = _cache_key("https://example.com", "html")
        key2 = _cache_key("https://example.com", "psi")
        assert key1 != key2

    def test_cache_key_is_sha1_hex(self):
        """Key should be a 40-char hex string (SHA1)."""
        key = _cache_key("https://example.com", "html")
        assert len(key) == 40
        assert all(c in "0123456789abcdef" for c in key)


# ---------------------------------------------------------------------------
# CacheManager Tests
# ---------------------------------------------------------------------------

class TestCacheManager:
    """Test CacheManager read/write operations."""

    def test_html_cache_round_trip(self, tmp_path):
        """Should write and read HTML cache entries."""
        cache = CacheManager(tmp_path, enabled=True)

        entry = HTMLCacheEntry(
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

        cache.set_html(entry)

        retrieved = cache.get_html("https://example.com")
        assert retrieved is not None
        assert retrieved.url == "https://example.com"
        assert retrieved.http_status == 200
        assert retrieved.tracking["ga4"] is True
        assert retrieved.tracking_evidence["ga4"] == ["G-TEST123"]
        assert retrieved.tech_cms == "WordPress"
        assert retrieved.business_signals["has_careers_page"] is True

    def test_psi_cache_round_trip(self, tmp_path):
        """Should write and read PSI cache entries."""
        cache = CacheManager(tmp_path, enabled=True)

        entry = PSICacheEntry(
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

        cache.set_psi(entry)

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

        mobile_entry = PSICacheEntry(
            url="https://example.com",
            strategy="mobile",
            performance=50,
            seo=None, accessibility=None, best_practices=None,
            lcp_ms=None, inp_ms=None, cls=None, ttfb_ms=None, fcp_ms=None,
            opportunities=[], diagnostics=[],
        )

        desktop_entry = PSICacheEntry(
            url="https://example.com",
            strategy="desktop",
            performance=80,
            seo=None, accessibility=None, best_practices=None,
            lcp_ms=None, inp_ms=None, cls=None, ttfb_ms=None, fcp_ms=None,
            opportunities=[], diagnostics=[],
        )

        cache.set_psi(mobile_entry)
        cache.set_psi(desktop_entry)

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

        entry = HTMLCacheEntry(
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

        cache.set_html(entry)

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
        entry = HTMLCacheEntry(
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
        cache.set_html(entry)

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
        entry = HTMLCacheEntry(
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
        cache.set_html(entry)

        # Corrupt the file
        cache_files = list(tmp_path.glob("*.json"))
        assert len(cache_files) == 1
        with open(cache_files[0], "w") as f:
            f.write("not valid json {{{")

        # Should return None, not raise
        result = cache.get_html("https://example.com")
        assert result is None


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
