"""URL normalization utilities for consistent caching and deduplication."""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# Query parameters to strip (tracking/analytics)
TRACKING_PARAMS = frozenset({
    # Google Analytics / Ads
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "gclid", "gclsrc", "dclid", "gbraid", "wbraid",
    # Facebook
    "fbclid", "fb_action_ids", "fb_action_types", "fb_source", "fb_ref",
    # Mailchimp
    "mc_cid", "mc_eid",
    # Microsoft / Bing
    "msclkid",
    # HubSpot
    "hsa_acc", "hsa_cam", "hsa_grp", "hsa_ad", "hsa_src", "hsa_tgt",
    "hsa_kw", "hsa_mt", "hsa_net", "hsa_ver",
    # Other common trackers
    "ref", "ref_src", "ref_url", "_ga", "_gl", "si",
})

# Default ports by scheme
DEFAULT_PORTS = {
    "http": 80,
    "https": 443,
    "ftp": 21,
}


def normalize_url(
    url: str,
    *,
    final_url: str | None = None,
    strip_fragment: bool = True,
    strip_tracking_params: bool = True,
    normalize_trailing_slash: bool = True,
    prefer_https: bool = True,
) -> str:
    """Normalize a URL for consistent caching and comparison.

    Normalization steps:
    1. Use final_url if provided (follows redirects)
    2. Lowercase scheme and host
    3. Strip default ports (:80 for http, :443 for https)
    4. Remove fragments (#...)
    5. Remove common tracking query params (utm_*, gclid, fbclid, etc.)
    6. Normalize trailing slash (add for path-only URLs)
    7. Optionally upgrade http to https

    Args:
        url: The URL to normalize.
        final_url: If provided, use this as the canonical URL (e.g., after redirects).
        strip_fragment: Remove URL fragments (#...).
        strip_tracking_params: Remove tracking query parameters.
        normalize_trailing_slash: Ensure consistent trailing slash handling.
        prefer_https: Upgrade http to https.

    Returns:
        Normalized URL string.
    """
    # Prefer final_url if available (handles redirects)
    target_url = final_url if final_url else url

    # Ensure URL has a scheme
    if not target_url.startswith(("http://", "https://", "//")):
        target_url = f"https://{target_url}"
    elif target_url.startswith("//"):
        target_url = f"https:{target_url}"

    try:
        parsed = urlparse(target_url)
    except Exception:
        # If parsing fails, return original
        return url

    # Lowercase scheme and host
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower() if parsed.hostname else ""

    # Upgrade http to https if preferred
    if prefer_https and scheme == "http":
        scheme = "https"

    # Strip default port
    port = parsed.port
    if port and port == DEFAULT_PORTS.get(scheme):
        port = None

    # Build netloc
    netloc = host
    if port:
        netloc = f"{host}:{port}"
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo = f"{userinfo}:{parsed.password}"
        netloc = f"{userinfo}@{netloc}"

    # Process path
    path = parsed.path or "/"

    # Normalize trailing slash for root/directory paths
    if normalize_trailing_slash:
        # Add trailing slash if path is empty or just "/"
        if path == "":
            path = "/"
        # For paths without file extension, ensure trailing slash
        elif not path.endswith("/") and "." not in path.split("/")[-1]:
            path = path + "/"

    # Process query string
    query = parsed.query
    if strip_tracking_params and query:
        params = parse_qs(query, keep_blank_values=True)
        # Filter out tracking params (case-insensitive)
        filtered_params = {
            k: v for k, v in params.items()
            if k.lower() not in TRACKING_PARAMS
        }
        # Sort params for consistency
        query = urlencode(sorted(filtered_params.items()), doseq=True)

    # Process fragment
    fragment = "" if strip_fragment else parsed.fragment

    # Rebuild URL
    normalized = urlunparse((scheme, netloc, path, "", query, fragment))

    return normalized


def extract_domain(url: str) -> str:
    """Extract the domain from a URL.

    Args:
        url: The URL to extract domain from.

    Returns:
        Domain string (lowercase).
    """
    if not url.startswith(("http://", "https://", "//")):
        url = f"https://{url}"

    try:
        parsed = urlparse(url)
        return (parsed.hostname or "").lower()
    except Exception:
        # Fallback: extract from path-like URL
        return url.split("/")[0].lower()


def urls_match(url1: str, url2: str) -> bool:
    """Check if two URLs point to the same resource after normalization.

    Args:
        url1: First URL.
        url2: Second URL.

    Returns:
        True if URLs match after normalization.
    """
    return normalize_url(url1) == normalize_url(url2)
