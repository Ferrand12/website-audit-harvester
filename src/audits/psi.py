"""PageSpeed Insights API client with validation and observability."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from urllib.error import HTTPError
from urllib.parse import urlencode

from src.models.lead_audit import CWV, LeadAudit, OpportunityItem, PSIScores
from src.utils.http import fetch_json

logger = logging.getLogger("harvester")

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CATEGORIES = ["performance", "seo", "accessibility", "best-practices"]

# URL for API key validation (lightweight, fast response)
VALIDATION_URL = "https://www.google.com"

# Lighthouse audit IDs for Core Web Vitals
CWV_MAP = {
    "largest-contentful-paint": "lcp_ms",
    "experimental-interaction-to-next-paint": "inp_ms",
    "interaction-to-next-paint": "inp_ms",
    "cumulative-layout-shift": "cls",
    "server-response-time": "ttfb_ms",
    "first-contentful-paint": "fcp_ms",
}


@dataclass
class PSIStats:
    """Thread-safe statistics for PSI API usage.

    Tracks API calls, cache hits, and rate-limited waits for observability.
    """
    calls_made: int = 0
    cache_hits: int = 0
    rate_limited_waits: int = 0
    errors: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_call(self) -> None:
        """Record a PSI API call."""
        with self._lock:
            self.calls_made += 1

    def record_cache_hit(self) -> None:
        """Record a cache hit (no API call needed)."""
        with self._lock:
            self.cache_hits += 1

    def record_rate_wait(self) -> None:
        """Record a rate-limited wait."""
        with self._lock:
            self.rate_limited_waits += 1

    def record_error(self) -> None:
        """Record an API error."""
        with self._lock:
            self.errors += 1

    def summary(self) -> str:
        """Get a summary string for logging."""
        with self._lock:
            return (
                f"PSI calls: {self.calls_made}, "
                f"cache hits: {self.cache_hits}, "
                f"rate-limited waits: {self.rate_limited_waits}, "
                f"errors: {self.errors}"
            )


# Global stats instance for the current run
_psi_stats = PSIStats()


def get_psi_stats() -> PSIStats:
    """Get the global PSI stats instance."""
    return _psi_stats


def reset_psi_stats() -> None:
    """Reset PSI stats (useful for testing)."""
    global _psi_stats
    _psi_stats = PSIStats()


class PSIValidationError(Exception):
    """Raised when PSI API key validation fails."""

    def __init__(self, message: str, http_code: int | None = None):
        super().__init__(message)
        self.http_code = http_code


def _build_url(target_url: str, strategy: str, api_key: str, categories: list[str] | None = None) -> str:
    """Build PSI API URL with given parameters.

    Args:
        target_url: URL to analyze.
        strategy: "mobile" or "desktop".
        api_key: Google API key (can be empty).
        categories: List of categories to request (defaults to all).

    Returns:
        Full PSI API URL.
    """
    cats = categories or CATEGORIES

    # PSI API wants category repeated; urlencode doesn't repeat keys,
    # so build manually.
    parts = [
        f"url={urlencode_value(target_url)}",
        f"strategy={strategy}",
    ]
    for cat in cats:
        parts.append(f"category={cat}")
    if api_key:
        parts.append(f"key={api_key}")
    return f"{PSI_ENDPOINT}?{'&'.join(parts)}"


def urlencode_value(v: str) -> str:
    """URL-encode a single value."""
    return urlencode({"k": v})[2:]  # strip 'k='


def validate_api_key(api_key: str, timeout: float = 15.0) -> bool:
    """Validate PSI API key by making a lightweight test request.

    Makes a minimal PSI request to verify the API key is valid.
    Does NOT count toward stats since this is a validation call.

    Args:
        api_key: Google API key to validate.
        timeout: Request timeout in seconds.

    Returns:
        True if key is valid.

    Raises:
        PSIValidationError: If key is invalid or API returns auth error.
    """
    if not api_key:
        # No key to validate
        return True

    # Build URL with only performance category for faster response
    url = _build_url(VALIDATION_URL, "mobile", api_key, categories=["performance"])

    logger.info("Validating PSI API key...")

    try:
        # Use minimal retries for validation
        fetch_json(url, timeout=timeout, max_retries=1)
        logger.info("PSI API key validated successfully")
        return True

    except HTTPError as exc:
        http_code = exc.code
        if http_code == 400:
            raise PSIValidationError(
                f"Invalid PSI API key: Bad request (HTTP 400). "
                f"Check that your API key is correctly formatted.",
                http_code=http_code,
            )
        elif http_code == 401:
            raise PSIValidationError(
                f"Invalid PSI API key: Unauthorized (HTTP 401). "
                f"The API key may be invalid or revoked.",
                http_code=http_code,
            )
        elif http_code == 403:
            raise PSIValidationError(
                f"Invalid PSI API key: Forbidden (HTTP 403). "
                f"The API key may not have PageSpeed Insights API enabled, "
                f"or quota may be exceeded.",
                http_code=http_code,
            )
        elif http_code == 429:
            # Rate limited - key is valid but quota exceeded
            logger.warning(
                "PSI API key validation rate-limited (HTTP 429). "
                "Key appears valid but quota may be low."
            )
            return True
        else:
            raise PSIValidationError(
                f"PSI API key validation failed: HTTP {http_code}",
                http_code=http_code,
            )

    except Exception as exc:
        # Network errors don't mean the key is invalid
        logger.warning("PSI API key validation failed due to network error: %s", exc)
        logger.warning("Proceeding anyway - key validity uncertain")
        return True


def _extract_scores(data: dict) -> PSIScores:
    cats = data.get("lighthouseResult", {}).get("categories", {})

    def score(key: str) -> int | None:
        cat = cats.get(key)
        if cat and cat.get("score") is not None:
            return round(cat["score"] * 100)
        return None

    return PSIScores(
        performance=score("performance"),
        seo=score("seo"),
        accessibility=score("accessibility"),
        best_practices=score("best-practices"),
    )


def _extract_cwv(data: dict) -> CWV:
    audits = data.get("lighthouseResult", {}).get("audits", {})
    values: dict[str, float | None] = {}
    for audit_id, field in CWV_MAP.items():
        audit = audits.get(audit_id)
        if audit and audit.get("numericValue") is not None:
            nv = audit["numericValue"]
            if field == "cls":
                values[field] = round(nv, 3)
            else:
                values[field] = round(nv)
    return CWV(**values)


def _classify_impact(audit: dict) -> str:
    """Heuristic impact classification from audit metadata."""
    nv = audit.get("numericValue")
    score = audit.get("score")
    if score is not None:
        if score <= 0.3:
            return "high"
        if score <= 0.7:
            return "medium"
        return "low"
    if nv is not None:
        if nv > 2000:
            return "high"
        if nv > 500:
            return "medium"
        return "low"
    return "medium"


def _extract_items(data: dict, section: str, limit: int = 3) -> list[OpportunityItem]:
    """Extract top items from opportunities or diagnostics."""
    lr = data.get("lighthouseResult", {})
    audits = lr.get("audits", {})
    # The category details list relevant audit refs
    perf = lr.get("categories", {}).get("performance", {})
    audit_refs = perf.get("auditRefs", [])
    group_refs = [r for r in audit_refs if r.get("group") == section]

    items: list[OpportunityItem] = []
    for ref in group_refs:
        aid = ref["id"]
        audit = audits.get(aid, {})
        # Skip passing audits
        if audit.get("score") is not None and audit["score"] >= 0.9:
            continue
        items.append(OpportunityItem(
            id=aid,
            title=audit.get("title", aid),
            impact=_classify_impact(audit),
        ))
        if len(items) >= limit:
            break
    return items


def run_psi_audit(
    lead: LeadAudit,
    *,
    api_key: str = "",
    timeout: float = 30.0,
    max_retries: int = 3,
    stats: PSIStats | None = None,
) -> None:
    """Fetch PSI data and populate lead in-place.

    On failure, sets status=partial and records error.

    Args:
        lead: LeadAudit to populate with PSI data.
        api_key: Google API key (optional).
        timeout: Request timeout in seconds.
        max_retries: Number of retries for transient errors.
        stats: PSIStats instance for observability (uses global if None).
    """
    psi_stats = stats or get_psi_stats()
    url = _build_url(lead.url, lead.strategy, api_key)

    logger.info("PSI request start: %s (strategy=%s)", lead.url, lead.strategy)

    try:
        data = fetch_json(url, timeout=timeout, max_retries=max_retries)
        psi_stats.record_call()
    except Exception as exc:
        logger.error("PSI failed for %s: %s", lead.url, exc)
        lead.status = "partial"
        lead.errors.append(f"PSI error: {exc}")
        psi_stats.record_call()
        psi_stats.record_error()
        return

    lead.scores = _extract_scores(data)
    lead.cwv = _extract_cwv(data)
    lead.psi_opportunities = _extract_items(data, "opportunities")
    lead.psi_diagnostics = _extract_items(data, "diagnostics")

    # Derive score_points and score_letter from performance score
    perf = lead.scores.performance
    if perf is not None:
        lead.score_points = perf
        if perf >= 90:
            lead.score_letter = "A"
        elif perf >= 50:
            lead.score_letter = "B"
        else:
            lead.score_letter = "C"

    lead.status = "complete"
    logger.info("PSI request end: %s scores=%s", lead.url, lead.scores.model_dump())
