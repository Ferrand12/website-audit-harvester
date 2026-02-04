"""Token bucket rate limiter for PSI API requests."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger("harvester")


@dataclass
class TokenBucket:
    """Thread-safe token bucket rate limiter.

    Implements a token bucket algorithm where tokens are added at a fixed rate
    and requests consume tokens. If no tokens are available, callers block
    until tokens become available.

    Args:
        rate_per_minute: Maximum requests allowed per minute.
        burst: Maximum tokens that can accumulate (defaults to rate_per_minute).
    """
    rate_per_minute: float
    burst: int | None = None

    # Internal state
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.burst is None:
            self.burst = max(1, int(self.rate_per_minute))
        self._tokens = float(self.burst)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        # Calculate tokens to add: rate_per_minute / 60 * elapsed_seconds
        tokens_to_add = (self.rate_per_minute / 60.0) * elapsed
        self._tokens = min(float(self.burst), self._tokens + tokens_to_add)
        self._last_refill = now

    def acquire(self, timeout: float | None = None) -> bool:
        """Acquire a token, blocking if necessary.

        Args:
            timeout: Maximum seconds to wait. None means wait forever.

        Returns:
            True if token was acquired, False if timeout expired.
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True

                # Calculate wait time until next token
                tokens_needed = 1.0 - self._tokens
                wait_seconds = tokens_needed / (self.rate_per_minute / 60.0)

            # Check timeout
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait_seconds = min(wait_seconds, remaining)

            if wait_seconds > 0.1:  # Only log for noticeable waits
                logger.info(
                    "Rate limit: waiting %.2fs for token (rate=%d/min)",
                    wait_seconds, int(self.rate_per_minute)
                )

            time.sleep(wait_seconds)

    def try_acquire(self) -> bool:
        """Try to acquire a token without blocking.

        Returns:
            True if token was acquired, False otherwise.
        """
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    @property
    def available_tokens(self) -> float:
        """Current number of available tokens (for testing/debugging)."""
        with self._lock:
            self._refill()
            return self._tokens


class RateLimiter:
    """Higher-level rate limiter wrapper with named limiters.

    Allows creating and managing multiple named rate limiters
    for different API endpoints or resource types.
    """

    def __init__(self) -> None:
        self._limiters: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        name: str,
        rate_per_minute: float,
        burst: int | None = None,
    ) -> TokenBucket:
        """Get existing limiter or create new one.

        Args:
            name: Unique identifier for the limiter.
            rate_per_minute: Maximum requests per minute.
            burst: Maximum burst capacity.

        Returns:
            TokenBucket instance for the named limiter.
        """
        with self._lock:
            if name not in self._limiters:
                self._limiters[name] = TokenBucket(
                    rate_per_minute=rate_per_minute,
                    burst=burst,
                )
            return self._limiters[name]

    def acquire(self, name: str, timeout: float | None = None) -> bool:
        """Acquire a token from named limiter.

        Args:
            name: Limiter name (must exist).
            timeout: Maximum wait time.

        Returns:
            True if token acquired.

        Raises:
            KeyError: If limiter doesn't exist.
        """
        return self._limiters[name].acquire(timeout=timeout)


# Global rate limiter instance
_global_limiter = RateLimiter()


def get_psi_limiter(rate_per_minute: float) -> TokenBucket:
    """Get the global PSI rate limiter, creating if needed."""
    return _global_limiter.get_or_create("psi", rate_per_minute)
