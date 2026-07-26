"""Exceptions for Sydney Transport Live."""

from __future__ import annotations


class TfnswError(Exception):
    """Base exception for TfNSW API errors."""


class TfnswAuthError(TfnswError):
    """Raised when the API key is missing or rejected."""


class TfnswApiError(TfnswError):
    """Raised when the TfNSW API returns an unexpected error."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class TfnswRateLimitError(TfnswApiError):
    """Raised when the API rate-limits the client."""

    def __init__(
        self,
        message: str = "TfNSW API rate limited",
        *,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message, status=429)
        self.retry_after = retry_after
