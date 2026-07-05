import pytest

from extensions.tags.naming import render_table, validate_tag_name
from utilities.errors import UserFacingError

RESERVED = frozenset({"create", "make", "list", "info"})


def test_valid_name_is_stripped_and_lowercased() -> None:
    assert validate_tag_name("  My Tag  ", RESERVED) == "my tag"


def test_empty_name_rejected() -> None:
    with pytest.raises(UserFacingError):
        validate_tag_name("   ", RESERVED)


def test_over_100_chars_rejected() -> None:
    with pytest.raises(UserFacingError):
        validate_tag_name("a" * 101, RESERVED)


def test_reserved_first_word_rejected() -> None:
    with pytest.raises(UserFacingError):
        validate_tag_name("info something", RESERVED)


def test_render_table_lines_up() -> None:
    table = render_table(["name", "uses"], [["hello", 3], ["hi", 21]])
    lines = table.splitlines()
    assert lines[0].startswith("+") and lines[0].endswith("+")
    assert len({len(line) for line in lines}) == 1  # all rows equal width
    assert "hello" in table and "21" in table
