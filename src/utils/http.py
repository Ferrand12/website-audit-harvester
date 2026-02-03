from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("harvester")

TRANSIENT_CODES = {429, 500, 502, 503, 504}

MAX_HTML_BYTES = 2 * 1024 * 1024  # 2 MB

_USER_AGENT = (
    "Mozilla/5.0 (compatible; WebsiteAuditHarvester/0.1; "
    "+https://github.com/example/website-audit-harvester)"
)


def fetch_json(
    url: str,
    *,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_base: float = 2.0,
) -> dict:
    """GET a URL and return parsed JSON, with retries on transient errors."""
    request = Request(url, headers={"Accept": "application/json"})

    for attempt in range(max_retries + 1):
        try:
            with urlopen(request, timeout=timeout) as resp:
                return json.loads(resp.read())
        except HTTPError as exc:
            if exc.code in TRANSIENT_CODES and attempt < max_retries:
                wait = backoff_base ** attempt
                logger.warning(
                    "HTTP %d from %s, retrying in %.1fs (attempt %d/%d)",
                    exc.code, url, wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
                continue
            raise
        except (URLError, TimeoutError) as exc:
            if attempt < max_retries:
                wait = backoff_base ** attempt
                logger.warning(
                    "Network error for %s: %s, retrying in %.1fs (attempt %d/%d)",
                    url, exc, wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"fetch_json failed after {max_retries + 1} attempts: {url}")


@dataclass
class HTMLResponse:
    status: int
    final_url: str
    body: str
    headers: dict[str, str]
    elapsed_ms: int


def fetch_html(
    url: str,
    *,
    timeout: float = 15.0,
    max_bytes: int = MAX_HTML_BYTES,
) -> HTMLResponse:
    """Fetch a single page of HTML. Follows redirects, caps download size."""
    request = Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    })

    start = time.monotonic()
    with urlopen(request, timeout=timeout) as resp:
        raw = resp.read(max_bytes)
        elapsed_ms = round((time.monotonic() - start) * 1000)
        # Best-effort decode
        charset = resp.headers.get_content_charset() or "utf-8"
        try:
            body = raw.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            body = raw.decode("utf-8", errors="replace")

        headers = {k.lower(): v for k, v in resp.headers.items()}
        return HTMLResponse(
            status=resp.status,
            final_url=resp.url,
            body=body,
            headers=headers,
            elapsed_ms=elapsed_ms,
        )
