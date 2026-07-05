import math
from collections.abc import Callable

__all__ = ("ONE_REP_MAX_FORMULAS", "kg_to_lb", "lb_to_kg")


def lb_to_kg(value: float) -> float:
    return round(round(value, 2) / 2.2, 2)


def kg_to_lb(value: float) -> float:
    return round(2.2 * round(value, 2), 2)


def _brzycki(weight: float, reps: int) -> float:
    return weight * (36 / (37 - reps))


def _epley(weight: float, reps: int) -> float:
    return weight * (1 + reps / 30)


def _lander(weight: float, reps: int) -> float:
    return 100 * (weight / (101.3 - 2.67123 * reps))


def _lombardi(weight: float, reps: int) -> float:
    return weight * reps**0.1


def _mayhew(weight: float, reps: int) -> float:
    return (100 * weight) / (52.2 + 41.9 * math.e ** (-0.055 * reps))


def _oconner(weight: float, reps: int) -> float:
    return weight * (1 + reps / 40)


def _wathen(weight: float, reps: int) -> float:
    return (100 * weight) / (48.8 + 53.8 * math.e ** (-0.075 * reps))


ONE_REP_MAX_FORMULAS: dict[str, Callable[[float, int], float]] = {
    "Brzycki": _brzycki,
    "Epley": _epley,
    "Lander": _lander,
    "Lombardi": _lombardi,
    "Mayhew": _mayhew,
    "O'Conner": _oconner,
    "Wathen": _wathen,
}
