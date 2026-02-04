"""Export utilities for leads data."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from src.models.lead_audit import LeadAudit, OpportunityItem

# Maximum items to include in top3 columns
MAX_TOP_ITEMS = 3

# Stable column order for CSV export
# Designed for Excel/Sheets compatibility
CSV_COLUMNS = [
    # Identity
    "lead_id",
    "url",
    "domain",
    "timestamp_utc",
    "status",
    "strategy",
    # Scoring
    "score_letter",
    "score_points",
    "score_reasons",
    "roi_priority",
    "roi_reasons",
    # PSI scores
    "scores.performance",
    "scores.seo",
    "scores.accessibility",
    "scores.best_practices",
    # Core Web Vitals
    "cwv.lcp_ms",
    "cwv.inp_ms",
    "cwv.cls",
    "cwv.ttfb_ms",
    "cwv.fcp_ms",
    # PSI opportunities and diagnostics (human-readable)
    "psi_opportunities_titles",
    "psi_diagnostics_titles",
    # PSI opportunities and diagnostics (machine-readable JSON)
    "psi_opportunities_top3",
    "psi_diagnostics_top3",
    # HTML meta
    "html_meta.http_status",
    "html_meta.final_url",
    "html_meta.response_time_ms",
    "html_meta.third_party_script_count",
    # Tracking
    "tracking.ga4",
    "tracking.gtm",
    "tracking.ua",
    "tracking.meta_pixel",
    "tracking.hotjar",
    "tracking.clarity",
    "tracking.segment",
    "tracking.mixpanel",
    "tracking.linkedin_insight",
    "tracking.tiktok_pixel",
    "tracking_evidence",
    # Tech
    "tech.cms",
    "tech.framework",
    "tech.ecommerce",
    "tech.hosting_hints",
    "tech_confidence",
    # Business signals
    "business_signals.has_careers_page",
    "business_signals.has_pricing_page",
    "business_signals.has_services_page",
    "business_signals.has_contact_form",
    "business_signals.has_ecommerce",
    "business_signals.has_multiple_locations_hint",
    "business_signals.languages_hint",
    "business_signals.phone_present",
    "business_signals.email_present",
    "business_signals.social_links_count",
    # Business insights
    "pains_summary",
    "outreach_en.subject",
    "outreach_en.body",
    # Errors
    "errors",
]


def _flatten(d: dict, prefix: str = "") -> dict:
    """Flatten nested dicts; lists and dicts become JSON strings."""
    flat: dict = {}
    for k, v in d.items():
        key = k if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            # Check if this is a leaf dict that should be JSON-stringified
            if key in ("tracking_evidence", "tech_confidence"):
                flat[key] = json.dumps(v) if v else ""
            else:
                flat.update(_flatten(v, key))
        elif isinstance(v, list):
            flat[key] = json.dumps(v) if v else ""
        else:
            flat[key] = v
    return flat


def _pains_summary(lead: LeadAudit) -> str:
    """Compact summary of pains for CSV."""
    if not lead.pains:
        return ""
    return "; ".join(f"{p.pain_id}({p.severity})" for p in lead.pains)


def _opportunities_titles(items: list[OpportunityItem], max_items: int = MAX_TOP_ITEMS) -> str:
    """Format opportunity/diagnostic titles as pipe-separated string.

    Args:
        items: List of OpportunityItem objects.
        max_items: Maximum number of items to include.

    Returns:
        Pipe-separated titles string, or empty string if no items.

    Example:
        "Eliminate render-blocking resources|Reduce unused CSS|Serve images in modern formats"
    """
    if not items:
        return ""
    titles = [item.title for item in items[:max_items]]
    return "|".join(titles)


def _opportunities_json(items: list[OpportunityItem], max_items: int = MAX_TOP_ITEMS) -> str:
    """Format opportunities/diagnostics as compact JSON array.

    Args:
        items: List of OpportunityItem objects.
        max_items: Maximum number of items to include.

    Returns:
        Compact JSON string of [{id, title, impact}, ...], or "[]" if no items.

    Example:
        '[{"id":"render-blocking-resources","title":"Eliminate render-blocking resources","impact":"high"}]'
    """
    if not items:
        return "[]"
    top_items = items[:max_items]
    # Use compact JSON format for Excel compatibility
    data = [{"id": item.id, "title": item.title, "impact": item.impact} for item in top_items]
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def export_json(leads: list[LeadAudit], path: Path) -> None:
    """Export leads as a JSON array."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([lead.model_dump() for lead in leads], f, indent=2, ensure_ascii=False)


def export_csv(leads: list[LeadAudit], path: Path) -> None:
    """Export leads as CSV with stable column order. UTF-8 with BOM for Excel.

    Includes PSI opportunities and diagnostics in both human-readable (pipe-separated)
    and machine-readable (JSON) formats.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            flat = _flatten(lead.model_dump())

            # Add derived fields
            flat["pains_summary"] = _pains_summary(lead)

            # PSI opportunities (human-readable titles)
            flat["psi_opportunities_titles"] = _opportunities_titles(lead.psi_opportunities)
            flat["psi_diagnostics_titles"] = _opportunities_titles(lead.psi_diagnostics)

            # PSI opportunities (machine-readable JSON)
            flat["psi_opportunities_top3"] = _opportunities_json(lead.psi_opportunities)
            flat["psi_diagnostics_top3"] = _opportunities_json(lead.psi_diagnostics)

            writer.writerow(flat)
