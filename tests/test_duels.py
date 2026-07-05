import pytest

from extensions.duels.models import RESULTS, Outcome, decide


@pytest.mark.parametrize(
    ("player_one", "player_two", "expected"),
    [
        (None, None, Outcome.VOID),
        (10.0, None, Outcome.P1_WIN),
        (None, 10.0, Outcome.P2_WIN),
        (10.0, 10.0, Outcome.DRAW),
        (9.99, 10.0, Outcome.P1_WIN),
        (10.0, 9.99, Outcome.P2_WIN),
    ],
)
def test_decide(
    player_one: float | None, player_two: float | None, expected: Outcome
) -> None:
    assert decide(player_one, player_two) is expected


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (Outcome.P1_WIN, (1, -1)),
        (Outcome.P2_WIN, (-1, 1)),
        (Outcome.DRAW, (0, 0)),
        (Outcome.VOID, (0, 0)),
    ],
)
def test_results_mapping(outcome: Outcome, expected: tuple[int, int]) -> None:
    assert RESULTS[outcome] == expected
