import json
import logging
import time
from pathlib import Path

import yaml

from src.audits.html_inspector import run_html_inspection
from src.audits.psi import run_psi_audit
from src.insights.business import generate_business_insights
from src.models.lead_audit import LeadAudit, HTMLMeta, TrackingInfo, TechInfo, BusinessSignals
from src.models.lead_audit import PSIScores, CWV, OpportunityItem
from src.scoring.rubric import compute_score
from src.utils.cache import CacheManager, HTMLCacheEntry, PSICacheEntry, load_existing_leads

logger = logging.getLogger("harvester")


def _load_config(config_path: str) -> dict:
    try:
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("Config file not found: %s, using defaults", config_path)
        return {}


def _apply_html_cache(lead: LeadAudit, entry: HTMLCacheEntry) -> None:
    """Apply cached HTML results to a lead."""
    lead.html_meta = HTMLMeta(
        http_status=entry.http_status,
        final_url=entry.final_url,
        response_time_ms=entry.response_time_ms,
        third_party_script_count=entry.third_party_script_count,
    )
    lead.tracking = TrackingInfo(**entry.tracking)
    lead.tracking_evidence = entry.tracking_evidence
    lead.tech = TechInfo(
        cms=entry.tech_cms,
        framework=entry.tech_framework,
        ecommerce=entry.tech_ecommerce,
        hosting_hints=entry.tech_hosting_hints,
    )
    lead.tech_confidence = entry.tech_confidence
    lead.business_signals = BusinessSignals(**entry.business_signals)


def _create_html_cache_entry(lead: LeadAudit) -> HTMLCacheEntry:
    """Create a cache entry from lead HTML inspection results."""
    return HTMLCacheEntry(
        url=lead.url,
        http_status=lead.html_meta.http_status,
        final_url=lead.html_meta.final_url,
        response_time_ms=lead.html_meta.response_time_ms,
        third_party_script_count=lead.html_meta.third_party_script_count,
        tracking=lead.tracking.model_dump(),
        tracking_evidence=lead.tracking_evidence,
        tech_cms=lead.tech.cms,
        tech_framework=lead.tech.framework,
        tech_ecommerce=lead.tech.ecommerce,
        tech_hosting_hints=lead.tech.hosting_hints,
        tech_confidence=lead.tech_confidence,
        business_signals=lead.business_signals.model_dump(),
    )


def _apply_psi_cache(lead: LeadAudit, entry: PSICacheEntry) -> None:
    """Apply cached PSI results to a lead."""
    lead.scores = PSIScores(
        performance=entry.performance,
        seo=entry.seo,
        accessibility=entry.accessibility,
        best_practices=entry.best_practices,
    )
    lead.cwv = CWV(
        lcp_ms=entry.lcp_ms,
        inp_ms=entry.inp_ms,
        cls=entry.cls,
        ttfb_ms=entry.ttfb_ms,
        fcp_ms=entry.fcp_ms,
    )
    lead.psi_opportunities = [OpportunityItem(**o) for o in entry.opportunities]
    lead.psi_diagnostics = [OpportunityItem(**d) for d in entry.diagnostics]
    if entry.performance is not None:
        lead.status = "complete"


def _create_psi_cache_entry(lead: LeadAudit) -> PSICacheEntry:
    """Create a PSI cache entry from lead."""
    return PSICacheEntry(
        url=lead.url,
        strategy=lead.strategy,
        performance=lead.scores.performance,
        seo=lead.scores.seo,
        accessibility=lead.scores.accessibility,
        best_practices=lead.scores.best_practices,
        lcp_ms=lead.cwv.lcp_ms,
        inp_ms=lead.cwv.inp_ms,
        cls=lead.cwv.cls,
        ttfb_ms=lead.cwv.ttfb_ms,
        fcp_ms=lead.cwv.fcp_ms,
        opportunities=[o.model_dump() for o in lead.psi_opportunities],
        diagnostics=[d.model_dump() for d in lead.psi_diagnostics],
    )


def run_pipeline(
    urls: list[str],
    strategy: str,
    concurrency: int = 4,
    config_path: str = "config/config.yaml",
    output_dir: str = "out",
    use_cache: bool = True,
    cache_dir: str | None = None,
    resume: bool = False,
    force: bool = False,
) -> list[LeadAudit]:
    cfg = _load_config(config_path)
    api_key = cfg.get("psi_api_key", "")
    timeout = cfg.get("timeout_seconds", 30)
    max_retries = cfg.get("max_retries", 3)
    rate_limit = cfg.get("rate_limit_per_min", 60)
    min_interval = 60.0 / rate_limit

    # Cache setup
    cache_enabled = use_cache and cfg.get("cache_enabled", True) and not force
    actual_cache_dir = cache_dir or cfg.get("cache_dir", f"{output_dir}/cache")
    cache = CacheManager(actual_cache_dir, enabled=cache_enabled)

    # Resume: load existing leads
    existing_leads: dict[str, dict] = {}
    if resume and not force:
        leads_path = Path(output_dir) / "leads.json"
        existing_leads = load_existing_leads(leads_path)
        if existing_leads:
            logger.info("Resume mode: found %d existing leads", len(existing_leads))

    leads: list[LeadAudit] = []
    cache_hits = {"html": 0, "psi": 0}
    skipped = 0

    for i, url in enumerate(urls):
        # Resume: skip if already processed
        if resume and url in existing_leads and not force:
            logger.info("Skipping %s (already in leads.json)", url)
            # Reconstruct lead from existing data
            lead_data = existing_leads[url]
            lead = LeadAudit.model_validate(lead_data)
            leads.append(lead)
            skipped += 1
            continue

        logger.info("Processing %s (%d/%d)", url, i + 1, len(urls))
        start = time.monotonic()

        lead = LeadAudit.from_url(url, strategy)

        # HTML inspection (check cache first)
        html_cached = cache.get_html(url)
        if html_cached:
            _apply_html_cache(lead, html_cached)
            cache_hits["html"] += 1
            logger.info("Cache hit (HTML): %s", url)
        else:
            run_html_inspection(lead, timeout=timeout)
            if cache_enabled and lead.html_meta.http_status:
                cache.set_html(_create_html_cache_entry(lead))

        # PSI audit (check cache first)
        psi_cached = cache.get_psi(url, strategy)
        if psi_cached:
            _apply_psi_cache(lead, psi_cached)
            cache_hits["psi"] += 1
            logger.info("Cache hit (PSI): %s", url)
        else:
            run_psi_audit(lead, api_key=api_key, timeout=timeout, max_retries=max_retries)
            if cache_enabled and lead.scores.performance is not None:
                cache.set_psi(_create_psi_cache_entry(lead))

        # Scoring
        compute_score(lead)

        # Business insights (pains + outreach + ROI)
        generate_business_insights(lead)

        elapsed = time.monotonic() - start
        logger.debug("Finished %s in %.3fs", url, elapsed)
        leads.append(lead)

        # Rate limiting (only if we made actual requests)
        if not (html_cached and psi_cached):
            if elapsed < min_interval and i < len(urls) - 1:
                pause = min_interval - elapsed
                logger.debug("Rate limit pause: %.2fs", pause)
                time.sleep(pause)

    logger.info(
        "Pipeline complete: %d leads (cache hits: HTML=%d, PSI=%d, skipped=%d)",
        len(leads), cache_hits["html"], cache_hits["psi"], skipped,
    )
    return leads
