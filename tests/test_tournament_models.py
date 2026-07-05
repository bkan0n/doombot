import pytest

from extensions.tournament.models import (
    MissionType,
    parse_mission_target,
)
from utilities.errors import UserFacingError


def test_sub_time_target_parses_time_string() -> None:
    target, extra = parse_mission_target(MissionType.SUB_TIME, "1:23.45")
    assert target == pytest.approx(83.45)
    assert extra is None


def test_sub_time_rejects_garbage() -> None:
    with pytest.raises(UserFacingError):
        parse_mission_target(MissionType.SUB_TIME, "not a time")


def test_mission_threshold_splits_count_and_difficulty() -> None:
    target, extra = parse_mission_target(MissionType.MISSION_THRESHOLD, "3 hard")
    assert target == 3
    assert extra == "Hard"


def test_mission_threshold_rejects_bad_difficulty() -> None:
    with pytest.raises(UserFacingError):
        parse_mission_target(MissionType.MISSION_THRESHOLD, "3 impossible")


def test_xp_threshold_requires_integer() -> None:
    assert parse_mission_target(MissionType.XP_THRESHOLD, "5000") == (5000, None)
    with pytest.raises(UserFacingError):
        parse_mission_target(MissionType.XP_THRESHOLD, "lots")


def test_top_placement_requires_integer() -> None:
    assert parse_mission_target(MissionType.TOP_PLACEMENT, "2") == (2, None)


def test_completion_has_no_target() -> None:
    assert parse_mission_target(MissionType.COMPLETION, "ignored") == (0.0, None)
