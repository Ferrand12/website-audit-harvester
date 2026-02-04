"""Tests for PSI client validation and observability."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
import io

import pytest

from src.audits.psi import (
    validate_api_key,
    PSIValidationError,
    PSIStats,
    get_psi_stats,
    reset_psi_stats,
    _build_url,
    VALIDATION_URL,
    PSI_ENDPOINT,
)
from src.pipeline.runner import validate_psi_api_key


# ---------------------------------------------------------------------------
# PSI URL Building Tests
# ---------------------------------------------------------------------------

class TestBuildUrl:
    """Test PSI URL building."""

    def test_build_url_without_key(self):
        """URL should be built without key parameter."""
        url = _build_url("https://example.com", "mobile", "")
        assert PSI_ENDPOINT in url
        assert "url=" in url
        assert "strategy=mobile" in url
        assert "key=" not in url

    def test_build_url_with_key(self):
        """URL should include key parameter when provided."""
        url = _build_url("https://example.com", "mobile", "test-api-key")
        assert "key=test-api-key" in url

    def test_build_url_with_categories(self):
        """URL should include category parameters."""
        url = _build_url("https://example.com", "mobile", "", categories=["performance"])
        assert "category=performance" in url

    def test_build_url_default_categories(self):
        """URL should include all default categories."""
        url = _build_url("https://example.com", "mobile", "")
        assert "category=performance" in url
        assert "category=seo" in url
        assert "category=accessibility" in url
        assert "category=best-practices" in url


# ---------------------------------------------------------------------------
# API Key Validation Tests
# ---------------------------------------------------------------------------

class TestValidateApiKey:
    """Test PSI API key validation."""

    def test_empty_key_returns_true(self):
        """Empty key should return True (no validation needed)."""
        result = validate_api_key("")
        assert result is True

    def test_none_key_returns_true(self):
        """None key should return True."""
        result = validate_api_key(None)
        assert result is True

    @patch("src.audits.psi.fetch_json")
    def test_valid_key_returns_true(self, mock_fetch):
        """Valid key should return True."""
        mock_fetch.return_value = {"lighthouseResult": {"categories": {}}}
        result = validate_api_key("valid-key")
        assert result is True
        mock_fetch.assert_called_once()

    @patch("src.audits.psi.fetch_json")
    def test_invalid_key_raises_error_401(self, mock_fetch):
        """Invalid key (401) should raise PSIValidationError."""
        mock_fetch.side_effect = HTTPError(
            url="", code=401, msg="Unauthorized", hdrs={}, fp=io.BytesIO()
        )
        with pytest.raises(PSIValidationError) as exc_info:
            validate_api_key("invalid-key")
        assert exc_info.value.http_code == 401
        assert "Unauthorized" in str(exc_info.value)

    @patch("src.audits.psi.fetch_json")
    def test_forbidden_key_raises_error_403(self, mock_fetch):
        """Forbidden key (403) should raise PSIValidationError."""
        mock_fetch.side_effect = HTTPError(
            url="", code=403, msg="Forbidden", hdrs={}, fp=io.BytesIO()
        )
        with pytest.raises(PSIValidationError) as exc_info:
            validate_api_key("forbidden-key")
        assert exc_info.value.http_code == 403
        assert "Forbidden" in str(exc_info.value)

    @patch("src.audits.psi.fetch_json")
    def test_bad_request_raises_error_400(self, mock_fetch):
        """Bad request (400) should raise PSIValidationError."""
        mock_fetch.side_effect = HTTPError(
            url="", code=400, msg="Bad Request", hdrs={}, fp=io.BytesIO()
        )
        with pytest.raises(PSIValidationError) as exc_info:
            validate_api_key("malformed-key")
        assert exc_info.value.http_code == 400

    @patch("src.audits.psi.fetch_json")
    def test_rate_limited_returns_true(self, mock_fetch):
        """Rate limited (429) should return True (key is valid)."""
        mock_fetch.side_effect = HTTPError(
            url="", code=429, msg="Too Many Requests", hdrs={}, fp=io.BytesIO()
        )
        result = validate_api_key("rate-limited-key")
        assert result is True

    @patch("src.audits.psi.fetch_json")
    def test_network_error_returns_true(self, mock_fetch):
        """Network errors should return True (can't determine validity)."""
        mock_fetch.side_effect = ConnectionError("Network unreachable")
        result = validate_api_key("some-key")
        assert result is True

    @patch("src.audits.psi.fetch_json")
    def test_validation_uses_lightweight_request(self, mock_fetch):
        """Validation should use minimal categories."""
        mock_fetch.return_value = {}
        validate_api_key("test-key")
        call_url = mock_fetch.call_args[0][0]
        # Should use VALIDATION_URL
        assert VALIDATION_URL.replace("https://", "") in call_url
        # Should only request performance category
        assert "category=performance" in call_url
        # Should not request all categories
        assert call_url.count("category=") == 1


class TestValidatePsiApiKeyInRunner:
    """Test validate_psi_api_key function in runner."""

    @patch("src.pipeline.runner.validate_api_key")
    def test_empty_key_skips_validation(self, mock_validate):
        """Empty key should not trigger validation call."""
        validate_psi_api_key("")
        mock_validate.assert_not_called()

    @patch("src.pipeline.runner.validate_api_key")
    def test_valid_key_passes(self, mock_validate):
        """Valid key should pass without raising."""
        mock_validate.return_value = True
        validate_psi_api_key("valid-key")  # Should not raise
        mock_validate.assert_called_once()

    @patch("src.pipeline.runner.validate_api_key")
    def test_invalid_key_exits(self, mock_validate):
        """Invalid key should raise SystemExit."""
        mock_validate.side_effect = PSIValidationError("Invalid key", http_code=401)
        with pytest.raises(SystemExit) as exc_info:
            validate_psi_api_key("invalid-key")
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# PSI Stats Tests
# ---------------------------------------------------------------------------

class TestPSIStats:
    """Test PSI statistics tracking."""

    def test_initial_stats_zero(self):
        """Fresh stats should be all zeros."""
        stats = PSIStats()
        assert stats.calls_made == 0
        assert stats.cache_hits == 0
        assert stats.rate_limited_waits == 0
        assert stats.errors == 0

    def test_record_call_increments(self):
        """record_call should increment calls_made."""
        stats = PSIStats()
        stats.record_call()
        stats.record_call()
        assert stats.calls_made == 2

    def test_record_cache_hit_increments(self):
        """record_cache_hit should increment cache_hits."""
        stats = PSIStats()
        stats.record_cache_hit()
        assert stats.cache_hits == 1

    def test_record_rate_wait_increments(self):
        """record_rate_wait should increment rate_limited_waits."""
        stats = PSIStats()
        stats.record_rate_wait()
        stats.record_rate_wait()
        stats.record_rate_wait()
        assert stats.rate_limited_waits == 3

    def test_record_error_increments(self):
        """record_error should increment errors."""
        stats = PSIStats()
        stats.record_error()
        assert stats.errors == 1

    def test_summary_format(self):
        """summary should return formatted string."""
        stats = PSIStats()
        stats.calls_made = 10
        stats.cache_hits = 5
        stats.rate_limited_waits = 2
        stats.errors = 1
        summary = stats.summary()
        assert "PSI calls: 10" in summary
        assert "cache hits: 5" in summary
        assert "rate-limited waits: 2" in summary
        assert "errors: 1" in summary

    def test_thread_safety(self):
        """Stats should be thread-safe."""
        import threading
        stats = PSIStats()
        threads = []

        def increment():
            for _ in range(100):
                stats.record_call()

        for _ in range(10):
            t = threading.Thread(target=increment)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert stats.calls_made == 1000


class TestGlobalStats:
    """Test global PSI stats management."""

    def test_get_psi_stats_returns_instance(self):
        """get_psi_stats should return PSIStats instance."""
        stats = get_psi_stats()
        assert isinstance(stats, PSIStats)

    def test_reset_psi_stats_clears_stats(self):
        """reset_psi_stats should create fresh stats."""
        stats = get_psi_stats()
        stats.record_call()
        stats.record_call()
        assert stats.calls_made >= 2

        reset_psi_stats()
        new_stats = get_psi_stats()
        assert new_stats.calls_made == 0

    def test_get_psi_stats_returns_same_instance(self):
        """Multiple calls should return same instance."""
        reset_psi_stats()
        stats1 = get_psi_stats()
        stats2 = get_psi_stats()
        assert stats1 is stats2


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestPSIValidationIntegration:
    """Integration tests for PSI validation in pipeline."""

    @patch("src.audits.psi.fetch_json")
    @patch("src.audits.html_inspector.fetch_html")
    def test_pipeline_skips_validation_with_empty_key(self, mock_html, mock_psi, tmp_path):
        """Pipeline should skip validation when no API key."""
        from src.pipeline.runner import run_pipeline

        # Mock HTML response
        from src.utils.http import HTMLResponse
        mock_html.return_value = HTMLResponse(
            status=200, final_url="https://example.com/",
            body="<html></html>", headers={}, elapsed_ms=100
        )

        # Mock PSI response (will fail but that's OK)
        mock_psi.side_effect = HTTPError(
            url="", code=429, msg="Rate limited", hdrs={}, fp=io.BytesIO()
        )

        config_path = tmp_path / "config.yaml"
        config_path.write_text("psi_api_key: ''\n")

        # Should not raise SystemExit
        leads = run_pipeline(
            urls=["https://example.com"],
            strategy="mobile",
            concurrency=1,
            config_path=str(config_path),
            output_dir=str(tmp_path / "out"),
            use_cache=False,
        )

        assert len(leads) == 1

    @patch("src.pipeline.runner.validate_api_key")
    def test_pipeline_validates_key_when_provided(self, mock_validate, tmp_path):
        """Pipeline should validate key when provided."""
        from src.pipeline.runner import run_pipeline

        mock_validate.side_effect = PSIValidationError("Invalid", http_code=401)

        config_path = tmp_path / "config.yaml"
        config_path.write_text("psi_api_key: 'test-key'\n")

        with pytest.raises(SystemExit):
            run_pipeline(
                urls=["https://example.com"],
                strategy="mobile",
                concurrency=1,
                config_path=str(config_path),
                output_dir=str(tmp_path / "out"),
                use_cache=False,
            )

        mock_validate.assert_called_once_with("test-key", timeout=30)

    @patch("src.audits.psi.fetch_json")
    @patch("src.audits.html_inspector.fetch_html")
    def test_pipeline_can_skip_validation(self, mock_html, mock_psi, tmp_path):
        """Pipeline should skip validation when skip_psi_validation=True."""
        from src.pipeline.runner import run_pipeline

        # Mock HTML response
        from src.utils.http import HTMLResponse
        mock_html.return_value = HTMLResponse(
            status=200, final_url="https://example.com/",
            body="<html></html>", headers={}, elapsed_ms=100
        )

        # Mock PSI response
        mock_psi.return_value = {"lighthouseResult": {"categories": {}, "audits": {}}}

        config_path = tmp_path / "config.yaml"
        config_path.write_text("psi_api_key: 'potentially-invalid-key'\n")

        # Should not validate or raise
        leads = run_pipeline(
            urls=["https://example.com"],
            strategy="mobile",
            concurrency=1,
            config_path=str(config_path),
            output_dir=str(tmp_path / "out"),
            use_cache=False,
            skip_psi_validation=True,
        )

        assert len(leads) == 1
