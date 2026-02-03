from __future__ import annotations

import logging

from src.models.lead_audit import LeadAudit

logger = logging.getLogger("harvester")

# ---------------------------------------------------------------------------
# Scoring rubric - Target Spec
# ---------------------------------------------------------------------------
# Total points 0-100, accumulated across categories:
#   - Performance/CWV: 0-35 pts
#   - SEO: 0-25 pts
#   - Accessibility + Best Practices: 0-15 pts
#   - Tracking maturity gap: 0-15 pts
#   - Tech opportunity: 0-10 pts
#
# Letter grades:
#   - A >= 70
#   - B 40-69
#   - C < 40
#
# Overrides:
#   - status == "failed" => C, 0 pts
#   - perf<=49 AND seo<=69 => minimum B
#   - (not GA4 or not GTM) AND seo<=84 => minimum B
# ---------------------------------------------------------------------------


def _perf_cwv_points(lead: LeadAudit) -> tuple[int, list[str]]:
    """Score performance and Core Web Vitals (max 35 pts)."""
    reasons: list[str] = []
    pts = 0
    perf = lead.scores.performance
    lcp = lead.cwv.lcp_ms
    inp = lead.cwv.inp_ms
    cls_val = lead.cwv.cls

    # Performance score component
    if perf is not None:
        if perf <= 49:
            pts += 20
            reasons.append(f"perf {perf}")
        elif perf <= 69:
            pts += 12
            reasons.append(f"perf {perf}")
        elif perf <= 89:
            pts += 5
        # >=90 => +0

    # CWV extras
    if lcp is not None and lcp > 4000:
        pts += 8
        if not any("perf" in r for r in reasons):
            reasons.append(f"LCP {lcp}ms")

    if inp is not None and inp > 300:
        pts += 5
        if not reasons:
            reasons.append(f"INP {inp}ms")

    if cls_val is not None and cls_val > 0.25:
        pts += 2
        if not reasons:
            reasons.append(f"CLS {cls_val}")

    return min(pts, 35), reasons


def _seo_points(lead: LeadAudit) -> tuple[int, list[str]]:
    """Score SEO (max 25 pts)."""
    reasons: list[str] = []
    pts = 0
    seo = lead.scores.seo

    if seo is not None:
        if seo <= 69:
            pts = 18
            reasons.append(f"seo {seo}")
        elif seo <= 84:
            pts = 10
            reasons.append(f"seo {seo}")
        elif seo <= 94:
            pts = 4
        # >=95 => +0

    return min(pts, 25), reasons


def _a11y_bp_points(lead: LeadAudit) -> tuple[int, list[str]]:
    """Score accessibility + best practices (max 15 pts)."""
    reasons: list[str] = []
    pts = 0
    a11y = lead.scores.accessibility
    bp = lead.scores.best_practices

    a11y_low = a11y is not None and a11y <= 79
    bp_low = bp is not None and bp <= 79

    if a11y_low:
        pts += 6
        reasons.append(f"a11y {a11y}")

    if bp_low:
        pts += 6
        reasons.append(f"bp {bp}")

    # Bonus if both are low
    if a11y_low and bp_low:
        pts += 3

    return min(pts, 15), reasons


def _tracking_gap_points(lead: LeadAudit) -> tuple[int, list[str]]:
    """Score tracking maturity gap (max 15 pts)."""
    reasons: list[str] = []
    pts = 0

    has_ga4 = lead.tracking.ga4
    has_gtm = lead.tracking.gtm

    if not has_ga4 and not has_gtm:
        pts = 15
        reasons.append("no GA4/GTM")
    elif not has_ga4 or not has_gtm:
        pts = 8
        missing = "GA4" if not has_ga4 else "GTM"
        reasons.append(f"no {missing}")
    # both present => +0

    return min(pts, 15), reasons


def _tech_opportunity_points(lead: LeadAudit) -> tuple[int, list[str]]:
    """Score tech opportunity (max 10 pts)."""
    reasons: list[str] = []
    pts = 0
    perf = lead.scores.performance

    # WordPress/WooCommerce and performance<=69 => +6
    cms = lead.tech.cms
    ecommerce = lead.tech.ecommerce
    if (cms == "WordPress" or ecommerce == "WooCommerce") and perf is not None and perf <= 69:
        pts += 6
        reasons.append(f"WP+perf{perf}")

    # Third-party scripts count >=15 => +4
    script_count = lead.html_meta.third_party_script_count
    if script_count >= 15:
        pts += 4
        reasons.append(f"{script_count} scripts")

    return min(pts, 10), reasons


def compute_score(lead: LeadAudit) -> None:
    """Compute score_points, score_letter, and score_reasons for a lead."""
    # Handle failed status
    if lead.status == "failed":
        lead.score_points = 0
        lead.score_letter = "C"
        lead.score_reasons = ["failed"]
        return

    all_reasons: list[str] = []

    # Accumulate points
    perf_pts, perf_r = _perf_cwv_points(lead)
    seo_pts, seo_r = _seo_points(lead)
    a11y_pts, a11y_r = _a11y_bp_points(lead)
    track_pts, track_r = _tracking_gap_points(lead)
    tech_pts, tech_r = _tech_opportunity_points(lead)

    total = perf_pts + seo_pts + a11y_pts + track_pts + tech_pts
    all_reasons.extend(perf_r + seo_r + track_r + a11y_r + tech_r)

    # Determine letter grade
    if total >= 70:
        letter = "A"
    elif total >= 40:
        letter = "B"
    else:
        letter = "C"

    # Override rules
    perf = lead.scores.performance
    seo = lead.scores.seo

    # Override 1: perf<=49 AND seo<=69 => minimum B
    if perf is not None and seo is not None:
        if perf <= 49 and seo <= 69:
            if letter == "C":
                letter = "B"

    # Override 2: (not GA4 or not GTM) AND seo<=84 => minimum B
    if not (lead.tracking.ga4 and lead.tracking.gtm):
        if seo is not None and seo <= 84:
            if letter == "C":
                letter = "B"

    lead.score_points = min(total, 100)
    lead.score_letter = letter
    lead.score_reasons = all_reasons[:3]

    logger.debug(
        "Scored %s: %d pts (%s) reasons=%s",
        lead.domain, lead.score_points, lead.score_letter, lead.score_reasons,
    )


def print_summary(leads: list[LeadAudit]) -> None:
    """Print summary of scored leads to console."""
    counts = {"A": 0, "B": 0, "C": 0}
    roi_counts = {"high": 0, "medium": 0, "low": 0}

    for lead in leads:
        letter = lead.score_letter or "C"
        counts[letter] = counts.get(letter, 0) + 1
        roi = lead.roi_priority or "low"
        roi_counts[roi] = roi_counts.get(roi, 0) + 1

    print(f"\nA: {counts['A']} | B: {counts['B']} | C: {counts['C']}")
    print(f"ROI: high: {roi_counts['high']} | medium: {roi_counts['medium']} | low: {roi_counts['low']}")

    # Top 5 by score_points
    sorted_leads = sorted(leads, key=lambda x: x.score_points, reverse=True)[:5]
    print("Top leads:")
    for i, lead in enumerate(sorted_leads, 1):
        reasons_str = ", ".join(lead.score_reasons) if lead.score_reasons else "-"
        roi = lead.roi_priority or "low"
        print(f"  {i}) {lead.domain} - {lead.score_points} ({lead.score_letter}) ROI: {roi} - {reasons_str}")
