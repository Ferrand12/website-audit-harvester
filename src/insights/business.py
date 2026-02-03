from __future__ import annotations

import logging

from src.models.lead_audit import LeadAudit, OutreachMessage, PainItem

logger = logging.getLogger("harvester")

# ---------------------------------------------------------------------------
# Pain detection rules
# ---------------------------------------------------------------------------

def _detect_pains(lead: LeadAudit) -> list[PainItem]:
    """Deterministic pain detection from audit signals."""
    pains: list[PainItem] = []
    scores = lead.scores
    cwv = lead.cwv

    # slow_mobile: performance <= 69 OR LCP > 4000ms
    perf = scores.performance
    lcp = cwv.lcp_ms
    if (perf is not None and perf <= 69) or (lcp is not None and lcp > 4000):
        severity = "high" if (perf is not None and perf <= 49) or (lcp is not None and lcp > 6000) else "medium"
        proof_parts = []
        if perf is not None:
            proof_parts.append(f"Performance score: {perf}/100")
        if lcp is not None:
            proof_parts.append(f"LCP: {lcp}ms")
        pains.append(PainItem(
            pain_id="slow_mobile",
            severity=severity,
            business_impact="Slow pages lose visitors and reduce conversions. Google also ranks faster sites higher.",
            proof="; ".join(proof_parts) if proof_parts else "Performance data indicates slow load times",
        ))

    # seo_weak: seo <= 84
    seo = scores.seo
    if seo is not None and seo <= 84:
        severity = "high" if seo <= 64 else "medium"
        pains.append(PainItem(
            pain_id="seo_weak",
            severity=severity,
            business_impact="SEO issues reduce organic visibility, meaning fewer potential customers find your site.",
            proof=f"SEO score: {seo}/100",
        ))

    # tracking_gap: missing GA4 or GTM
    if not (lead.tracking.ga4 and lead.tracking.gtm):
        missing = []
        if not lead.tracking.ga4:
            missing.append("GA4")
        if not lead.tracking.gtm:
            missing.append("GTM")
        pains.append(PainItem(
            pain_id="tracking_gap",
            severity="high",
            business_impact="Without proper analytics, you cannot measure what works or optimize marketing spend.",
            proof=f"Missing: {', '.join(missing)}",
        ))

    # accessibility_risk: accessibility <= 79
    a11y = scores.accessibility
    if a11y is not None and a11y <= 79:
        severity = "high" if a11y <= 59 else "medium"
        pains.append(PainItem(
            pain_id="accessibility_risk",
            severity=severity,
            business_impact="Accessibility gaps exclude users and increase legal exposure in regulated markets.",
            proof=f"Accessibility score: {a11y}/100",
        ))

    # best_practices_risk: best_practices <= 79
    bp = scores.best_practices
    if bp is not None and bp <= 79:
        severity = "high" if bp <= 59 else "medium"
        pains.append(PainItem(
            pain_id="best_practices_risk",
            severity=severity,
            business_impact="Technical debt and security gaps can harm user trust and site stability.",
            proof=f"Best Practices score: {bp}/100",
        ))

    return pains


# ---------------------------------------------------------------------------
# ROI Priority calculation
# ---------------------------------------------------------------------------

def _compute_roi_priority(lead: LeadAudit) -> tuple[str, list[str]]:
    """Compute ROI priority based on score_letter and business_signals."""
    reasons: list[str] = []
    signals = lead.business_signals
    letter = lead.score_letter or "C"

    # Check for high-value business signals
    has_services = signals.has_services_page
    has_pricing = signals.has_pricing_page
    has_ecommerce = signals.has_ecommerce
    has_locations = signals.has_multiple_locations_hint

    high_value_signals = []
    if has_services:
        high_value_signals.append("services")
    if has_pricing:
        high_value_signals.append("pricing")
    if has_ecommerce:
        high_value_signals.append("ecommerce")
    if has_locations:
        high_value_signals.append("multi-location")

    if letter in ("A", "B") and high_value_signals:
        reasons.extend(high_value_signals)
        return "high", reasons
    elif letter in ("A", "B"):
        reasons.append(f"grade {letter} but no biz signals")
        return "medium", reasons
    elif letter == "C" and (has_pricing or has_ecommerce):
        if has_pricing:
            reasons.append("has pricing")
        if has_ecommerce:
            reasons.append("has ecommerce")
        return "medium", reasons
    else:
        reasons.append(f"grade {letter}")
        return "low", reasons


# ---------------------------------------------------------------------------
# Outreach message generation (EN) - Enhanced with evidence
# ---------------------------------------------------------------------------

def _get_concrete_evidence(lead: LeadAudit) -> str:
    """Get one concrete piece of evidence for personalization."""
    # Priority: tracking evidence > script count > CMS/framework
    te = lead.tracking_evidence

    # Check for GTM without GA4 (measurement gap)
    if te.get("gtm") and not te.get("ga4"):
        gtm_id = te["gtm"][0] if te["gtm"] else "GTM"
        return f"I noticed {gtm_id} is installed but GA4 is missing"

    # Check for many third-party scripts
    script_count = lead.html_meta.third_party_script_count
    if script_count >= 15:
        return f"The page loads {script_count} third-party scripts, which impacts speed and can affect conversions"

    # Check for specific tracking
    if te.get("gtm"):
        return f"I see you're using {te['gtm'][0]}"
    if te.get("ga4"):
        return f"I noticed your GA4 setup ({te['ga4'][0]})"

    # Fall back to CMS/tech
    if lead.tech.cms == "WordPress":
        if lead.tech.ecommerce == "WooCommerce":
            return "Your WordPress/WooCommerce site"
        return "Your WordPress site"
    if lead.tech.cms:
        return f"Your {lead.tech.cms} site"
    if lead.tech.framework:
        return f"Your {lead.tech.framework} application"

    return "Your website"


def _get_business_impact(lead: LeadAudit, pains: list[PainItem]) -> str:
    """Get business impact statement based on detected issues."""
    perf = lead.scores.performance
    script_count = lead.html_meta.third_party_script_count

    # GTM present but GA4 missing: measurement gap
    if lead.tracking.gtm and not lead.tracking.ga4:
        return "Without GA4, you're likely missing key conversion data and can't accurately measure campaign ROI."

    # Many scripts: tag hygiene issue
    if script_count >= 15:
        return "This tag bloat can slow page loads by 2-3 seconds, potentially costing you 7% in conversions per second of delay."

    # WordPress/WooCommerce with low perf: speed sprint opportunity
    if (lead.tech.cms == "WordPress" or lead.tech.ecommerce == "WooCommerce") and perf is not None and perf <= 69:
        return "Optimizing WordPress performance typically yields 20-40% faster load times, directly improving user experience and sales."

    # General performance issue
    if perf is not None and perf <= 69:
        return "Slow mobile performance often leads to lost visitors and lower search rankings, impacting both traffic and revenue."

    # SEO issue
    seo = lead.scores.seo
    if seo is not None and seo <= 84:
        return "SEO gaps mean potential customers searching for your services may find competitors instead."

    # Tracking gap
    if not lead.tracking.ga4 or not lead.tracking.gtm:
        return "Incomplete analytics setup means you can't accurately measure which marketing channels drive real results."

    # Default
    return "These technical gaps can affect how visitors experience your site and whether they convert."


def _generate_outreach(lead: LeadAudit, pains: list[PainItem]) -> OutreachMessage:
    """Generate a personalized outreach message in English (90-140 words)."""
    domain = lead.domain

    # Build subject
    perf = lead.scores.performance
    if perf is not None and perf <= 49:
        subject = f"Speed opportunity for {domain}"
    elif lead.tracking.gtm and not lead.tracking.ga4:
        subject = f"Measurement gap on {domain}"
    elif lead.html_meta.third_party_script_count >= 15:
        subject = f"Tag hygiene check for {domain}"
    else:
        subject = f"Quick wins for {domain}"

    # Get personalization elements
    evidence = _get_concrete_evidence(lead)
    impact = _get_business_impact(lead, pains)

    # Build body
    has_data = lead.scores.performance is not None

    if has_data:
        intro = f"Hi there,\n\nI recently reviewed {domain} on mobile."
    else:
        intro = f"Hi there,\n\nI took a quick look at {domain}."

    # Evidence sentence
    evidence_line = f"\n\n{evidence}."

    # Impact sentence
    impact_line = f" {impact}"

    # Build issue list (max 2 for brevity)
    issues: list[str] = []
    for p in pains[:2]:
        if p.pain_id == "slow_mobile" and perf is not None:
            issues.append(f"Mobile performance score of {perf}/100")
        elif p.pain_id == "tracking_gap":
            issues.append("Incomplete analytics tracking")
        elif p.pain_id == "seo_weak":
            issues.append("Some SEO optimization gaps")

    issue_text = ""
    if issues:
        issue_text = "\n\nKey findings:\n" + "\n".join(f"- {i}" for i in issues)

    # CTA with offer
    cta = (
        "\n\nWould you be open to a 15-minute call? I can share a 1-page audit summary "
        "with specific recommendations.\n\n"
        "Best,\n[Your Name]"
    )

    body = intro + evidence_line + impact_line + issue_text + cta

    return OutreachMessage(subject=subject, body=body)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_business_insights(lead: LeadAudit) -> None:
    """Populate pains, roi_priority, roi_reasons, and outreach_en on the lead."""
    pains = _detect_pains(lead)
    lead.pains = pains

    roi_priority, roi_reasons = _compute_roi_priority(lead)
    lead.roi_priority = roi_priority
    lead.roi_reasons = roi_reasons

    lead.outreach_en = _generate_outreach(lead, pains)

    logger.debug(
        "Business insights for %s: %d pains, ROI=%s, outreach subject=%r",
        lead.domain, len(pains), roi_priority, lead.outreach_en.subject,
    )
