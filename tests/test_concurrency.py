"""Tests for pipeline concurrency and rate limiting."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch, call

import pytest

from src.utils.rate_limit import TokenBucket, RateLimiter, get_psi_limiter
from src.pipeline.runner import (
    run_pipeline,
    _run_concurrent_stage,
    _process_html_single,
    _process_psi_single,
    StageResult,
)
from src.models.lead_audit import LeadAudit
from src.utils.cache import CacheManager


# ---------------------------------------------------------------------------
# TokenBucket Tests
# ---------------------------------------------------------------------------

class TestTokenBucket:
    """Test token bucket rate limiter."""

    def test_initial_tokens_equals_burst(self):
        """Bucket should start with burst tokens available."""
        bucket = TokenBucket(rate_per_minute=60, burst=5)
        assert bucket.available_tokens == 5.0

    def test_burst_defaults_to_rate(self):
        """Burst should default to rate_per_minute if not specified."""
        bucket = TokenBucket(rate_per_minute=30)
        assert bucket.burst == 30

    def test_acquire_consumes_token(self):
        """Acquiring should consume one token."""
        bucket = TokenBucket(rate_per_minute=60, burst=5)
        initial = bucket.available_tokens
        bucket.acquire()
        # Use tolerance for floating point comparison (small refill during execution)
        assert abs(bucket.available_tokens - (initial - 1)) < 0.01

    def test_try_acquire_nonblocking(self):
        """try_acquire should not block when no tokens."""
        bucket = TokenBucket(rate_per_minute=60, burst=1)
        # Consume the only token
        assert bucket.try_acquire() is True
        # Should return immediately without blocking
        start = time.monotonic()
        assert bucket.try_acquire() is False
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # Should be nearly instant

    def test_acquire_blocks_until_token_available(self):
        """acquire should block when no tokens are available."""
        # Very high rate so tokens refill quickly
        bucket = TokenBucket(rate_per_minute=600, burst=1)
        bucket.acquire()  # Consume the token

        start = time.monotonic()
        bucket.acquire()  # Should block briefly then succeed
        elapsed = time.monotonic() - start

        # At 600/min = 10/sec, we need ~0.1s for 1 token
        assert elapsed > 0.05  # Some blocking occurred
        assert elapsed < 0.5   # But not too long

    def test_acquire_timeout_expires(self):
        """acquire should return False when timeout expires."""
        bucket = TokenBucket(rate_per_minute=1, burst=1)  # Very slow refill
        bucket.acquire()  # Consume the token

        start = time.monotonic()
        result = bucket.acquire(timeout=0.1)
        elapsed = time.monotonic() - start

        assert result is False
        assert elapsed >= 0.1
        assert elapsed < 0.3

    def test_tokens_refill_over_time(self):
        """Tokens should refill based on elapsed time."""
        bucket = TokenBucket(rate_per_minute=600, burst=10)  # 10 tokens/sec
        # Consume all tokens
        for _ in range(10):
            bucket.try_acquire()
        assert bucket.available_tokens < 1

        # Wait and check refill
        time.sleep(0.2)  # Should add ~2 tokens
        tokens = bucket.available_tokens
        assert tokens >= 1.5
        assert tokens <= 3.0

    def test_tokens_cap_at_burst(self):
        """Tokens should not exceed burst limit."""
        bucket = TokenBucket(rate_per_minute=6000, burst=5)  # Fast refill
        time.sleep(0.1)  # Let it try to refill
        assert bucket.available_tokens <= 5.0

    def test_rate_limiter_blocks_over_limit_calls(self):
        """Rate limiter should block calls that exceed the limit (mocked time)."""
        # Create a bucket with 2 tokens and slow refill
        bucket = TokenBucket(rate_per_minute=60, burst=2)

        # First two should succeed immediately
        assert bucket.try_acquire() is True
        assert bucket.try_acquire() is True

        # Third should fail (no blocking, just check)
        assert bucket.try_acquire() is False

    def test_concurrent_acquire_thread_safe(self):
        """Multiple threads acquiring should not cause race conditions."""
        bucket = TokenBucket(rate_per_minute=1000, burst=100)
        acquired_count = [0]

        def worker():
            for _ in range(10):
                if bucket.try_acquire():
                    acquired_count[0] += 1

        threads = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker) for _ in range(10)]
            for f in futures:
                f.result()

        # Should have acquired exactly 100 (the burst amount)
        assert acquired_count[0] == 100


# ---------------------------------------------------------------------------
# RateLimiter Manager Tests
# ---------------------------------------------------------------------------

class TestRateLimiter:
    """Test RateLimiter manager."""

    def test_get_or_create_creates_limiter(self):
        """Should create limiter on first access."""
        limiter = RateLimiter()
        bucket = limiter.get_or_create("test", rate_per_minute=60)
        assert isinstance(bucket, TokenBucket)
        assert bucket.rate_per_minute == 60

    def test_get_or_create_returns_same_limiter(self):
        """Should return same limiter for same name."""
        limiter = RateLimiter()
        bucket1 = limiter.get_or_create("test", rate_per_minute=60)
        bucket2 = limiter.get_or_create("test", rate_per_minute=100)  # Different rate ignored
        assert bucket1 is bucket2

    def test_get_psi_limiter_singleton(self):
        """get_psi_limiter should return consistent limiter."""
        limiter1 = get_psi_limiter(60)
        limiter2 = get_psi_limiter(60)
        assert limiter1 is limiter2


# ---------------------------------------------------------------------------
# Pipeline Concurrency Tests
# ---------------------------------------------------------------------------

class TestPipelineConcurrency:
    """Test pipeline uses ThreadPoolExecutor for concurrency."""

    def test_concurrent_stage_uses_executor_when_concurrency_gt_1(self):
        """Should use ThreadPoolExecutor when concurrency > 1."""
        results = []

        def mock_worker(lead, **kwargs):
            time.sleep(0.05)  # Simulate work
            return StageResult(url=lead.url, success=True, cached=False, elapsed_ms=50)

        leads = [
            (LeadAudit.from_url(f"https://site{i}.com", "mobile"), {})
            for i in range(5)
        ]

        # With concurrency=1, should take ~250ms (sequential)
        start_seq = time.monotonic()
        _run_concurrent_stage(leads, mock_worker, concurrency=1, stage_name="Test")
        elapsed_seq = time.monotonic() - start_seq

        # With concurrency=5, should take ~50ms (parallel)
        start_par = time.monotonic()
        _run_concurrent_stage(leads, mock_worker, concurrency=5, stage_name="Test")
        elapsed_par = time.monotonic() - start_par

        # Parallel should be significantly faster
        assert elapsed_par < elapsed_seq * 0.6

    def test_concurrent_stage_returns_all_results(self):
        """Should return results for all items regardless of concurrency."""
        def mock_worker(lead, **kwargs):
            return StageResult(url=lead.url, success=True, cached=False, elapsed_ms=10)

        leads = [
            (LeadAudit.from_url(f"https://site{i}.com", "mobile"), {})
            for i in range(10)
        ]

        results, _ = _run_concurrent_stage(leads, mock_worker, concurrency=4, stage_name="Test")
        assert len(results) == 10

    def test_concurrent_stage_handles_exceptions(self):
        """Should handle worker exceptions gracefully."""
        def mock_worker(lead, **kwargs):
            if "fail" in lead.url:
                raise ValueError("Intentional failure")
            return StageResult(url=lead.url, success=True, cached=False, elapsed_ms=10)

        leads = [
            (LeadAudit.from_url("https://ok.com", "mobile"), {}),
            (LeadAudit.from_url("https://fail.com", "mobile"), {}),
            (LeadAudit.from_url("https://ok2.com", "mobile"), {}),
        ]

        results, _ = _run_concurrent_stage(leads, mock_worker, concurrency=3, stage_name="Test")

        assert len(results) == 3
        success_count = sum(1 for r in results if r.success)
        error_count = sum(1 for r in results if r.error)
        assert success_count == 2
        assert error_count == 1


class TestPipelineOutputSchema:
    """Test pipeline produces identical output schema regardless of concurrency."""

    @pytest.fixture
    def mock_html_response(self):
        """Mock HTML response."""
        from src.utils.http import HTMLResponse
        return HTMLResponse(
            status=200,
            final_url="https://example.com/",
            body="""
            <html>
            <head><title>Test</title></head>
            <body>
                <script src="https://www.googletagmanager.com/gtag/js?id=G-TEST123"></script>
            </body>
            </html>
            """,
            headers={"server": "nginx"},
            elapsed_ms=100,
        )

    @pytest.fixture
    def mock_psi_response(self):
        """Mock PSI API response."""
        return {
            "lighthouseResult": {
                "categories": {
                    "performance": {"score": 0.65},
                    "seo": {"score": 0.80},
                    "accessibility": {"score": 0.85},
                    "best-practices": {"score": 0.90},
                },
                "audits": {
                    "largest-contentful-paint": {"numericValue": 3500},
                    "cumulative-layout-shift": {"numericValue": 0.1},
                    "first-contentful-paint": {"numericValue": 2000},
                },
            }
        }

    def test_output_schema_consistent_across_concurrency(
        self, tmp_path, mock_html_response, mock_psi_response
    ):
        """Output should have same schema with concurrency=1 and concurrency=4."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("psi_api_key: ''\nrate_limit_per_min: 1000\n")

        urls = ["https://example.com"]

        with patch("src.audits.html_inspector.fetch_html") as mock_fetch_html, \
             patch("src.audits.psi.fetch_json") as mock_fetch_json:

            mock_fetch_html.return_value = mock_html_response
            mock_fetch_json.return_value = mock_psi_response

            # Run with concurrency=1
            leads_seq = run_pipeline(
                urls=urls,
                strategy="mobile",
                concurrency=1,
                config_path=str(config_file),
                output_dir=str(tmp_path / "out1"),
                use_cache=False,
            )

            # Run with concurrency=4
            leads_par = run_pipeline(
                urls=urls,
                strategy="mobile",
                concurrency=4,
                config_path=str(config_file),
                output_dir=str(tmp_path / "out2"),
                use_cache=False,
            )

        # Compare schema (not exact values since timestamps differ)
        assert len(leads_seq) == len(leads_par) == 1

        lead_seq = leads_seq[0]
        lead_par = leads_par[0]

        # Check all expected fields exist
        expected_fields = [
            "lead_id", "url", "domain", "strategy", "status",
            "html_meta", "tracking", "tracking_evidence", "tech", "tech_confidence",
            "business_signals", "scores", "cwv", "psi_opportunities", "psi_diagnostics",
            "score_letter", "score_points", "score_reasons",
            "roi_priority", "roi_reasons", "pains", "outreach_en",
        ]

        seq_dict = lead_seq.model_dump()
        par_dict = lead_par.model_dump()

        for field in expected_fields:
            assert field in seq_dict, f"Missing field in sequential: {field}"
            assert field in par_dict, f"Missing field in parallel: {field}"

        # Values that should be identical
        assert lead_seq.url == lead_par.url
        assert lead_seq.domain == lead_par.domain
        assert lead_seq.strategy == lead_par.strategy
        assert lead_seq.scores.model_dump() == lead_par.scores.model_dump()
        assert lead_seq.score_letter == lead_par.score_letter
        assert lead_seq.score_points == lead_par.score_points


class TestPipelineRateLimiting:
    """Test that PSI requests respect rate limits."""

    def test_psi_stage_acquires_rate_limit_token(self, tmp_path):
        """PSI processing should acquire token from rate limiter."""
        mock_limiter = MagicMock()
        mock_limiter.acquire.return_value = True

        lead = LeadAudit.from_url("https://example.com", "mobile")
        cache = CacheManager(tmp_path, enabled=False)

        with patch("src.audits.psi.fetch_json") as mock_fetch:
            mock_fetch.return_value = {
                "lighthouseResult": {
                    "categories": {"performance": {"score": 0.5}},
                    "audits": {},
                }
            }

            _process_psi_single(
                lead=lead,
                cache=cache,
                api_key="",
                timeout=30,
                max_retries=3,
                cache_enabled=False,
                rate_limiter=mock_limiter,
            )

        mock_limiter.acquire.assert_called_once()

    def test_psi_stage_skips_rate_limit_on_cache_hit(self, tmp_path):
        """PSI cache hit should not consume rate limit token."""
        mock_limiter = MagicMock()

        # Set up cache with existing entry using new API
        cache = CacheManager(tmp_path, enabled=True)
        from src.utils.cache import create_psi_cache_data
        entry_data = create_psi_cache_data(
            url="https://example.com",
            strategy="mobile",
            performance=65,
            seo=80,
            accessibility=85,
            best_practices=90,
            lcp_ms=3000,
            inp_ms=200,
            cls=0.1,
            ttfb_ms=500,
            fcp_ms=1500,
            opportunities=[],
            diagnostics=[],
        )
        cache.set_psi("https://example.com", "mobile", entry_data)

        lead = LeadAudit.from_url("https://example.com", "mobile")

        result = _process_psi_single(
            lead=lead,
            cache=cache,
            api_key="",
            timeout=30,
            max_retries=3,
            cache_enabled=True,
            rate_limiter=mock_limiter,
        )

        # Should have gotten cache hit
        assert result.cached is True
        # Rate limiter should NOT have been called
        mock_limiter.acquire.assert_not_called()


# ---------------------------------------------------------------------------
# Integration-like Tests
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    """Higher-level integration tests for pipeline."""

    def test_resume_skips_existing_leads(self, tmp_path):
        """Resume mode should skip URLs already in leads.json."""
        import json

        # Create existing leads.json
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        existing_lead = {
            "lead_id": "abc123",
            "url": "https://existing.com",
            "domain": "existing.com",
            "strategy": "mobile",
            "status": "complete",
            "timestamp_utc": "2024-01-01T00:00:00Z",
            "html_meta": {
                "http_status": 200,
                "final_url": "https://existing.com/",
                "response_time_ms": 100,
                "third_party_script_count": 0,
            },
            "tracking": {"ga4": False, "gtm": False, "ua": False, "meta_pixel": False,
                        "hotjar": False, "clarity": False, "segment": False,
                        "mixpanel": False, "linkedin_insight": False, "tiktok_pixel": False},
            "tracking_evidence": {},
            "tech": {"cms": None, "framework": None, "ecommerce": None, "hosting_hints": []},
            "tech_confidence": {},
            "business_signals": {
                "has_careers_page": False,
                "has_pricing_page": False,
                "has_services_page": False,
                "has_contact_form": False,
                "has_ecommerce": False,
                "has_multiple_locations_hint": False,
                "languages_hint": [],
                "phone_present": False,
                "email_present": False,
                "social_links_count": 0,
            },
            "scores": {"performance": 65, "seo": 80, "accessibility": 85, "best_practices": 90},
            "cwv": {"lcp_ms": 3000, "inp_ms": None, "cls": 0.1, "ttfb_ms": None, "fcp_ms": None},
            "psi_opportunities": [],
            "psi_diagnostics": [],
            "score_letter": "B",
            "score_points": 50,
            "score_reasons": [],
            "roi_priority": "medium",
            "roi_reasons": [],
            "pains": [],
            "outreach_en": None,
            "errors": [],
        }
        with open(out_dir / "leads.json", "w") as f:
            json.dump([existing_lead], f)

        config_file = tmp_path / "config.yaml"
        config_file.write_text("psi_api_key: ''\n")

        # Run pipeline with resume - should skip existing URL
        with patch("src.audits.html_inspector.fetch_html") as mock_html, \
             patch("src.audits.psi.fetch_json") as mock_psi:

            leads = run_pipeline(
                urls=["https://existing.com", "https://new.com"],
                strategy="mobile",
                concurrency=1,
                config_path=str(config_file),
                output_dir=str(out_dir),
                use_cache=False,
                resume=True,
            )

        # Should have called fetch only for new.com
        # (existing.com was skipped)
        assert mock_html.call_count == 1
        assert "new.com" in str(mock_html.call_args)
