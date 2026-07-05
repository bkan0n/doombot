from __future__ import annotations

import io
import typing

import xlsxwriter

from .models import Category, Rank
from .xp import UserXP

if typing.TYPE_CHECKING:
    from database.services.tournament import SpreadsheetRecord

__all__ = ("build_spreadsheet",)

# (name column, time column, points column) per category block.
_COLUMNS: typing.Final[dict[str, tuple[int, int, int]]] = {
    Category.TIME_ATTACK: (0, 1, 2),
    Category.MILDCORE: (4, 5, 6),
    Category.HARDCORE: (8, 9, 10),
    Category.BONUS: (12, 13, 14),
}

_HEADER_COLORS: typing.Final[dict[str, str]] = {
    Category.TIME_ATTACK: "#93c47d",
    Category.MILDCORE: "#ff9900",
    Category.HARDCORE: "#ff0000",
    Category.BONUS: "#ffff00",
}

# (first_col, last_col) of each category's merged title cell on row 0.
_MERGE_RANGES: typing.Final[dict[str, tuple[int, int]]] = {
    Category.TIME_ATTACK: (0, 2),
    Category.MILDCORE: (4, 6),
    Category.HARDCORE: (8, 10),
    Category.BONUS: (12, 14),
}

_CATEGORY_XP_FIELD: typing.Final[dict[str, str]] = {
    Category.TIME_ATTACK: "time_attack",
    Category.MILDCORE: "mildcore",
    Category.HARDCORE: "hardcore",
    Category.BONUS: "bonus",
}


def build_spreadsheet(
    records: list[SpreadsheetRecord], xp: dict[int, UserXP]
) -> io.BytesIO:
    """Per-rank leaderboard sheets plus a missions sheet, as xlsx bytes."""
    buffer = io.BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
    rank_sheets = {
        rank: workbook.add_worksheet(name=rank)
        for rank in (Rank.GRANDMASTER, Rank.DIAMOND, Rank.GOLD, Rank.UNRANKED)
    }
    missions = workbook.add_worksheet(name="Missions")

    header = workbook.add_format({"align": "left", "border": 1})
    for sheet in rank_sheets.values():
        for category in Category.playable():
            merge = workbook.add_format(
                {"align": "center", "bg_color": _HEADER_COLORS[category], "border": 1}
            )
            first_col, last_col = _MERGE_RANGES[category]
            sheet.merge_range(0, first_col, 0, last_col, str(category), merge)
        sheet.write_row(1, 0, ["Name", "Time", "Points", ""] * 4, cell_format=header)
        sheet.set_column_pixels(0, 15, width=105)

    missions.write_row(
        0,
        0,
        [
            "Names",
            "Easy",
            "Medium",
            "Hard",
            "Expert",
            "General",
            "Missions Total",
            "Total XP",
        ],
        cell_format=workbook.add_format({"border": 1}),
    )
    missions.set_column_pixels(0, 19, width=105)
    for i, (user_id, user) in enumerate(xp.items(), start=1):
        missions.write_row(
            i,
            0,
            [
                f"{user.nickname} ({user_id})",
                user.easy,
                user.medium,
                user.hard,
                user.expert,
                user.general,
                user.mission_total,
                user.total,
            ],
        )

    row_cursor: dict[tuple[str, str], int] = {}
    for record in records:
        if record.rank not in rank_sheets or record.category not in _COLUMNS:
            continue
        key = (record.rank, record.category)
        row = row_cursor.get(key, 2)
        row_cursor[key] = row + 1
        sheet = rank_sheets[Rank(record.rank)]
        name_col, time_col, points_col = _COLUMNS[record.category]
        sheet.write(row, name_col, f"{record.nickname} ({record.user_id})")
        sheet.write(row, time_col, record.record)
        user = xp.get(record.user_id)
        points = getattr(user, _CATEGORY_XP_FIELD[record.category]) if user else 0
        sheet.write(row, points_col, points)

    workbook.close()
    buffer.seek(0)
    return buffer
