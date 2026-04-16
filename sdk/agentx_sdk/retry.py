"""AgentX SDK — exponential backoff retry decorator."""
from __future__ import annotations

import functools
import random
import time
from typing import Callable, TypeVar

from .exceptions import ConnectionError as CxError
from .exceptions import RateLimitError, ServerError

F = TypeVar("F", bound=Callable)


def with_retry(max_retries: int = 3, base_delay: float = 0.5) -> Callable[[F], F]:
    """Decorator factory that retries a function on transient failures.

    Retries on:
    - :class:`~agentx_sdk.exceptions.ServerError` (5xx) — exponential backoff
    - :class:`~agentx_sdk.exceptions.ConnectionError` — exponential backoff
    - :class:`~agentx_sdk.exceptions.RateLimitError` (429) — honours ``Retry-After`` header

    Args:
        max_retries: Maximum number of additional attempts after the first failure.
                     ``0`` means no retries (one attempt total).
        base_delay:  Initial backoff seconds for exp-backoff errors. Doubles each attempt,
                     capped at 30 s, with ±0.5 s jitter.

    Returns:
        A decorator that wraps the target function with retry logic.

    Example::

        @with_retry(max_retries=3, base_delay=1.0)
        def _get(self, path: str) -> dict:
            ...
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):  # type: ignore[return]
            last_exc: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return fn(*args, **kwargs)

                except RateLimitError as exc:
                    last_exc = exc
                    if attempt == max_retries:
                        break
                    wait = exc.retry_after + random.uniform(0.0, 0.5)
                    time.sleep(wait)

                except (ServerError, CxError) as exc:
                    last_exc = exc
                    if attempt == max_retries:
                        break
                    delay = min(base_delay * (2 ** attempt), 30.0) + random.uniform(0.0, 0.5)
                    time.sleep(delay)

            assert last_exc is not None  # always set when we reach here
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator
