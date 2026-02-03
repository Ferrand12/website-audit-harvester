"""Cache utilities for storing and retrieving audit results."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("harvester")


def _cache_key(url: str, suffix: str) -> str:
    """Generate a cache key from URL and suffix."""
    return hashlib.sha1(f"{url}:{suffix}".encode()).hexdigest()


class HTMLCacheEntry(BaseModel):
    """Cached HTML inspection results."""
    url: str
    http_status: int | None
    final_url: str | None
    response_time_ms: int | None
    third_party_script_count: int
    tracking: dict[str, bool]
    tracking_evidence: dict[str, list[str]]
    tech_cms: str | None
    tech_framework: str | None
    tech_ecommerce: str | None
    tech_hosting_hints: list[str]
    tech_confidence: dict[str, float]
    business_signals: dict[str, Any]


class PSICacheEntry(BaseModel):
    """Cached PSI results."""
    url: str
    strategy: str
    performance: int | None
    seo: int | None
    accessibility: int | None
    best_practices: int | None
    lcp_ms: int | None
    inp_ms: int | None
    cls: float | None
    ttfb_ms: int | None
    fcp_ms: int | None
    opportunities: list[dict[str, str]]
    diagnostics: list[dict[str, str]]


class CacheManager:
    """Manages reading and writing cache entries."""

    def __init__(self, cache_dir: str | Path, enabled: bool = True):
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled
        if enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _html_path(self, url: str) -> Path:
        return self.cache_dir / f"{_cache_key(url, 'html')}.json"

    def _psi_path(self, url: str, strategy: str) -> Path:
        return self.cache_dir / f"{_cache_key(url + strategy, 'psi')}.json"

    def get_html(self, url: str) -> HTMLCacheEntry | None:
        """Get cached HTML results, or None if not cached."""
        if not self.enabled:
            return None
        path = self._html_path(url)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            entry = HTMLCacheEntry.model_validate(data)
            logger.debug("Cache hit (HTML): %s", url)
            return entry
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("Invalid cache entry for %s: %s", url, e)
            return None

    def set_html(self, entry: HTMLCacheEntry) -> None:
        """Store HTML results in cache."""
        if not self.enabled:
            return
        path = self._html_path(entry.url)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry.model_dump(), f)
        logger.debug("Cached HTML: %s", entry.url)

    def get_psi(self, url: str, strategy: str) -> PSICacheEntry | None:
        """Get cached PSI results, or None if not cached."""
        if not self.enabled:
            return None
        path = self._psi_path(url, strategy)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            entry = PSICacheEntry.model_validate(data)
            logger.debug("Cache hit (PSI): %s", url)
            return entry
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("Invalid PSI cache entry for %s: %s", url, e)
            return None

    def set_psi(self, entry: PSICacheEntry) -> None:
        """Store PSI results in cache."""
        if not self.enabled:
            return
        path = self._psi_path(entry.url, entry.strategy)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry.model_dump(), f)
        logger.debug("Cached PSI: %s", entry.url)

    def clear(self) -> int:
        """Clear all cache entries. Returns count of deleted files."""
        if not self.cache_dir.exists():
            return 0
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
            count += 1
        logger.info("Cleared %d cache entries", count)
        return count


def load_existing_leads(leads_path: Path) -> dict[str, dict]:
    """Load existing leads.json and return dict keyed by URL for resume."""
    if not leads_path.exists():
        return {}
    try:
        with open(leads_path, "r", encoding="utf-8") as f:
            leads = json.load(f)
        return {lead["url"]: lead for lead in leads}
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Could not load existing leads: %s", e)
        return {}
