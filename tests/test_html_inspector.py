"""Tests for HTML inspector detection logic."""

import pytest

from src.models.lead_audit import LeadAudit
from src.audits.html_inspector import (
    TRACKING_PATTERNS,
    CMS_SIGNALS,
    FRAMEWORK_SIGNALS,
    ECOMMERCE_SIGNALS,
    _detect_best,
    _count_third_party_scripts,
)


# ---------------------------------------------------------------------------
# HTML Fixtures
# ---------------------------------------------------------------------------

HTML_GTM = """
<!DOCTYPE html>
<html>
<head>
    <script>(function(w,d,s,l,i){w[l]=w[l]||[];})(window,document,'script','dataLayer','GTM-ABC123');</script>
</head>
<body>Hello</body>
</html>
"""

HTML_GA4 = """
<!DOCTYPE html>
<html>
<head>
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-ABCDEF123"></script>
</head>
<body>Hello</body>
</html>
"""

HTML_META_PIXEL = """
<!DOCTYPE html>
<html>
<head>
    <script>
        !function(f,b,e,v,n,t,s){...}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');
        fbq('init', '1234567890');
    </script>
</head>
<body>Hello</body>
</html>
"""

HTML_WORDPRESS = """
<!DOCTYPE html>
<html>
<head>
    <meta name="generator" content="WordPress 6.4.2" />
    <link rel="stylesheet" href="/wp-content/themes/theme/style.css">
    <script src="/wp-includes/js/jquery.js"></script>
</head>
<body>Hello</body>
</html>
"""

HTML_SHOPIFY = """
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="https://cdn.shopify.com/s/files/theme.css">
    <script>Shopify.theme = {name: "Dawn"};</script>
</head>
<body>Hello</body>
</html>
"""

HTML_NEXTJS = """
<!DOCTYPE html>
<html>
<head></head>
<body>
    <div id="__next">Content</div>
    <script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>
</body>
</html>
"""

HTML_MIXED = """
<!DOCTYPE html>
<html>
<head>
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-TEST123"></script>
    <script>(function(w,d,s,l,i){w[l]=w[l]||[];})(window,document,'script','dataLayer','GTM-XYZ789');</script>
    <link rel="stylesheet" href="/wp-content/themes/theme/style.css">
</head>
<body>Hello</body>
</html>
"""

HTML_WITH_SCRIPTS = """
<!DOCTYPE html>
<html>
<head>
    <script src="https://cdn.otherdomain.com/lib.js"></script>
    <script src="https://analytics.google.com/analytics.js"></script>
    <script src="https://connect.facebook.net/sdk.js"></script>
    <script src="/local/script.js"></script>
    <script src="https://example.com/same-domain.js"></script>
</head>
<body>Hello</body>
</html>
"""


# ---------------------------------------------------------------------------
# Tracking Detection Tests
# ---------------------------------------------------------------------------

class TestTrackingDetection:
    """Test tracking pixel detection patterns."""

    def test_detect_gtm(self):
        """Should detect Google Tag Manager."""
        for field, pattern in TRACKING_PATTERNS:
            if field == "gtm":
                match = pattern.search(HTML_GTM)
                assert match is not None
                # Should capture the GTM ID
                assert "GTM-ABC123" in match.group()
                break

    def test_detect_ga4(self):
        """Should detect GA4."""
        for field, pattern in TRACKING_PATTERNS:
            if field == "ga4":
                match = pattern.search(HTML_GA4)
                assert match is not None
                # Should capture the G- ID
                assert "G-ABCDEF123" in match.group()
                break

    def test_detect_meta_pixel(self):
        """Should detect Meta Pixel via connect.facebook.net."""
        for field, pattern in TRACKING_PATTERNS:
            if field == "meta_pixel":
                assert pattern.search(HTML_META_PIXEL) is not None
                break

    def test_no_false_positive_on_clean_html(self):
        """Should not detect tracking on clean HTML."""
        clean_html = "<html><head></head><body>Hello</body></html>"
        for field, pattern in TRACKING_PATTERNS:
            assert pattern.search(clean_html) is None


# ---------------------------------------------------------------------------
# Tracking Evidence Dict Shape
# ---------------------------------------------------------------------------

class TestTrackingEvidenceShape:
    """Test that tracking_evidence is a dict with list values."""

    def test_evidence_dict_structure(self):
        """tracking_evidence should be dict[str, list[str]]."""
        # Simulate what html_inspector produces
        tracking_evidence: dict[str, list[str]] = {}

        for field, pat in TRACKING_PATTERNS:
            if field == "gtm":
                matches = pat.findall(HTML_GTM)
                if matches:
                    tracking_evidence[field] = [m[:80] if isinstance(m, str) else m for m in matches[:5]]

        assert "gtm" in tracking_evidence
        assert isinstance(tracking_evidence["gtm"], list)
        assert len(tracking_evidence["gtm"]) > 0
        assert "GTM-ABC123" in tracking_evidence["gtm"][0]

    def test_evidence_captures_ga4_id(self):
        """Should capture GA4 ID in evidence."""
        tracking_evidence: dict[str, list[str]] = {}

        for field, pat in TRACKING_PATTERNS:
            if field == "ga4":
                matches = pat.findall(HTML_GA4)
                if matches:
                    tracking_evidence[field] = [m[:80] if isinstance(m, str) else m for m in matches[:5]]

        assert "ga4" in tracking_evidence
        assert "G-ABCDEF123" in tracking_evidence["ga4"][0]


# ---------------------------------------------------------------------------
# CMS Detection Tests
# ---------------------------------------------------------------------------

class TestCMSDetection:
    """Test CMS detection patterns."""

    def test_detect_wordpress(self):
        """Should detect WordPress via wp-content, wp-includes, generator."""
        label, count, evidence, conf = _detect_best(HTML_WORDPRESS, CMS_SIGNALS)
        assert label == "WordPress"
        assert count >= 2
        assert conf > 0

    def test_detect_shopify(self):
        """Should detect Shopify via cdn.shopify.com."""
        label, count, evidence, conf = _detect_best(HTML_SHOPIFY, CMS_SIGNALS)
        assert label == "Shopify"
        assert count >= 1
        assert conf > 0


# ---------------------------------------------------------------------------
# Framework Detection Tests
# ---------------------------------------------------------------------------

class TestFrameworkDetection:
    """Test framework detection patterns."""

    def test_detect_nextjs(self):
        """Should detect Next.js via __NEXT_DATA__."""
        label, count, evidence, conf = _detect_best(HTML_NEXTJS, FRAMEWORK_SIGNALS)
        assert label == "Next.js"
        assert conf > 0


# ---------------------------------------------------------------------------
# Third-Party Script Count Tests
# ---------------------------------------------------------------------------

class TestThirdPartyScriptCount:
    """Test third-party script counting."""

    def test_count_external_scripts(self):
        """Should count external scripts, excluding same-domain."""
        count = _count_third_party_scripts(HTML_WITH_SCRIPTS, "example.com")
        # cdn.otherdomain.com, analytics.google.com, connect.facebook.net = 3
        # /local/script.js is relative, excluded
        # example.com/same-domain.js is same domain, excluded
        assert count == 3

    def test_empty_html_gives_zero(self):
        """Empty HTML should have 0 third-party scripts."""
        count = _count_third_party_scripts("<html></html>", "example.com")
        assert count == 0

    def test_only_relative_scripts(self):
        """Only relative scripts should give 0."""
        html = '<script src="/js/app.js"></script><script src="./lib.js"></script>'
        count = _count_third_party_scripts(html, "example.com")
        assert count == 0


# ---------------------------------------------------------------------------
# Mixed Detection Tests
# ---------------------------------------------------------------------------

class TestMixedDetection:
    """Test detection on HTML with multiple signals."""

    def test_mixed_html_detects_multiple(self):
        """Should detect GA4, GTM, and WordPress in mixed HTML."""
        # Check tracking
        ga4_found = False
        gtm_found = False
        for field, pattern in TRACKING_PATTERNS:
            if field == "ga4" and pattern.search(HTML_MIXED):
                ga4_found = True
            if field == "gtm" and pattern.search(HTML_MIXED):
                gtm_found = True
        assert ga4_found
        assert gtm_found

        # Check CMS
        label, count, evidence, conf = _detect_best(HTML_MIXED, CMS_SIGNALS)
        assert label == "WordPress"


# ---------------------------------------------------------------------------
# Tech Confidence Tests
# ---------------------------------------------------------------------------

class TestTechConfidence:
    """Test that tech_confidence dict is properly structured."""

    def test_confidence_returns_float(self):
        """Confidence should be a float between 0 and 1."""
        label, count, evidence, conf = _detect_best(HTML_WORDPRESS, CMS_SIGNALS)
        assert isinstance(conf, float)
        assert 0 <= conf <= 1

    def test_no_match_gives_zero_confidence(self):
        """No match should give 0 confidence."""
        label, count, evidence, conf = _detect_best("<html></html>", CMS_SIGNALS)
        assert label is None
        assert conf == 0
