"""Pure duel decision logic, kept import-light for unit testing."""

import enum


class Outcome(enum.Enum):
    P1_WIN = enum.auto()
    P2_WIN = enum.auto()
    DRAW = enum.auto()
    VOID = enum.auto()


RESULTS: dict[Outcome, tuple[int, int]] = {
    Outcome.P1_WIN: (1, -1),
    Outcome.P2_WIN: (-1, 1),
    Outcome.DRAW: (0, 0),
    Outcome.VOID: (0, 0),
}


def decide(player_one: float | None, player_two: float | None) -> Outcome:
    """Decide a finished duel window; lower time wins, absence forfeits."""
    match (player_one, player_two):
        case (None, None):
            return Outcome.VOID
        case (_, None):
            return Outcome.P1_WIN
        case (None, _):
            return Outcome.P2_WIN
        case (p1, p2) if p1 == p2:
            return Outcome.DRAW
        case (p1, p2):
            return Outcome.P1_WIN if p1 < p2 else Outcome.P2_WIN
