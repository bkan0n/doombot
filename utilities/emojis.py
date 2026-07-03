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
