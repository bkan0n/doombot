import pytest

from extensions.gym.calc import ONE_REP_MAX_FORMULAS, kg_to_lb, lb_to_kg


def test_lb_kg_round_trip_approximate() -> None:
    assert lb_to_kg(220.0) == 100.0
    assert kg_to_lb(100.0) == 220.0


def test_epley_known_value() -> None:
    # 100kg x 10 reps -> 100 * (1 + 10/30) = 133.33...
    assert ONE_REP_MAX_FORMULAS["Epley"](100, 10) == pytest.approx(133.33, abs=0.01)


def test_brzycki_single_rep_is_identity() -> None:
    assert ONE_REP_MAX_FORMULAS["Brzycki"](100, 1) == pytest.approx(100.0)


def test_all_seven_formulas_present() -> None:
    assert set(ONE_REP_MAX_FORMULAS) == {
        "Brzycki",
        "Epley",
        "Lander",
        "Lombardi",
        "Mayhew",
        "O'Conner",
        "Wathen",
    }
