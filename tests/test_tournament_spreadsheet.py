import zipfile

from database.services.tournament import SpreadsheetRecord
from extensions.tournament.spreadsheet import build_spreadsheet
from extensions.tournament.xp import UserXP


def test_build_spreadsheet_contains_all_sheets_and_data() -> None:
    records = [
        SpreadsheetRecord(
            user_id=1,
            nickname="alice",
            category="Hardcore",
            record=100.0,
            rank="Grandmaster",
            date_rank=1,
        )
    ]
    xp = {1: UserXP(nickname="alice", hardcore=2500, total=4500, mission_total=2000)}
    buffer = build_spreadsheet(records, xp)
    with zipfile.ZipFile(buffer) as zf:
        workbook = zf.read("xl/workbook.xml").decode()
        for sheet in ("Grandmaster", "Diamond", "Gold", "Unranked", "Missions"):
            assert sheet in workbook
        shared = zf.read("xl/sharedStrings.xml").decode()
        assert "alice (1)" in shared


def test_build_spreadsheet_empty_inputs() -> None:
    buffer = build_spreadsheet([], {})
    assert buffer.getbuffer().nbytes > 0
