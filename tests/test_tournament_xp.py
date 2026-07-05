from database.services.tournament import (
    DifficultyMissionRow,
    GeneralMission,
    LeaderboardXPRow,
)
from extensions.tournament import xp as xp_mod


def lb_row(
    user_id: int,
    record: float,
    top: float | None,
    category: str = "Hardcore",
    value: str = "Gold",
) -> LeaderboardXPRow:
    return LeaderboardXPRow(
        nickname=f"user{user_id}",
        user_id=user_id,
        record=record,
        category=category,
        top_record=top,
        value=value,
    )


def mission_row(user_id: int, difficulty: str) -> DifficultyMissionRow:
    return DifficultyMissionRow(
        user_id=user_id,
        category="Hardcore",
        nickname=f"user{user_id}",
        difficulty=difficulty,
        top_record=100.0,
    )


def test_top_record_earns_ceiling() -> None:
    assert xp_mod.leaderboard_xp("Hardcore", 100.0, 100.0) == 2500


def test_slow_record_floors_at_100() -> None:
    assert xp_mod.leaderboard_xp("Time Attack", 10_000.0, 100.0) == 100


def test_multiplier_varies_by_category() -> None:
    hc = xp_mod.leaderboard_xp("Hardcore", 110.0, 100.0)
    ta = xp_mod.leaderboard_xp("Time Attack", 110.0, 100.0)
    assert hc > ta  # HC multiplier is far more forgiving


def test_missing_top_record_treated_as_own_record() -> None:
    assert xp_mod.leaderboard_xp("Bonus", 42.0, None) == 2500


def test_compute_xp_accumulates_leaderboard_and_missions() -> None:
    rows = [lb_row(1, 100.0, 100.0), lb_row(2, 110.0, 100.0)]
    missions = [mission_row(1, "Expert"), mission_row(1, "Easy")]
    xp = xp_mod.compute_xp(rows, missions)
    assert xp[1].hardcore == 2500
    assert xp[1].expert == 1 and xp[1].easy == 1
    assert xp[1].mission_total == 2500  # 2000 + 500
    assert xp[1].total == 2500 + 2500
    assert xp[2].total == xp[2].hardcore > 100


def test_general_xp_threshold() -> None:
    xp = xp_mod.compute_xp([lb_row(1, 100.0, 100.0), lb_row(2, 500.0, 100.0)], [])
    mission = GeneralMission(type="XP Threshold", target=2000.0, extra_target=None)
    xp_mod.apply_general_mission(xp, mission, ())
    assert xp[1].general == 1 and xp[1].total == 4500
    assert xp[2].general == 0


def test_general_mission_threshold_counts_difficulty() -> None:
    xp = xp_mod.compute_xp([], [mission_row(1, "Hard"), mission_row(2, "Easy")])
    mission = GeneralMission(type="Mission Threshold", target=1.0, extra_target="Hard")
    xp_mod.apply_general_mission(xp, mission, ())
    assert xp[1].general == 1
    assert xp[2].general == 0


def test_general_top_placement_uses_provided_ids() -> None:
    xp = xp_mod.compute_xp([lb_row(1, 100.0, 100.0)], [])
    mission = GeneralMission(type="Top Placement", target=2.0, extra_target=None)
    before = xp[1].total
    xp_mod.apply_general_mission(xp, mission, (1,))
    assert xp[1].total == before + 2000
