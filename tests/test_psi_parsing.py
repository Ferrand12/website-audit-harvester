"""Tests for PSI response parsing."""

import pytest

from src.audits.psi import _extract_scores, _extract_cwv, _extract_items


# ---------------------------------------------------------------------------
# Minimal PSI JSON Fixture
# ---------------------------------------------------------------------------

PSI_RESPONSE = {
    "lighthouseResult": {
        "categories": {
            "performance": {"score": 0.72},
            "seo": {"score": 0.91},
            "accessibility": {"score": 0.85},
            "best-practices": {"score": 0.78},
        },
        "audits": {
            "largest-contentful-paint": {
                "numericValue": 2500.0,
                "score": 0.65,
            },
            "first-contentful-paint": {
                "numericValue": 1200.0,
                "score": 0.8,
            },
            "cumulative-layout-shift": {
                "numericValue": 0.05,
                "score": 0.95,
            },
            "server-response-time": {
                "numericValue": 350.0,
                "score": 0.9,
            },
            "render-blocking-resources": {
                "id": "render-blocking-resources",
                "title": "Eliminate render-blocking resources",
                "score": 0.4,
                "numericValue": 1500,
            },
            "unused-javascript": {
                "id": "unused-javascript",
                "title": "Reduce unused JavaScript",
                "score": 0.3,
                "numericValue": 2500,
            },
            "uses-optimized-images": {
                "id": "uses-optimized-images",
                "title": "Efficiently encode images",
                "score": 0.5,
                "numericValue": 800,
            },
            "dom-size": {
                "id": "dom-size",
                "title": "Avoid an excessive DOM size",
                "score": 0.6,
                "numericValue": 1500,
            },
        },
        "auditRefs": [
            {"id": "render-blocking-resources", "group": "opportunities"},
            {"id": "unused-javascript", "group": "opportunities"},
            {"id": "uses-optimized-images", "group": "opportunities"},
            {"id": "dom-size", "group": "diagnostics"},
        ],
    }
}


# ---------------------------------------------------------------------------
# Score Extraction Tests
# ---------------------------------------------------------------------------

class TestScoreExtraction:
    """Test PSI score extraction."""

    def test_extract_performance_score(self):
        """Should extract performance score as 0-100 int."""
        scores = _extract_scores(PSI_RESPONSE)
        assert scores.performance == 72

    def test_extract_seo_score(self):
        """Should extract SEO score as 0-100 int."""
        scores = _extract_scores(PSI_RESPONSE)
        assert scores.seo == 91

    def test_extract_accessibility_score(self):
        """Should extract accessibility score."""
        scores = _extract_scores(PSI_RESPONSE)
        assert scores.accessibility == 85

    def test_extract_best_practices_score(self):
        """Should extract best practices score."""
        scores = _extract_scores(PSI_RESPONSE)
        assert scores.best_practices == 78

    def test_missing_category_returns_none(self):
        """Missing category should return None."""
        partial = {"lighthouseResult": {"categories": {}}}
        scores = _extract_scores(partial)
        assert scores.performance is None


# ---------------------------------------------------------------------------
# CWV Extraction Tests
# ---------------------------------------------------------------------------

class TestCWVExtraction:
    """Test Core Web Vitals extraction."""

    def test_extract_lcp(self):
        """Should extract LCP in milliseconds."""
        cwv = _extract_cwv(PSI_RESPONSE)
        assert cwv.lcp_ms == 2500

    def test_extract_fcp(self):
        """Should extract FCP in milliseconds."""
        cwv = _extract_cwv(PSI_RESPONSE)
        assert cwv.fcp_ms == 1200

    def test_extract_cls(self):
        """Should extract CLS as float."""
        cwv = _extract_cwv(PSI_RESPONSE)
        assert cwv.cls == 0.05

    def test_extract_ttfb(self):
        """Should extract TTFB in milliseconds."""
        cwv = _extract_cwv(PSI_RESPONSE)
        assert cwv.ttfb_ms == 350

    def test_missing_audit_returns_none(self):
        """Missing CWV audit should return None."""
        partial = {"lighthouseResult": {"audits": {}}}
        cwv = _extract_cwv(partial)
        assert cwv.lcp_ms is None
        assert cwv.inp_ms is None


# ---------------------------------------------------------------------------
# Opportunities/Diagnostics Extraction Tests
# ---------------------------------------------------------------------------

class TestItemsExtraction:
    """Test opportunities and diagnostics extraction."""

    def test_extract_opportunities(self):
        """Should extract top opportunities with impact."""
        # Need to restructure fixture to have auditRefs in categories.performance
        response = {
            "lighthouseResult": {
                "categories": {
                    "performance": {
                        "score": 0.72,
                        "auditRefs": [
                            {"id": "render-blocking-resources", "group": "opportunities"},
                            {"id": "unused-javascript", "group": "opportunities"},
                            {"id": "uses-optimized-images", "group": "opportunities"},
                            {"id": "dom-size", "group": "diagnostics"},
                        ],
                    }
                },
                "audits": PSI_RESPONSE["lighthouseResult"]["audits"],
            }
        }
        items = _extract_items(response, "opportunities", limit=3)
        assert len(items) <= 3
        assert all(item.id for item in items)
        assert all(item.title for item in items)
        assert all(item.impact in ("high", "medium", "low") for item in items)

    def test_extract_diagnostics(self):
        """Should extract diagnostics."""
        response = {
            "lighthouseResult": {
                "categories": {
                    "performance": {
                        "score": 0.72,
                        "auditRefs": [
                            {"id": "dom-size", "group": "diagnostics"},
                        ],
                    }
                },
                "audits": PSI_RESPONSE["lighthouseResult"]["audits"],
            }
        }
        items = _extract_items(response, "diagnostics", limit=3)
        assert len(items) >= 1
