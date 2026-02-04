"""Cache utilities for storing and retrieving audit results.

Features:
- URL normalization for consistent cache keys
- TTL-based expiration
- Schema versioning for cache invalidation
- Graceful handling of corrupted/poisoned cache files
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from src.utils.url import normalize_url

logger = logging.getLogger("harvester")

# Schema version - increment when cache entry structure changes
# This ensures old cache entries are invalidated after schema updates
CACHE_SCHEMA_VERSION = 2

# Default TTL: 7 days in seconds
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60  # 604800


def _cache_key(normalized_url: str, suffix: str) -> str:
    """Generate a cache key from normalized URL and suffix."""
    return hashlib.sha1(f"{normalized_url}:{suffix}".encode()).hexdigest()


def _utc_now() -> str:
    """Get current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _is_expired(created_utc: str | None, ttl_seconds: int) -> bool:
    """Check if a cache entry has expired based on TTL.

    Args:
        created_utc: ISO timestamp when entry was created.
        ttl_seconds: Time-to-live in seconds.

    Returns:
        True if entry has expired.
    """
    if ttl_seconds <= 0:
        return False  # TTL of 0 means never expire

    if not created_utc:
        return True  # Missing timestamp treated as expired

    try:
        # Parse ISO timestamp
        created = datetime.fromisoformat(created_utc.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_seconds = (now - created).total_seconds()
        return age_seconds > ttl_seconds
    except (ValueError, TypeError):
        # If timestamp is invalid, treat as expired
        return True


class CacheMetadata(BaseModel):
    """Metadata stored with each cache entry."""
    created_utc: str
    normalized_url: str
    schema_version: int
    ttl_seconds: int
    is_partial: bool = False  # True if result was incomplete


class HTMLCacheEntry(BaseModel):
    """Cached HTML inspection results."""
    # Metadata
    meta: CacheMetadata

    # Original request URL (before normalization)
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
    # Metadata
    meta: CacheMetadata

    # Original request URL (before normalization)
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
    """Manages reading and writing cache entries with TTL and versioning.

    Features:
    - URL normalization for consistent keys
    - TTL-based expiration
    - Schema version checking
    - Graceful handling of corrupted files
    """

    def __init__(
        self,
        cache_dir: str | Path,
        enabled: bool = True,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        cache_partial: bool = True,
    ):
        """Initialize cache manager.

        Args:
            cache_dir: Directory to store cache files.
            enabled: Whether caching is enabled.
            ttl_seconds: Time-to-live for cache entries (0 = never expire).
            cache_partial: Whether to cache partial/incomplete results.
        """
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds
        self.cache_partial = cache_partial

        if enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _html_path(self, normalized_url: str) -> Path:
        return self.cache_dir / f"{_cache_key(normalized_url, 'html')}.json"

    def _psi_path(self, normalized_url: str, strategy: str) -> Path:
        return self.cache_dir / f"{_cache_key(normalized_url + strategy, 'psi')}.json"

    def _validate_entry(
        self,
        data: dict,
        url: str,
        entry_type: str,
    ) -> tuple[bool, str]:
        """Validate cache entry metadata.

        Returns:
            Tuple of (is_valid, reason_if_invalid).
        """
        meta = data.get("meta")
        if not meta:
            return False, "missing metadata"

        # Check schema version
        schema_version = meta.get("schema_version", 0)
        if schema_version != CACHE_SCHEMA_VERSION:
            return False, f"schema version mismatch (cached={schema_version}, current={CACHE_SCHEMA_VERSION})"

        # Check TTL expiration
        created_utc = meta.get("created_utc", "")
        ttl = meta.get("ttl_seconds", self.ttl_seconds)
        if _is_expired(created_utc, ttl):
            age_info = ""
            try:
                created = datetime.fromisoformat(created_utc.replace("Z", "+00:00"))
                age_seconds = (datetime.now(timezone.utc) - created).total_seconds()
                age_info = f", age={int(age_seconds)}s, ttl={ttl}s"
            except Exception:
                pass
            return False, f"expired{age_info}"

        return True, ""

    def get_html(self, url: str, final_url: str | None = None) -> HTMLCacheEntry | None:
        """Get cached HTML results, or None if not cached/expired/invalid.

        Args:
            url: Original URL to look up.
            final_url: Final URL after redirects (used for normalization).

        Returns:
            Cached entry or None.
        """
        if not self.enabled:
            return None

        normalized = normalize_url(url, final_url=final_url)
        path = self._html_path(normalized)

        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validate metadata
            is_valid, reason = self._validate_entry(data, url, "HTML")
            if not is_valid:
                logger.info("Cache miss (HTML) %s: %s", url, reason)
                return None

            entry = HTMLCacheEntry.model_validate(data)
            logger.debug("Cache hit (HTML): %s", url)
            return entry

        except json.JSONDecodeError as e:
            logger.warning("Corrupted cache file (HTML) for %s: %s", url, e)
            self._safe_delete(path)
            return None
        except ValidationError as e:
            logger.warning("Invalid cache entry (HTML) for %s: %s", url, e)
            self._safe_delete(path)
            return None
        except Exception as e:
            logger.warning("Cache read error (HTML) for %s: %s", url, e)
            return None

    def set_html(
        self,
        url: str,
        entry_data: dict,
        *,
        final_url: str | None = None,
        is_partial: bool = False,
    ) -> None:
        """Store HTML results in cache.

        Args:
            url: Original URL.
            entry_data: Dictionary of cache entry fields (without meta).
            final_url: Final URL after redirects.
            is_partial: Whether this is a partial/incomplete result.
        """
        if not self.enabled:
            return

        if is_partial and not self.cache_partial:
            logger.debug("Skipping cache (partial results disabled): %s", url)
            return

        normalized = normalize_url(url, final_url=final_url)
        path = self._html_path(normalized)

        # Build full entry with metadata
        full_entry = {
            "meta": {
                "created_utc": _utc_now(),
                "normalized_url": normalized,
                "schema_version": CACHE_SCHEMA_VERSION,
                "ttl_seconds": self.ttl_seconds,
                "is_partial": is_partial,
            },
            **entry_data,
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(full_entry, f)
            logger.debug("Cached HTML: %s (normalized=%s)", url, normalized)
        except Exception as e:
            logger.warning("Cache write error (HTML) for %s: %s", url, e)

    def get_psi(
        self,
        url: str,
        strategy: str,
        final_url: str | None = None,
    ) -> PSICacheEntry | None:
        """Get cached PSI results, or None if not cached/expired/invalid.

        Args:
            url: Original URL to look up.
            strategy: PSI strategy (mobile/desktop).
            final_url: Final URL after redirects (used for normalization).

        Returns:
            Cached entry or None.
        """
        if not self.enabled:
            return None

        normalized = normalize_url(url, final_url=final_url)
        path = self._psi_path(normalized, strategy)

        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validate metadata
            is_valid, reason = self._validate_entry(data, url, "PSI")
            if not is_valid:
                logger.info("Cache miss (PSI) %s: %s", url, reason)
                return None

            entry = PSICacheEntry.model_validate(data)
            logger.debug("Cache hit (PSI): %s", url)
            return entry

        except json.JSONDecodeError as e:
            logger.warning("Corrupted cache file (PSI) for %s: %s", url, e)
            self._safe_delete(path)
            return None
        except ValidationError as e:
            logger.warning("Invalid cache entry (PSI) for %s: %s", url, e)
            self._safe_delete(path)
            return None
        except Exception as e:
            logger.warning("Cache read error (PSI) for %s: %s", url, e)
            return None

    def set_psi(
        self,
        url: str,
        strategy: str,
        entry_data: dict,
        *,
        final_url: str | None = None,
        is_partial: bool = False,
    ) -> None:
        """Store PSI results in cache.

        Args:
            url: Original URL.
            strategy: PSI strategy (mobile/desktop).
            entry_data: Dictionary of cache entry fields (without meta).
            final_url: Final URL after redirects.
            is_partial: Whether this is a partial/incomplete result.
        """
        if not self.enabled:
            return

        if is_partial and not self.cache_partial:
            logger.debug("Skipping cache (partial results disabled): %s", url)
            return

        normalized = normalize_url(url, final_url=final_url)
        path = self._psi_path(normalized, strategy)

        # Build full entry with metadata
        full_entry = {
            "meta": {
                "created_utc": _utc_now(),
                "normalized_url": normalized,
                "schema_version": CACHE_SCHEMA_VERSION,
                "ttl_seconds": self.ttl_seconds,
                "is_partial": is_partial,
            },
            **entry_data,
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(full_entry, f)
            logger.debug("Cached PSI: %s (normalized=%s)", url, normalized)
        except Exception as e:
            logger.warning("Cache write error (PSI) for %s: %s", url, e)

    def _safe_delete(self, path: Path) -> None:
        """Safely delete a cache file."""
        try:
            if path.exists():
                path.unlink()
                logger.debug("Deleted invalid cache file: %s", path)
        except Exception as e:
            logger.warning("Could not delete cache file %s: %s", path, e)

    def clear(self) -> int:
        """Clear all cache entries. Returns count of deleted files."""
        if not self.cache_dir.exists():
            return 0
        count = 0
        for f in self.cache_dir.glob("*.json"):
            try:
                f.unlink()
                count += 1
            except Exception as e:
                logger.warning("Could not delete cache file %s: %s", f, e)
        logger.info("Cleared %d cache entries", count)
        return count

    def get_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats.
        """
        if not self.cache_dir.exists():
            return {"total_files": 0, "total_bytes": 0}

        files = list(self.cache_dir.glob("*.json"))
        total_bytes = sum(f.stat().st_size for f in files)

        return {
            "total_files": len(files),
            "total_bytes": total_bytes,
            "cache_dir": str(self.cache_dir),
            "ttl_seconds": self.ttl_seconds,
            "schema_version": CACHE_SCHEMA_VERSION,
        }


def load_existing_leads(leads_path: Path) -> dict[str, dict]:
    """Load existing leads.json and return dict keyed by URL for resume.

    Note: URLs are normalized for consistent lookup.
    """
    if not leads_path.exists():
        return {}
    try:
        with open(leads_path, "r", encoding="utf-8") as f:
            leads = json.load(f)
        # Key by both original and normalized URL for flexibility
        result = {}
        for lead in leads:
            url = lead.get("url", "")
            result[url] = lead
            # Also add normalized version
            normalized = normalize_url(url)
            if normalized != url:
                result[normalized] = lead
        return result
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Could not load existing leads: %s", e)
        return {}


# Legacy compatibility aliases for entry creation
# These help with the transition from the old API

def create_html_cache_data(
    url: str,
    http_status: int | None,
    final_url: str | None,
    response_time_ms: int | None,
    third_party_script_count: int,
    tracking: dict[str, bool],
    tracking_evidence: dict[str, list[str]],
    tech_cms: str | None,
    tech_framework: str | None,
    tech_ecommerce: str | None,
    tech_hosting_hints: list[str],
    tech_confidence: dict[str, float],
    business_signals: dict[str, Any],
) -> dict:
    """Create HTML cache entry data dictionary."""
    return {
        "url": url,
        "http_status": http_status,
        "final_url": final_url,
        "response_time_ms": response_time_ms,
        "third_party_script_count": third_party_script_count,
        "tracking": tracking,
        "tracking_evidence": tracking_evidence,
        "tech_cms": tech_cms,
        "tech_framework": tech_framework,
        "tech_ecommerce": tech_ecommerce,
        "tech_hosting_hints": tech_hosting_hints,
        "tech_confidence": tech_confidence,
        "business_signals": business_signals,
    }


def create_psi_cache_data(
    url: str,
    strategy: str,
    performance: int | None,
    seo: int | None,
    accessibility: int | None,
    best_practices: int | None,
    lcp_ms: int | None,
    inp_ms: int | None,
    cls: float | None,
    ttfb_ms: int | None,
    fcp_ms: int | None,
    opportunities: list[dict[str, str]],
    diagnostics: list[dict[str, str]],
) -> dict:
    """Create PSI cache entry data dictionary."""
    return {
        "url": url,
        "strategy": strategy,
        "performance": performance,
        "seo": seo,
        "accessibility": accessibility,
        "best_practices": best_practices,
        "lcp_ms": lcp_ms,
        "inp_ms": inp_ms,
        "cls": cls,
        "ttfb_ms": ttfb_ms,
        "fcp_ms": fcp_ms,
        "opportunities": opportunities,
        "diagnostics": diagnostics,
    }
