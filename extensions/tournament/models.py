from __future__ import annotations

import enum

import msgspec

from utilities.errors import UserFacingError
from utilities.transformers import time_convert

__all__ = (
    "Category",
    "MapEntry",
    "MissionDifficulty",
    "MissionType",
    "Rank",
    "parse_mission_target",
)


class Category(enum.StrEnum):
    TIME_ATTACK = "Time Attack"
    MILDCORE = "Mildcore"
    HARDCORE = "Hardcore"
    BONUS = "Bonus"
    GENERAL = "General"

    @classmethod
    def playable(cls) -> tuple[Category, ...]:
        return cls.TIME_ATTACK, cls.MILDCORE, cls.HARDCORE, cls.BONUS


class Rank(enum.StrEnum):
    UNRANKED = "Unranked"
    GOLD = "Gold"
    DIAMOND = "Diamond"
    GRANDMASTER = "Grandmaster"


class MissionDifficulty(enum.StrEnum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"
    EXPERT = "Expert"
    GENERAL = "General"


class MissionType(enum.StrEnum):
    XP_THRESHOLD = "XP Threshold"
    MISSION_THRESHOLD = "Mission Threshold"
    TOP_PLACEMENT = "Top Placement"
    SUB_TIME = "Sub Time"
    COMPLETION = "Completion"

    @classmethod
    def general(cls) -> tuple[MissionType, ...]:
        return cls.XP_THRESHOLD, cls.MISSION_THRESHOLD, cls.TOP_PLACEMENT

    @classmethod
    def difficulty(cls) -> tuple[MissionType, ...]:
        return cls.SUB_TIME, cls.COMPLETION


class MapEntry(msgspec.Struct, frozen=True):
    code: str
    level: str
    creator: str


def _to_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise UserFacingError("Target must be a whole number.") from None


def parse_mission_target(
    mission_type: MissionType, raw: str
) -> tuple[float, str | None]:
    """Validate a raw mission target string into (target, extra_target).

    Mission Threshold packs two values into one input ("3 Hard"): the count
    goes to target and the difficulty name to extra_target (a text column).
    """
    if mission_type is MissionType.MISSION_THRESHOLD:
        count, _, difficulty = raw.strip().partition(" ")
        difficulty = difficulty.strip().capitalize()
        if difficulty not in ("Easy", "Medium", "Hard", "Expert"):
            raise UserFacingError(
                "Mission Threshold target must look like `3 Hard` (count + difficulty)."
            )
        return _to_int(count), difficulty
    if mission_type in (MissionType.XP_THRESHOLD, MissionType.TOP_PLACEMENT):
        return _to_int(raw.strip()), None
    if mission_type is MissionType.SUB_TIME:
        try:
            return time_convert(raw.strip()), None
        except ValueError:
            raise UserFacingError(
                "Sub Time target must be a [HH:][MM:]SS.ss time."
            ) from None
    return 0.0, None  # Completion needs no target
