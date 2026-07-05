from __future__ import annotations

import math
import typing

import msgspec

from .models import Category, MissionDifficulty, MissionType

if typing.TYPE_CHECKING:
    from collections.abc import Collection

    from database.services.tournament import (
        DifficultyMissionRow,
        GeneralMission,
        LeaderboardXPRow,
    )

__all__ = (
    "MISSION_POINTS",
    "XP_MULTIPLIER",
    "UserXP",
    "apply_general_mission",
    "compute_xp",
    "leaderboard_xp",
)

# Ported verbatim from the old bot; tuned so each category's XP curve decays
# at a different rate relative to the rank group's top time.
XP_MULTIPLIER: typing.Final[dict[Category, float]] = {
    Category.TIME_ATTACK: 0.14094,
    Category.MILDCORE: 0.3654,
    Category.HARDCORE: 0.8352,
    Category.BONUS: 0.3654,
}

MISSION_POINTS: typing.Final[dict[MissionDifficulty, int]] = {
    MissionDifficulty.EXPERT: 2000,
    MissionDifficulty.HARD: 1500,
    MissionDifficulty.MEDIUM: 1000,
    MissionDifficulty.EASY: 500,
    MissionDifficulty.GENERAL: 2000,
}

_XP_CEILING: typing.Final = 2500
_XP_FLOOR: typing.Final = 100

_CATEGORY_FIELD: typing.Final[dict[str, str]] = {
    Category.TIME_ATTACK: "time_attack",
    Category.MILDCORE: "mildcore",
    Category.HARDCORE: "hardcore",
    Category.BONUS: "bonus",
}

_DIFFICULTY_FIELD: typing.Final[dict[str, str]] = {
    MissionDifficulty.EASY: "easy",
    MissionDifficulty.MEDIUM: "medium",
    MissionDifficulty.HARD: "hard",
    MissionDifficulty.EXPERT: "expert",
}


class UserXP(msgspec.Struct):
    """Mutable per-user XP accumulator for one tournament."""

    nickname: str
    easy: int = 0
    medium: int = 0
    hard: int = 0
    expert: int = 0
    general: int = 0
    mission_total: int = 0
    total: int = 0
    time_attack: int = 0
    mildcore: int = 0
    hardcore: int = 0
    bonus: int = 0


def leaderboard_xp(category: str, record: float, top_record: float | None) -> int:
    """XP for one record relative to its rank group's top record.

    top_record is None only when the join produced no group top (degenerate
    single-record groups); the record is then its own top and earns ceiling.
    """
    top = top_record if top_record is not None else record
    multi = XP_MULTIPLIER[Category(category)]
    value = (1 - (record - top) / (multi * top)) * _XP_CEILING
    return max(_XP_FLOOR, math.ceil(value))


def compute_xp(
    lb_rows: list[LeaderboardXPRow],
    mission_rows: list[DifficultyMissionRow],
) -> dict[int, UserXP]:
    """Leaderboard XP plus per-difficulty mission XP, keyed by user id."""
    xp: dict[int, UserXP] = {}
    for row in lb_rows:
        user = xp.setdefault(row.user_id, UserXP(nickname=row.nickname))
        value = leaderboard_xp(row.category, row.record, row.top_record)
        field = _CATEGORY_FIELD[row.category]
        setattr(user, field, getattr(user, field) + value)
        user.total += value
    for row in mission_rows:
        user = xp.setdefault(row.user_id, UserXP(nickname=row.nickname))
        points = MISSION_POINTS[MissionDifficulty(row.difficulty)]
        user.mission_total += points
        user.total += points
        field = _DIFFICULTY_FIELD[row.difficulty]
        setattr(user, field, getattr(user, field) + 1)
    return xp


def apply_general_mission(
    xp: dict[int, UserXP],
    mission: GeneralMission,
    top_placement_user_ids: Collection[int],
) -> None:
    """Award the tournament-wide General mission (2000 XP) in place.

    Top Placement eligibility comes from the DB (the caller passes the ids
    from fetch_top_placement_users); the other two derive from the already
    computed totals.
    """
    target = mission.target or 0
    if mission.type == MissionType.XP_THRESHOLD:
        eligible = [uid for uid, user in xp.items() if user.total >= target]
    elif mission.type == MissionType.MISSION_THRESHOLD:
        field = _DIFFICULTY_FIELD.get(mission.extra_target or "")
        if field is None:
            return
        eligible = [uid for uid, user in xp.items() if getattr(user, field) >= target]
    elif mission.type == MissionType.TOP_PLACEMENT:
        eligible = [uid for uid in top_placement_user_ids if uid in xp]
    else:
        return
    for uid in eligible:
        user = xp[uid]
        user.mission_total += MISSION_POINTS[MissionDifficulty.GENERAL]
        user.total += MISSION_POINTS[MissionDifficulty.GENERAL]
        user.general = 1
