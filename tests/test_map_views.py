import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from extensions.maps.views import (
    _GUIDE_WARNING,
    _LEVELS_DESCRIPTION,
    _LEVELS_LABEL,
    MapSubmission,
    MapSubmissionReview,
    _drop_invalid_guide,
    _levels_display,
    _parse_levels,
    _persist_submission,
    _validate_guide,
    map_submission_body,
)
from utilities.errors import UserFacingError


def test_parse_levels_strips_and_dedupes_preserving_order() -> None:
    raw = "  Level 1  \nLevel 2\nLevel 1\n\n  Trial of Agony\n"
    assert _parse_levels(raw) == ["Level 1", "Level 2", "Trial of Agony"]


def test_parse_levels_whitespace_only_rejected() -> None:
    with pytest.raises(UserFacingError):
        _parse_levels(" \n\t\n ")


def test_levels_display_numbers_and_counts() -> None:
    assert _levels_display(["Alpha", "Beta"]) == "**Levels (2)**\n1. Alpha\n2. Beta"


def test_map_submission_body_renders_numbered_levels() -> None:
    sub = MapSubmission(
        map_code="ABC123",
        map_name="Hanamura",
        map_types=["Single"],
        description="",
        levels=["Alpha", "Beta"],
        image_url=None,
    )
    strings = [
        item
        for item in map_submission_body(sub, header="Preview")
        if isinstance(item, str)
    ]
    assert "**Levels (2)**\n1. Alpha\n2. Beta" in strings


def test_map_submission_body_can_omit_levels() -> None:
    sub = MapSubmission(
        map_code="ABC123",
        map_name="Hanamura",
        map_types=["Single"],
        description="",
        levels=["Alpha", "Beta"],
        image_url=None,
    )
    body = map_submission_body(sub, header="Announcement", include_levels=False)
    strings = [item for item in body if isinstance(item, str)]
    assert not any("**Levels" in item for item in strings)
    assert any("`Levels` 2" in item for item in strings)


def test_map_submission_body_no_level_count_when_list_shown() -> None:
    body = map_submission_body(_sub(levels=["Alpha", "Beta"]), header="Preview")
    strings = [item for item in body if isinstance(item, str)]
    assert not any("`Levels`" in item for item in strings)


def test_levels_label_copy_within_discord_limits() -> None:
    assert len(_LEVELS_LABEL) <= 45
    assert len(_LEVELS_DESCRIPTION) <= 100


def _sub(**overrides) -> MapSubmission:
    defaults = dict(
        map_code="ABC123",
        map_name="Hanamura",
        map_types=["Single"],
        description="",
        levels=["Alpha"],
        image_url=None,
    )
    return MapSubmission(**defaults | overrides)


def test_map_submission_body_renders_guide_line() -> None:
    body = map_submission_body(
        _sub(guide_url="https://example.com/guide"), header="Preview"
    )
    strings = [item for item in body if isinstance(item, str)]
    assert any("`Guide` [View](https://example.com/guide)" in s for s in strings)
    assert _GUIDE_WARNING not in strings


def test_map_submission_body_omits_guide_line_when_absent() -> None:
    body = map_submission_body(_sub(), header="Preview")
    strings = [item for item in body if isinstance(item, str)]
    assert not any("`Guide`" in s for s in strings)
    assert _GUIDE_WARNING not in strings


def test_map_submission_body_warns_on_invalid_guide() -> None:
    body = map_submission_body(
        _sub(guide_url="https://example.com/dead", guide_valid=False),
        header="Preview",
    )
    strings = [item for item in body if isinstance(item, str)]
    assert _GUIDE_WARNING in strings


def test_drop_invalid_guide_blanks_only_invalid() -> None:
    invalid = _sub(guide_url="https://example.com/dead", guide_valid=False)
    dropped = _drop_invalid_guide(invalid)
    assert dropped.guide_url is None
    assert dropped.guide_valid is True

    valid = _sub(guide_url="https://example.com/guide")
    assert _drop_invalid_guide(valid) is valid


class FakeSession:
    def __init__(
        self, *, status: int = 200, resolved: str = "https://example.com/"
    ) -> None:
        self._status = status
        self._resolved = resolved

    def get(self, url: str):
        @asynccontextmanager
        async def _response():
            yield SimpleNamespace(status=self._status, url=self._resolved)

        return _response()


class RecordingMaps:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def create_map(self, **kwargs) -> None:
        self.calls.append(("create_map", kwargs))

    async def add_creator(self, map_code: str, user_id: int) -> None:
        self.calls.append(("add_creator", map_code, user_id))

    async def add_levels(self, map_code: str, levels: list[str]) -> None:
        self.calls.append(("add_levels", map_code, levels))

    async def add_guide(self, map_code: str, url: str) -> None:
        self.calls.append(("add_guide", map_code, url))


def test_validate_guide_blank_is_no_guide() -> None:
    assert asyncio.run(_validate_guide(FakeSession(), "   ")) == (None, True)


def test_validate_guide_reachable_returns_resolved() -> None:
    session = FakeSession(resolved="https://example.com/guide")
    assert asyncio.run(_validate_guide(session, "example.com/guide")) == (
        "https://example.com/guide",
        True,
    )


def test_validate_guide_unreachable_keeps_normalized_input() -> None:
    session = FakeSession(status=404)
    assert asyncio.run(_validate_guide(session, "example.com/dead")) == (
        "https://example.com/dead",
        False,
    )


def _persist(sub: MapSubmission) -> RecordingMaps:
    maps = RecordingMaps()
    svc = SimpleNamespace(maps=maps)
    asyncio.run(_persist_submission(svc, sub, creator_id=42))
    return maps


def test_persist_submission_inserts_valid_guide() -> None:
    maps = _persist(_sub(guide_url="https://example.com/guide"))
    assert ("add_guide", "ABC123", "https://example.com/guide") in maps.calls


def test_persist_submission_skips_invalid_guide() -> None:
    maps = _persist(_sub(guide_url="https://example.com/dead", guide_valid=False))
    assert not any(call[0] == "add_guide" for call in maps.calls)
    assert any(call[0] == "create_map" for call in maps.calls)


def test_persist_submission_skips_absent_guide() -> None:
    maps = _persist(_sub())
    assert not any(call[0] == "add_guide" for call in maps.calls)


def test_update_guide_swaps_staged_submission() -> None:
    review = MapSubmissionReview.__new__(MapSubmissionReview)  # skip discord setup
    review.sub = _sub(guide_url="https://example.com/dead", guide_valid=False)

    class _Response:
        async def edit_message(self, **kwargs) -> None:
            pass

    async def _run() -> None:
        review._render = lambda footer: None  # rendering needs discord items
        review._buttons = None
        await review.update_guide(
            SimpleNamespace(response=_Response()),
            "https://example.com/guide",
            valid=True,
        )

    asyncio.run(_run())
    assert review.sub.guide_url == "https://example.com/guide"
    assert review.sub.guide_valid is True
