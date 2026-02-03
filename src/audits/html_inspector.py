from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from src.models.lead_audit import HTMLMeta, TechInfo, TrackingInfo, BusinessSignals
from src.models.lead_audit import LeadAudit
from src.utils.http import fetch_html

logger = logging.getLogger("harvester")

# ---------------------------------------------------------------------------
# Tracking patterns: (field_name, regex_pattern)
# ---------------------------------------------------------------------------
TRACKING_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ga4",              re.compile(r"gtag/js\?id=(G-[A-Z0-9]+)", re.I)),
    ("gtm",              re.compile(r"(GTM-[A-Z0-9]{4,})", re.I)),
    ("ua",               re.compile(r"(UA-\d{4,}-\d{1,})", re.I)),
    ("meta_pixel",       re.compile(r"fbq\s*\(\s*['\"]init['\"]|connect\.facebook\.net", re.I)),
    ("hotjar",           re.compile(r"hotjar\.com|hj\s*\(\s*['\"]", re.I)),
    ("clarity",          re.compile(r"clarity\.ms/tag/", re.I)),
    ("segment",          re.compile(r"cdn\.segment\.com/analytics|analytics\.min\.js", re.I)),
    ("mixpanel",         re.compile(r"mixpanel\.com/libs|mixpanel\.init", re.I)),
    ("linkedin_insight", re.compile(r"snap\.licdn\.com/li\.lms-analytics|_linkedin_partner_id", re.I)),
    ("tiktok_pixel",     re.compile(r"analytics\.tiktok\.com|ttq\.load", re.I)),
]

# ---------------------------------------------------------------------------
# CMS detection: (label, patterns, weight per match)
# ---------------------------------------------------------------------------
CMS_SIGNALS: list[tuple[str, list[re.Pattern[str]], float]] = [
    ("WordPress", [
        re.compile(r"/wp-content/", re.I),
        re.compile(r"/wp-includes/", re.I),
        re.compile(r'<meta\s[^>]*name=["\']generator["\'][^>]*content=["\']WordPress', re.I),
    ], 0.35),
    ("Shopify", [
        re.compile(r"cdn\.shopify\.com", re.I),
        re.compile(r"Shopify\.theme", re.I),
    ], 0.5),
    ("Webflow", [
        re.compile(r"webflow\.io", re.I),
        re.compile(r"data-wf-page", re.I),
    ], 0.5),
    ("Wix", [
        re.compile(r"static\.parastorage\.com|wix\.com", re.I),
    ], 0.6),
    ("Squarespace", [
        re.compile(r"static\.squarespace\.com|squarespace-cdn", re.I),
    ], 0.6),
    ("Drupal", [
        re.compile(r"/sites/default/files|Drupal\.settings", re.I),
    ], 0.5),
    ("Joomla", [
        re.compile(r"/media/jui/|/administrator/|com_content", re.I),
    ], 0.4),
]

# ---------------------------------------------------------------------------
# Framework detection
# ---------------------------------------------------------------------------
FRAMEWORK_SIGNALS: list[tuple[str, list[re.Pattern[str]], float]] = [
    ("Next.js", [
        re.compile(r"__NEXT_DATA__", re.I),
        re.compile(r"/_next/static/", re.I),
    ], 0.5),
    ("Nuxt", [
        re.compile(r"__NUXT__", re.I),
        re.compile(r"/_nuxt/", re.I),
    ], 0.5),
    ("Gatsby", [
        re.compile(r"/gatsby-", re.I),
        re.compile(r"gatsby-focus-wrapper", re.I),
    ], 0.5),
    ("React", [
        re.compile(r"data-reactroot|_reactRootContainer|react\.production", re.I),
    ], 0.4),
    ("Vue", [
        re.compile(r"data-v-[0-9a-f]|Vue\.config|vue\.runtime", re.I),
    ], 0.4),
    ("Angular", [
        re.compile(r"ng-version=|ng-app=|angular\.min\.js", re.I),
    ], 0.5),
]

# ---------------------------------------------------------------------------
# Ecommerce detection
# ---------------------------------------------------------------------------
ECOMMERCE_SIGNALS: list[tuple[str, list[re.Pattern[str]], float]] = [
    ("WooCommerce", [
        re.compile(r"woocommerce|wc-cart", re.I),
    ], 0.6),
    ("Shopify", [
        re.compile(r"cdn\.shopify\.com|Shopify\.theme", re.I),
    ], 0.5),
    ("PrestaShop", [
        re.compile(r"prestashop|/modules/ps_", re.I),
    ], 0.5),
    ("Magento", [
        re.compile(r"mage/cookies|Magento_Ui|magento", re.I),
    ], 0.4),
]

# ---------------------------------------------------------------------------
# Hosting detection from response headers
# ---------------------------------------------------------------------------
HOSTING_HEADER_MAP: list[tuple[str, str, re.Pattern[str] | None]] = [
    ("Cloudflare",  "cf-ray",           None),
    ("Vercel",      "x-vercel-id",      None),
    ("Netlify",     "x-nf-request-id",  None),
]

HOSTING_SERVER_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("Apache",    re.compile(r"Apache", re.I)),
    ("Nginx",     re.compile(r"nginx", re.I)),
    ("LiteSpeed", re.compile(r"LiteSpeed", re.I)),
    ("IIS",       re.compile(r"Microsoft-IIS", re.I)),
]

# Pattern to find external script tags
SCRIPT_SRC_PATTERN = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.I)

# ---------------------------------------------------------------------------
# Business signals patterns
# ---------------------------------------------------------------------------
HREF_PATTERN = re.compile(r'href=["\']([^"\']*)["\']', re.I)
CAREERS_KEYWORDS = re.compile(r"careers|jobs|recrutement|emploi|karriere|carriere", re.I)
PRICING_KEYWORDS = re.compile(r"pricing|tarifs?|prices?|plans?|abonnement", re.I)
SERVICES_KEYWORDS = re.compile(r"services?|prestations?|solutions?|offerings?", re.I)
CONTACT_FORM_PATTERN = re.compile(
    r'<form[^>]*>.*?(email|contact|message|textarea).*?</form>',
    re.I | re.DOTALL
)
ECOMMERCE_HINTS = re.compile(r"cart|panier|checkout|add-to-cart|buy-now|shop", re.I)
LOCATIONS_KEYWORDS = re.compile(
    r"locations?|stores?|magasins?|agences?|nos agences|find us|nos boutiques|points de vente",
    re.I
)
ADDRESS_PATTERN = re.compile(
    r"\d{1,5}\s+[\w\s]+(?:street|st|avenue|ave|road|rd|boulevard|blvd|rue|avenue|place)",
    re.I
)
PHONE_PATTERN = re.compile(
    r"(?:\+\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{2,4}[-.\s]?\d{2,4}[-.\s]?\d{0,4}"
)
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
SOCIAL_DOMAINS = {
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
    "tiktok.com": "tiktok",
    "twitter.com": "twitter",
    "x.com": "twitter",
}
LANG_PATTERN = re.compile(r'<html[^>]*\slang=["\']([a-z]{2})', re.I)
META_LANG_PATTERN = re.compile(
    r'<meta[^>]*(?:http-equiv=["\']content-language["\'][^>]*content=["\']([^"\']+)|'
    r'name=["\']language["\'][^>]*content=["\']([^"\']+))',
    re.I
)


def _detect_best(
    html: str,
    signal_list: list[tuple[str, list[re.Pattern[str]], float]],
) -> tuple[str | None, int, list[str], float]:
    """Return (best_label, match_count, evidence, confidence) for the signal group with the most hits."""
    best_label: str | None = None
    best_count = 0
    best_weight = 0.0
    all_evidence: list[str] = []

    for label, patterns, weight in signal_list:
        hits: list[str] = []
        for pat in patterns:
            m = pat.search(html)
            if m:
                hits.append(m.group()[:80])
        if hits and len(hits) > best_count:
            best_label = label
            best_count = len(hits)
            best_weight = weight
        all_evidence.extend(f"{label}: {h}" for h in hits)

    # Confidence = base weight * min(match_count / max_patterns, 1.0)
    confidence = 0.0
    if best_label and best_count > 0:
        confidence = min(best_weight + (best_count - 1) * 0.15, 1.0)

    return best_label, best_count, all_evidence, round(confidence, 2)


def _count_third_party_scripts(html: str, page_domain: str) -> int:
    """Count external script tags that are not same-domain."""
    matches = SCRIPT_SRC_PATTERN.findall(html)
    count = 0
    for src in matches:
        if src.startswith("/") or src.startswith("data:"):
            continue
        try:
            parsed = urlparse(src)
            script_host = parsed.netloc.lower()
            if script_host and script_host != page_domain.lower():
                if not script_host.endswith(f".{page_domain.lower()}"):
                    count += 1
        except Exception:
            continue
    return count


def _extract_business_signals(html: str, ecommerce_detected: str | None) -> BusinessSignals:
    """Extract business ability-to-pay signals from HTML."""
    # Extract all hrefs for link analysis
    hrefs = HREF_PATTERN.findall(html)
    href_text = " ".join(hrefs)

    # Page type detection via links
    has_careers = bool(CAREERS_KEYWORDS.search(href_text))
    has_pricing = bool(PRICING_KEYWORDS.search(href_text))
    has_services = bool(SERVICES_KEYWORDS.search(href_text))

    # Contact form detection
    has_contact_form = bool(CONTACT_FORM_PATTERN.search(html))

    # Ecommerce: from tech detection OR cart/checkout hints
    has_ecommerce = bool(ecommerce_detected) or bool(ECOMMERCE_HINTS.search(html))

    # Multiple locations hint
    locations_match = LOCATIONS_KEYWORDS.search(html)
    address_matches = ADDRESS_PATTERN.findall(html)
    has_multiple_locations = bool(locations_match) or len(address_matches) >= 2

    # Languages detection
    languages: set[str] = set()
    lang_match = LANG_PATTERN.search(html)
    if lang_match:
        languages.add(lang_match.group(1).lower())
    meta_lang = META_LANG_PATTERN.search(html)
    if meta_lang:
        lang_val = meta_lang.group(1) or meta_lang.group(2)
        if lang_val:
            for lang in lang_val.split(","):
                lang = lang.strip().split("-")[0].lower()
                if len(lang) == 2:
                    languages.add(lang)

    # Phone and email presence
    phone_present = bool(PHONE_PATTERN.search(html))
    email_present = bool(EMAIL_PATTERN.search(html))

    # Social links count
    social_found: set[str] = set()
    for href in hrefs:
        href_lower = href.lower()
        for domain, platform in SOCIAL_DOMAINS.items():
            if domain in href_lower:
                social_found.add(platform)
                break

    return BusinessSignals(
        has_careers_page=has_careers,
        has_pricing_page=has_pricing,
        has_services_page=has_services,
        has_contact_form=has_contact_form,
        has_ecommerce=has_ecommerce,
        has_multiple_locations_hint=has_multiple_locations,
        languages_hint=sorted(languages),
        phone_present=phone_present,
        email_present=email_present,
        social_links_count=len(social_found),
    )


def run_html_inspection(lead: LeadAudit, *, timeout: float = 15.0) -> None:
    """Fetch homepage HTML and populate tracking + tech + business_signals fields."""
    logger.info("HTML inspect start: %s", lead.url)
    try:
        resp = fetch_html(lead.url, timeout=timeout)
    except Exception as exc:
        logger.error("HTML fetch failed for %s: %s", lead.url, exc)
        lead.errors.append(f"HTML fetch error: {exc}")
        if lead.status != "complete":
            lead.status = "partial"
        return

    html = resp.body

    # Count third-party scripts
    third_party_count = _count_third_party_scripts(html, lead.domain)

    # Meta
    lead.html_meta = HTMLMeta(
        http_status=resp.status,
        final_url=resp.final_url,
        response_time_ms=resp.elapsed_ms,
        third_party_script_count=third_party_count,
    )

    # --- Tracking -----------------------------------------------------------
    tracking_vals: dict[str, bool] = {}
    tracking_evidence: dict[str, list[str]] = {}

    for field, pat in TRACKING_PATTERNS:
        matches = pat.findall(html)
        if matches:
            tracking_vals[field] = True
            evidence_list = [m[:80] if isinstance(m, str) else m[0][:80] if m else "" for m in matches[:5]]
            tracking_evidence[field] = evidence_list
        else:
            tracking_vals[field] = False

    lead.tracking = TrackingInfo(**tracking_vals)
    lead.tracking_evidence = tracking_evidence

    # --- CMS ----------------------------------------------------------------
    cms_label, cms_hits, cms_ev, cms_conf = _detect_best(html, CMS_SIGNALS)

    # --- Framework ----------------------------------------------------------
    fw_label, fw_hits, fw_ev, fw_conf = _detect_best(html, FRAMEWORK_SIGNALS)

    # --- Ecommerce ----------------------------------------------------------
    ec_label, ec_hits, ec_ev, ec_conf = _detect_best(html, ECOMMERCE_SIGNALS)

    # --- Hosting hints from headers -----------------------------------------
    hosting: list[str] = []
    hosting_conf = 0.0
    for label, header_key, val_pat in HOSTING_HEADER_MAP:
        val = resp.headers.get(header_key)
        if val is not None:
            if val_pat is None or val_pat.search(val):
                hosting.append(label)
                hosting_conf = max(hosting_conf, 0.9)

    server = resp.headers.get("server", "")
    powered = resp.headers.get("x-powered-by", "")
    for hdr_val in (server, powered):
        for label, pat in HOSTING_SERVER_HINTS:
            if pat.search(hdr_val):
                if label not in hosting:
                    hosting.append(label)
                    hosting_conf = max(hosting_conf, 0.7)

    lead.tech = TechInfo(
        cms=cms_label,
        framework=fw_label,
        ecommerce=ec_label,
        hosting_hints=hosting,
    )

    lead.tech_confidence = {
        "cms": cms_conf,
        "framework": fw_conf,
        "ecommerce": ec_conf,
        "hosting": round(hosting_conf, 2),
    }

    # --- Business signals ---------------------------------------------------
    lead.business_signals = _extract_business_signals(html, ec_label)

    logger.info(
        "HTML inspect end: %s  tracking=%d signals, tech=%s/%s/%s, hosting=%s, 3p_scripts=%d, biz_signals=%s",
        lead.url,
        sum(1 for v in tracking_vals.values() if v),
        cms_label, fw_label, ec_label, hosting, third_party_count,
        f"careers={lead.business_signals.has_careers_page},pricing={lead.business_signals.has_pricing_page}",
    )
