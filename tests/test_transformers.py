import asyncio
import datetime
from contextlib import asynccontextmanager
from types import SimpleNamespace

import aiohttp
import pytest

from utilities.errors import UserFacingError
from utilities.transformers import parse_future_date, validate_url


def test_absolute_date_parses_utc_aware() -> None:
    parsed = parse_future_date("2030-01-02 15:00 UTC")
    assert parsed == datetime.datetime(2030, 1, 2, 15, 0, tzinfo=datetime.UTC)


def test_relative_date_prefers_future() -> None:
    parsed = parse_future_date("in 2 days")
    assert parsed > datetime.datetime.now(datetime.UTC)


def test_garbage_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_future_date("definitely not a date")


class FakeSession:
    """Stands in for aiohttp.ClientSession: records URLs, returns a canned response."""

    def __init__(
        self,
        *,
        status: int = 200,
        resolved: str = "https://example.com/",
        error: Exception | None = None,
    ) -> None:
        self._status = status
        self._resolved = resolved
        self._error = error
        self.requested: list[str] = []

    def get(self, url: str):
        self.requested.append(url)
        if self._error is not None:
            raise self._error

        @asynccontextmanager
        async def _response():
            yield SimpleNamespace(status=self._status, url=self._resolved)

        return _response()


def test_validate_url_prepends_https_and_returns_resolved() -> None:
    session = FakeSession(resolved="https://example.com/guide")
    result = asyncio.run(validate_url(session, "  example.com/guide "))
    assert session.requested == ["https://example.com/guide"]
    assert result == "https://example.com/guide"


def test_validate_url_keeps_explicit_scheme() -> None:
    session = FakeSession()
    asyncio.run(validate_url(session, "http://example.com"))
    assert session.requested == ["http://example.com"]


def test_validate_url_non_200_rejected() -> None:
    session = FakeSession(status=404)
    with pytest.raises(UserFacingError):
        asyncio.run(validate_url(session, "https://example.com"))


def test_validate_url_client_error_rejected() -> None:
    session = FakeSession(error=aiohttp.ClientError())
    with pytest.raises(UserFacingError):
        asyncio.run(validate_url(session, "https://example.com"))
