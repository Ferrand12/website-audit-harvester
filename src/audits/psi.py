from __future__ import annotations

import logging
from urllib.parse import urlencode

from src.models.lead_audit import CWV, LeadAudit, OpportunityItem, PSIScores
from src.utils.http import fetch_json

logger = logging.getLogger("harvester")

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CATEGORIES = ["performance", "seo", "accessibility", "best-practices"]

# Lighthouse audit IDs for Core Web Vitals
CWV_MAP = {
    "largest-contentful-paint": "lcp_ms",
    "experimental-interaction-to-next-paint": "inp_ms",
    "interaction-to-next-paint": "inp_ms",
    "cumulative-layout-shift": "cls",
    "server-response-time": "ttfb_ms",
    "first-contentful-paint": "fcp_ms",
}


def _build_url(target_url: str, strategy: str, api_key: str) -> str:
    params: dict[str, str] = {
        "url": target_url,
        "strategy": strategy,
    }
    for cat in CATEGORIES:
        params.setdefault("category", "")  # handled below
    # PSI API wants category repeated; urlencode doesn't repeat keys,
    # so build manually.
    parts = [f"url={urlencode_value(target_url)}",
             f"strategy={strategy}"]
    for cat in CATEGORIES:
        parts.append(f"category={cat}")
    if api_key:
        parts.append(f"key={api_key}")
    return f"{PSI_ENDPOINT}?{'&'.join(parts)}"


def urlencode_value(v: str) -> str:
    """URL-encode a single value."""
    return urlencode({"k": v})[2:]  # strip 'k='


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
) -> None:
    """Fetch PSI data and populate lead in-place. On failure, sets status=partial."""
    url = _build_url(lead.url, lead.strategy, api_key)
    logger.info("PSI request start: %s (strategy=%s)", lead.url, lead.strategy)
    try:
        data = fetch_json(url, timeout=timeout, max_retries=max_retries)
    except Exception as exc:
        logger.error("PSI failed for %s: %s", lead.url, exc)
        lead.status = "partial"
        lead.errors.append(f"PSI error: {exc}")
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
