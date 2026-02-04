"""Pipeline runner with concurrent HTML and PSI stages."""
from __future__ import annotations

import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from src.audits.html_inspector import run_html_inspection
from src.audits.psi import (
    run_psi_audit,
    validate_api_key,
    PSIValidationError,
    get_psi_stats,
    reset_psi_stats,
)
from src.insights.business import generate_business_insights
from src.models.lead_audit import LeadAudit, HTMLMeta, TrackingInfo, TechInfo, BusinessSignals
from src.models.lead_audit import PSIScores, CWV, OpportunityItem
from src.scoring.rubric import compute_score
from src.utils.cache import (
    CacheManager,
    HTMLCacheEntry,
    PSICacheEntry,
    load_existing_leads,
    create_html_cache_data,
    create_psi_cache_data,
    DEFAULT_TTL_SECONDS,
)
from src.utils.rate_limit import get_psi_limiter, TokenBucket
from src.utils.url import normalize_url

logger = logging.getLogger("harvester")


@dataclass
class StageResult:
    """Result from a pipeline stage."""
    url: str
    success: bool
    cached: bool
    elapsed_ms: int
    error: str | None = None


@dataclass
class PipelineStats:
    """Pipeline execution statistics."""
    total_urls: int = 0
    skipped_resume: int = 0
    html_cache_hits: int = 0
    psi_cache_hits: int = 0
    html_cache_expired: int = 0
    psi_cache_expired: int = 0
    html_errors: int = 0
    psi_errors: int = 0
    html_stage_ms: int = 0
    psi_stage_ms: int = 0
    scoring_ms: int = 0
    total_ms: int = 0


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


def _create_html_cache_data(lead: LeadAudit) -> dict:
    """Create a cache entry data dict from lead HTML inspection results."""
    return create_html_cache_data(
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


def _create_psi_cache_data(lead: LeadAudit) -> dict:
    """Create a PSI cache entry data dict from lead."""
    return create_psi_cache_data(
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


def _process_html_single(
    lead: LeadAudit,
    cache: CacheManager,
    timeout: float,
    cache_enabled: bool,
) -> StageResult:
    """Process HTML inspection for a single lead (thread-safe).

    Returns StageResult with success/cached status.
    """
    start = time.monotonic()
    url = lead.url

    # Check cache first (uses normalized URL internally)
    html_cached = cache.get_html(url)
    if html_cached:
        _apply_html_cache(lead, html_cached)
        elapsed_ms = round((time.monotonic() - start) * 1000)
        logger.debug("html_done (cached): %s [%dms]", url, elapsed_ms)
        return StageResult(url=url, success=True, cached=True, elapsed_ms=elapsed_ms)

    # Run HTML inspection
    try:
        run_html_inspection(lead, timeout=timeout)
        success = lead.html_meta.http_status is not None
        is_partial = lead.status == "partial"

        if cache_enabled and (success or is_partial):
            cache.set_html(
                url=url,
                entry_data=_create_html_cache_data(lead),
                final_url=lead.html_meta.final_url,
                is_partial=is_partial,
            )

        elapsed_ms = round((time.monotonic() - start) * 1000)
        logger.debug("html_done: %s [%dms]", url, elapsed_ms)
        return StageResult(url=url, success=success, cached=False, elapsed_ms=elapsed_ms)
    except Exception as exc:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        error_msg = str(exc)
        logger.error("html_error: %s - %s", url, error_msg)
        lead.errors.append(f"HTML error: {error_msg}")
        if lead.status != "complete":
            lead.status = "partial"
        return StageResult(
            url=url, success=False, cached=False, elapsed_ms=elapsed_ms, error=error_msg
        )


def _process_psi_single(
    lead: LeadAudit,
    cache: CacheManager,
    api_key: str,
    timeout: float,
    max_retries: int,
    cache_enabled: bool,
    rate_limiter: TokenBucket | None,
) -> StageResult:
    """Process PSI audit for a single lead (thread-safe with rate limiting).

    Returns StageResult with success/cached status.
    """
    start = time.monotonic()
    url = lead.url
    strategy = lead.strategy
    psi_stats = get_psi_stats()

    # Check cache first (uses normalized URL internally)
    # Pass final_url from HTML stage if available for better normalization
    final_url = lead.html_meta.final_url if lead.html_meta else None
    psi_cached = cache.get_psi(url, strategy, final_url=final_url)
    if psi_cached:
        _apply_psi_cache(lead, psi_cached)
        psi_stats.record_cache_hit()
        elapsed_ms = round((time.monotonic() - start) * 1000)
        logger.debug("psi_done (cached): %s [%dms]", url, elapsed_ms)
        return StageResult(url=url, success=True, cached=True, elapsed_ms=elapsed_ms)

    # Acquire rate limit token before making PSI request
    if rate_limiter:
        wait_start = time.monotonic()
        rate_limiter.acquire()
        wait_time = time.monotonic() - wait_start
        if wait_time > 0.1:  # Only count significant waits
            psi_stats.record_rate_wait()

    # Run PSI audit
    try:
        run_psi_audit(lead, api_key=api_key, timeout=timeout, max_retries=max_retries)
        success = lead.scores.performance is not None
        is_partial = lead.status == "partial"

        if cache_enabled and (success or is_partial):
            cache.set_psi(
                url=url,
                strategy=strategy,
                entry_data=_create_psi_cache_data(lead),
                final_url=final_url,
                is_partial=is_partial,
            )

        elapsed_ms = round((time.monotonic() - start) * 1000)
        logger.debug("psi_done: %s [%dms]", url, elapsed_ms)
        return StageResult(url=url, success=success, cached=False, elapsed_ms=elapsed_ms)
    except Exception as exc:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        error_msg = str(exc)
        logger.error("psi_error: %s - %s", url, error_msg)
        lead.errors.append(f"PSI error: {error_msg}")
        lead.status = "partial"
        return StageResult(
            url=url, success=False, cached=False, elapsed_ms=elapsed_ms, error=error_msg
        )


def _run_concurrent_stage(
    items: list,
    worker_fn: Callable,
    concurrency: int,
    stage_name: str,
) -> tuple[list[StageResult], int]:
    """Run a stage with ThreadPoolExecutor.

    Args:
        items: List of (lead, kwargs) tuples to process.
        worker_fn: Function to call with (lead, **kwargs).
        concurrency: Number of concurrent workers.
        stage_name: Name for logging (e.g., "HTML", "PSI").

    Returns:
        Tuple of (results list, total elapsed ms).
    """
    if not items:
        return [], 0

    results: list[StageResult] = []
    stage_start = time.monotonic()

    if concurrency <= 1:
        # Sequential execution
        for lead, kwargs in items:
            result = worker_fn(lead, **kwargs)
            results.append(result)
    else:
        # Concurrent execution with ThreadPoolExecutor
        logger.info(
            "%s stage: starting with %d workers for %d URLs",
            stage_name, concurrency, len(items)
        )
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_url: dict[Future, str] = {}
            for lead, kwargs in items:
                future = executor.submit(worker_fn, lead, **kwargs)
                future_to_url[future] = lead.url

            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as exc:
                    logger.error("%s stage exception for %s: %s", stage_name, url, exc)
                    results.append(StageResult(
                        url=url, success=False, cached=False, elapsed_ms=0, error=str(exc)
                    ))

    stage_elapsed = round((time.monotonic() - stage_start) * 1000)
    return results, stage_elapsed


def validate_psi_api_key(api_key: str, timeout: float = 15.0) -> None:
    """Validate PSI API key before processing.

    Args:
        api_key: Google API key to validate.
        timeout: Request timeout in seconds.

    Raises:
        SystemExit: If API key is invalid.
    """
    if not api_key:
        logger.info("No PSI API key configured (running without key)")
        return

    try:
        validate_api_key(api_key, timeout=timeout)
    except PSIValidationError as exc:
        logger.error("PSI API key validation failed: %s", exc)
        print(f"\nERROR: {exc}\n", file=sys.stderr)
        print("Please check your PSI API key in config/config.yaml or set PSI_API_KEY environment variable.", file=sys.stderr)
        raise SystemExit(1)


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
    skip_psi_validation: bool = False,
) -> list[LeadAudit]:
    """Run the audit pipeline with concurrent HTML and PSI stages.

    Args:
        urls: List of URLs to audit.
        strategy: PSI strategy ("mobile" or "desktop").
        concurrency: Number of concurrent workers (default 4).
        config_path: Path to config YAML.
        output_dir: Output directory for results.
        use_cache: Whether to use caching.
        cache_dir: Override cache directory.
        resume: Skip URLs already in leads.json.
        force: Ignore cache and resume, re-run all.
        skip_psi_validation: Skip PSI API key validation.

    Returns:
        List of LeadAudit results.
    """
    pipeline_start = time.monotonic()
    stats = PipelineStats(total_urls=len(urls))

    # Reset PSI stats for this run
    reset_psi_stats()
    psi_stats = get_psi_stats()

    cfg = _load_config(config_path)
    api_key = cfg.get("psi_api_key", "")
    timeout = cfg.get("timeout_seconds", 30)
    max_retries = cfg.get("max_retries", 3)
    rate_limit = cfg.get("rate_limit_per_min", 60)

    # Cache settings
    cache_ttl = cfg.get("cache_ttl_seconds", DEFAULT_TTL_SECONDS)
    cache_partial = cfg.get("cache_partial", True)

    # Validate PSI API key on startup (unless skipped)
    if not skip_psi_validation:
        validate_psi_api_key(api_key, timeout=timeout)

    # Logging: pipeline configuration
    logger.info(
        "Pipeline starting: %d URLs, concurrency=%d, strategy=%s, rate_limit=%d/min",
        len(urls), concurrency, strategy, rate_limit
    )

    if api_key:
        logger.info("PSI API key: configured")
    else:
        logger.info("PSI API key: not configured (may be rate-limited)")

    # Cache setup with TTL and partial settings
    cache_enabled = use_cache and cfg.get("cache_enabled", True) and not force
    actual_cache_dir = cache_dir or cfg.get("cache_dir", f"{output_dir}/cache")
    cache = CacheManager(
        actual_cache_dir,
        enabled=cache_enabled,
        ttl_seconds=cache_ttl,
        cache_partial=cache_partial,
    )

    if cache_enabled:
        logger.info("Cache enabled: ttl=%ds, partial=%s", cache_ttl, cache_partial)

    # Rate limiter for PSI requests
    rate_limiter = get_psi_limiter(rate_limit) if rate_limit > 0 else None

    # Resume: load existing leads (uses normalized URLs for lookup)
    existing_leads: dict[str, dict] = {}
    if resume and not force:
        leads_path = Path(output_dir) / "leads.json"
        existing_leads = load_existing_leads(leads_path)
        if existing_leads:
            logger.info("Resume mode: found %d existing leads", len(existing_leads))

    # Phase 0: Initialize leads and handle resume
    leads: list[LeadAudit] = []
    leads_to_process: list[LeadAudit] = []

    for url in urls:
        # Check both original and normalized URL for resume
        normalized = normalize_url(url)
        if resume and (url in existing_leads or normalized in existing_leads) and not force:
            logger.debug("Skipping %s (already in leads.json)", url)
            lead_data = existing_leads.get(url) or existing_leads.get(normalized)
            lead = LeadAudit.model_validate(lead_data)
            leads.append(lead)
            stats.skipped_resume += 1
        else:
            lead = LeadAudit.from_url(url, strategy)
            leads.append(lead)
            leads_to_process.append(lead)

    if stats.skipped_resume > 0:
        logger.info("Resume: skipped %d URLs already in leads.json", stats.skipped_resume)

    if not leads_to_process:
        logger.info("No URLs to process (all skipped or empty input)")
        return leads

    # Build URL -> lead index map for result ordering
    url_to_lead = {lead.url: lead for lead in leads_to_process}

    # -------------------------------------------------------------------------
    # Stage A: HTML Inspection (concurrent)
    # -------------------------------------------------------------------------
    html_items = [
        (lead, {
            "cache": cache,
            "timeout": timeout,
            "cache_enabled": cache_enabled,
        })
        for lead in leads_to_process
    ]

    html_results, html_elapsed = _run_concurrent_stage(
        html_items,
        _process_html_single,
        concurrency,
        "HTML",
    )

    stats.html_stage_ms = html_elapsed
    for r in html_results:
        if r.cached:
            stats.html_cache_hits += 1
        elif not r.success:
            stats.html_errors += 1

    logger.info(
        "HTML stage complete: %d URLs in %dms (cache_hits=%d, errors=%d)",
        len(html_results), html_elapsed, stats.html_cache_hits, stats.html_errors
    )

    # -------------------------------------------------------------------------
    # Stage B: PSI Audit (concurrent with rate limiting)
    # -------------------------------------------------------------------------
    psi_items = [
        (lead, {
            "cache": cache,
            "api_key": api_key,
            "timeout": timeout,
            "max_retries": max_retries,
            "cache_enabled": cache_enabled,
            "rate_limiter": rate_limiter,
        })
        for lead in leads_to_process
    ]

    # Use same concurrency but rate limiter will control actual throughput
    psi_results, psi_elapsed = _run_concurrent_stage(
        psi_items,
        _process_psi_single,
        concurrency,
        "PSI",
    )

    stats.psi_stage_ms = psi_elapsed
    for r in psi_results:
        if r.cached:
            stats.psi_cache_hits += 1
        elif not r.success:
            stats.psi_errors += 1

    logger.info(
        "PSI stage complete: %d URLs in %dms (cache_hits=%d, errors=%d)",
        len(psi_results), psi_elapsed, stats.psi_cache_hits, stats.psi_errors
    )

    # -------------------------------------------------------------------------
    # Stage C: Scoring and Business Insights (sequential, fast)
    # -------------------------------------------------------------------------
    scoring_start = time.monotonic()
    for lead in leads_to_process:
        compute_score(lead)
        generate_business_insights(lead)
        logger.debug("scored: %s -> %s (%d pts)", lead.url, lead.score_letter, lead.score_points)

    stats.scoring_ms = round((time.monotonic() - scoring_start) * 1000)
    logger.info("Scoring stage complete: %d leads in %dms", len(leads_to_process), stats.scoring_ms)

    # -------------------------------------------------------------------------
    # Pipeline complete
    # -------------------------------------------------------------------------
    stats.total_ms = round((time.monotonic() - pipeline_start) * 1000)

    logger.info(
        "Pipeline complete: %d leads total (%d processed, %d skipped) in %dms",
        len(leads), len(leads_to_process), stats.skipped_resume, stats.total_ms
    )
    logger.info(
        "Stage timings: HTML=%dms, PSI=%dms, Scoring=%dms",
        stats.html_stage_ms, stats.psi_stage_ms, stats.scoring_ms
    )
    logger.info(
        "Cache performance: HTML hits=%d, PSI hits=%d",
        stats.html_cache_hits, stats.psi_cache_hits
    )

    # Log PSI API usage stats
    logger.info(psi_stats.summary())

    return leads
