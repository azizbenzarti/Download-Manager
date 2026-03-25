from __future__ import annotations

import time
from typing import Callable, TypeVar


T = TypeVar("T")


class RetryError(Exception):
    """Raised when all retry attempts are exhausted."""


class RetryPolicy:
    """
    Simple retry policy with optional exponential backoff.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        backoff_factor: float = 2.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.backoff_factor = backoff_factor

    def get_delay(self, attempt_number: int) -> float:
        """
        attempt_number starts at 1
        """
        return self.base_delay * (self.backoff_factor ** (attempt_number - 1))

    def execute(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute a function with retries.
        """
        last_exception: Exception | None = None

        for attempt in range(1, self.max_retries + 2):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                last_exception = exc

                if attempt > self.max_retries:
                    break

                delay = self.get_delay(attempt)
                time.sleep(delay)

        raise RetryError(
            f"Operation failed after {self.max_retries + 1} attempts"
        ) from last_exception