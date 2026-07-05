import math
from typing import Final

VERIFIED = "<:_:1042541867469910056>"
HALF_VERIFIED = "<:_:1042541868723998871>"
UNVERIFIED = "<:_:1042541865821556746>"

TROPHY = "🏆"
TIME = "⌛"

FIRST = "<:_:1043226244575142018>"
SECOND = "<:_:1043226243463659540>"
THIRD = "<:_:1043226242335391794>"

STAR = "★"
EMPTY_STAR = "☆"

# The legacy "upper" reaction the old bot counted spectacular-record votes with.
UPPER_REACTION_ID: Final = 787788134620332063

_STAR_TIERS: Final[tuple[tuple[int, str], ...]] = (
    (15, "<:_:873791530018701312>"),
    (10, "<:_:873791529926414336>"),
    (5, "<:_:873791529876082758>"),
    (0, "<:_:929871697555914752>"),
)


def star_tier_emoji(count: int) -> str:
    """Emoji for a spectacular-record star count, escalating with the count."""
    return next(emoji for threshold, emoji in _STAR_TIERS if count >= threshold)


PLACEMENTS: Final[dict[int, str]] = {
    1: FIRST,
    2: SECOND,
    3: THIRD,
}


def get_placement_emoji(placement: int) -> str:
    """Get the placement emoji."""
    return PLACEMENTS.get(placement, "")


def stars_rating_string(rating: float | None = None) -> str:
    """Create a star rating string."""
    if not rating:
        return "Unrated"
    filled = math.ceil(rating) * STAR
    return filled + ((5 - len(filled)) * EMPTY_STAR)


def generate_all_star_rating_strings() -> list[str]:
    """Generate all possible star combinations."""
    return [stars_rating_string(x) for x in range(6)]


GOLD_RANK = "<:gold:931317421862699118>"
DIAMOND_RANK = "<:diamond:931317455639445524>"
GRANDMASTER_RANK = "<:grandmaster:931317469396729876>"

_RANK_EMOJIS: Final[dict[str, str]] = {
    "Gold": GOLD_RANK,
    "Diamond": DIAMOND_RANK,
    "Grandmaster": GRANDMASTER_RANK,
}


def rank_emoji(value: str) -> str:
    """Emoji for a tournament rank name; empty string for Unranked/unknown."""
    return _RANK_EMOJIS.get(value, "")
