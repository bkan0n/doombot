import datetime

import pytest

from utilities.transformers import parse_future_date


def test_absolute_date_parses_utc_aware() -> None:
    parsed = parse_future_date("2030-01-02 15:00 UTC")
    assert parsed == datetime.datetime(2030, 1, 2, 15, 0, tzinfo=datetime.UTC)


def test_relative_date_prefers_future() -> None:
    parsed = parse_future_date("in 2 days")
    assert parsed > datetime.datetime.now(datetime.UTC)


def test_garbage_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_future_date("definitely not a date")
