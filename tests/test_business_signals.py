"""Tests for business signals detection."""

import pytest

from src.models.lead_audit import BusinessSignals
from src.audits.html_inspector import _extract_business_signals


# ---------------------------------------------------------------------------
# HTML Fixtures
# ---------------------------------------------------------------------------

HTML_CAREERS = """
<!DOCTYPE html>
<html lang="en">
<head><title>Test</title></head>
<body>
    <nav>
        <a href="/about">About</a>
        <a href="/careers">Careers</a>
        <a href="/contact">Contact</a>
    </nav>
</body>
</html>
"""

HTML_JOBS_FR = """
<!DOCTYPE html>
<html lang="fr">
<head><title>Test</title></head>
<body>
    <nav>
        <a href="/recrutement">Recrutement</a>
        <a href="/emploi">Nos offres d'emploi</a>
    </nav>
</body>
</html>
"""

HTML_PRICING = """
<!DOCTYPE html>
<html lang="en">
<head><title>Test</title></head>
<body>
    <nav>
        <a href="/pricing">Pricing</a>
        <a href="/plans">Plans</a>
    </nav>
</body>
</html>
"""

HTML_SERVICES = """
<!DOCTYPE html>
<html lang="en">
<head><title>Test</title></head>
<body>
    <nav>
        <a href="/services">Our Services</a>
        <a href="/solutions">Solutions</a>
    </nav>
</body>
</html>
"""

HTML_CONTACT_FORM = """
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
    <form action="/contact" method="post">
        <input type="text" name="name">
        <input type="email" name="email">
        <textarea name="message"></textarea>
        <button type="submit">Send</button>
    </form>
</body>
</html>
"""

HTML_ECOMMERCE = """
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
    <a href="/cart">Cart</a>
    <button class="add-to-cart">Add to Cart</button>
    <a href="/checkout">Checkout</a>
</body>
</html>
"""

HTML_MULTIPLE_LOCATIONS = """
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
    <h2>Our Locations</h2>
    <p>123 Main Street, New York</p>
    <p>456 Oak Avenue, Los Angeles</p>
    <a href="/stores">Find a Store</a>
</body>
</html>
"""

HTML_WITH_CONTACT_INFO = """
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
    <p>Call us: +1 (555) 123-4567</p>
    <p>Email: contact@example.com</p>
</body>
</html>
"""

HTML_SOCIAL_LINKS = """
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
    <a href="https://facebook.com/company">Facebook</a>
    <a href="https://linkedin.com/company/acme">LinkedIn</a>
    <a href="https://twitter.com/company">Twitter</a>
    <a href="https://instagram.com/company">Instagram</a>
</body>
</html>
"""

HTML_MULTILINGUAL = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Test</title>
    <meta http-equiv="content-language" content="en,fr,de">
</head>
<body>
    <a href="/en">English</a>
    <a href="/fr">Français</a>
    <a href="/de">Deutsch</a>
</body>
</html>
"""

HTML_EMPTY = """
<!DOCTYPE html>
<html>
<head><title>Empty</title></head>
<body></body>
</html>
"""

HTML_COMPLETE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>ACME Corp</title>
    <meta http-equiv="content-language" content="en,fr">
</head>
<body>
    <nav>
        <a href="/">Home</a>
        <a href="/services">Services</a>
        <a href="/pricing">Pricing</a>
        <a href="/careers">Careers</a>
        <a href="/contact">Contact</a>
    </nav>

    <h2>Our Locations</h2>
    <p>123 Main Street, Chicago</p>
    <p>789 Oak Boulevard, Seattle</p>

    <form action="/contact" method="post">
        <input type="email" name="email">
        <textarea name="message"></textarea>
        <button>Submit</button>
    </form>

    <footer>
        <p>Call: +1-800-555-1234</p>
        <p>info@acme.com</p>
        <a href="https://linkedin.com/company/acme">LinkedIn</a>
        <a href="https://twitter.com/acme">Twitter</a>
    </footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Careers Page Detection
# ---------------------------------------------------------------------------

class TestCareersDetection:
    """Test careers/jobs page detection."""

    def test_detect_careers_link(self):
        """Should detect /careers link."""
        signals = _extract_business_signals(HTML_CAREERS, None)
        assert signals.has_careers_page is True

    def test_detect_french_jobs_terms(self):
        """Should detect French terms: recrutement, emploi."""
        signals = _extract_business_signals(HTML_JOBS_FR, None)
        assert signals.has_careers_page is True

    def test_no_careers_on_empty(self):
        """Should not detect careers on empty HTML."""
        signals = _extract_business_signals(HTML_EMPTY, None)
        assert signals.has_careers_page is False


# ---------------------------------------------------------------------------
# Pricing Page Detection
# ---------------------------------------------------------------------------

class TestPricingDetection:
    """Test pricing/plans page detection."""

    def test_detect_pricing_link(self):
        """Should detect /pricing and /plans links."""
        signals = _extract_business_signals(HTML_PRICING, None)
        assert signals.has_pricing_page is True

    def test_no_pricing_on_empty(self):
        """Should not detect pricing on empty HTML."""
        signals = _extract_business_signals(HTML_EMPTY, None)
        assert signals.has_pricing_page is False


# ---------------------------------------------------------------------------
# Services Page Detection
# ---------------------------------------------------------------------------

class TestServicesDetection:
    """Test services page detection."""

    def test_detect_services_link(self):
        """Should detect /services and /solutions links."""
        signals = _extract_business_signals(HTML_SERVICES, None)
        assert signals.has_services_page is True


# ---------------------------------------------------------------------------
# Contact Form Detection
# ---------------------------------------------------------------------------

class TestContactFormDetection:
    """Test contact form detection."""

    def test_detect_contact_form(self):
        """Should detect form with email/message fields."""
        signals = _extract_business_signals(HTML_CONTACT_FORM, None)
        assert signals.has_contact_form is True

    def test_no_form_on_empty(self):
        """Should not detect form on empty HTML."""
        signals = _extract_business_signals(HTML_EMPTY, None)
        assert signals.has_contact_form is False


# ---------------------------------------------------------------------------
# Ecommerce Detection
# ---------------------------------------------------------------------------

class TestEcommerceDetection:
    """Test ecommerce detection."""

    def test_detect_ecommerce_via_html(self):
        """Should detect cart/checkout hints in HTML."""
        signals = _extract_business_signals(HTML_ECOMMERCE, None)
        assert signals.has_ecommerce is True

    def test_detect_ecommerce_via_tech(self):
        """Should detect ecommerce via tech detection (WooCommerce)."""
        signals = _extract_business_signals(HTML_EMPTY, "WooCommerce")
        assert signals.has_ecommerce is True

    def test_no_ecommerce_on_empty(self):
        """Should not detect ecommerce on empty HTML without tech."""
        signals = _extract_business_signals(HTML_EMPTY, None)
        assert signals.has_ecommerce is False


# ---------------------------------------------------------------------------
# Multiple Locations Detection
# ---------------------------------------------------------------------------

class TestMultipleLocationsDetection:
    """Test multi-location business detection."""

    def test_detect_multiple_locations(self):
        """Should detect multiple addresses and location keywords."""
        signals = _extract_business_signals(HTML_MULTIPLE_LOCATIONS, None)
        assert signals.has_multiple_locations_hint is True

    def test_no_locations_on_empty(self):
        """Should not detect locations on empty HTML."""
        signals = _extract_business_signals(HTML_EMPTY, None)
        assert signals.has_multiple_locations_hint is False


# ---------------------------------------------------------------------------
# Contact Info Detection
# ---------------------------------------------------------------------------

class TestContactInfoDetection:
    """Test phone and email detection."""

    def test_detect_phone(self):
        """Should detect phone number."""
        signals = _extract_business_signals(HTML_WITH_CONTACT_INFO, None)
        assert signals.phone_present is True

    def test_detect_email(self):
        """Should detect email address."""
        signals = _extract_business_signals(HTML_WITH_CONTACT_INFO, None)
        assert signals.email_present is True

    def test_no_contact_on_empty(self):
        """Should not detect contact info on empty HTML."""
        signals = _extract_business_signals(HTML_EMPTY, None)
        assert signals.phone_present is False
        assert signals.email_present is False


# ---------------------------------------------------------------------------
# Social Links Detection
# ---------------------------------------------------------------------------

class TestSocialLinksDetection:
    """Test social media link detection."""

    def test_detect_social_links(self):
        """Should count unique social platforms."""
        signals = _extract_business_signals(HTML_SOCIAL_LINKS, None)
        # Facebook, LinkedIn, Twitter, Instagram = 4
        assert signals.social_links_count == 4

    def test_no_social_on_empty(self):
        """Should have 0 social links on empty HTML."""
        signals = _extract_business_signals(HTML_EMPTY, None)
        assert signals.social_links_count == 0


# ---------------------------------------------------------------------------
# Language Detection
# ---------------------------------------------------------------------------

class TestLanguageDetection:
    """Test language hint detection."""

    def test_detect_single_language(self):
        """Should detect language from html lang attribute."""
        signals = _extract_business_signals(HTML_CAREERS, None)
        assert "en" in signals.languages_hint

    def test_detect_multiple_languages(self):
        """Should detect multiple languages from meta tag."""
        signals = _extract_business_signals(HTML_MULTILINGUAL, None)
        assert "en" in signals.languages_hint
        assert "fr" in signals.languages_hint
        assert "de" in signals.languages_hint


# ---------------------------------------------------------------------------
# Complete Page Detection
# ---------------------------------------------------------------------------

class TestCompletePageDetection:
    """Test detection on complete HTML with multiple signals."""

    def test_complete_page_detects_all(self):
        """Should detect all signals on complete page."""
        signals = _extract_business_signals(HTML_COMPLETE, None)

        assert signals.has_careers_page is True
        assert signals.has_pricing_page is True
        assert signals.has_services_page is True
        assert signals.has_contact_form is True
        assert signals.has_multiple_locations_hint is True
        assert signals.phone_present is True
        assert signals.email_present is True
        assert signals.social_links_count >= 2
        assert "en" in signals.languages_hint


# ---------------------------------------------------------------------------
# BusinessSignals Model Tests
# ---------------------------------------------------------------------------

class TestBusinessSignalsModel:
    """Test BusinessSignals model defaults."""

    def test_default_values(self):
        """All booleans should default to False, lists empty, count 0."""
        signals = BusinessSignals()

        assert signals.has_careers_page is False
        assert signals.has_pricing_page is False
        assert signals.has_services_page is False
        assert signals.has_contact_form is False
        assert signals.has_ecommerce is False
        assert signals.has_multiple_locations_hint is False
        assert signals.languages_hint == []
        assert signals.phone_present is False
        assert signals.email_present is False
        assert signals.social_links_count == 0

    def test_model_dump(self):
        """Model should serialize to dict."""
        signals = BusinessSignals(
            has_careers_page=True,
            has_pricing_page=True,
            social_links_count=3,
        )

        data = signals.model_dump()
        assert data["has_careers_page"] is True
        assert data["has_pricing_page"] is True
        assert data["social_links_count"] == 3
