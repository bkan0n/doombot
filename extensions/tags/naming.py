from utilities.errors import UserFacingError

__all__ = ("render_table", "validate_tag_name")


def validate_tag_name(name: str, reserved: frozenset[str]) -> str:
    """Normalize a tag name to lowercase or raise UserFacingError."""
    lower = name.strip().lower()
    if not lower:
        raise UserFacingError("Missing tag name.")
    if len(lower) > 100:
        raise UserFacingError("Tag name is a maximum of 100 characters.")
    first_word, _, _ = lower.partition(" ")
    if first_word in reserved:
        raise UserFacingError("This tag name starts with a reserved word.")
    return lower


def render_table(columns: list[str], rows: list[list[object]]) -> str:
    """Render an rST grid table (ported from RoboDanny's TabularData)."""
    cells = [[str(value) for value in row] for row in rows]
    widths = [
        max(len(column), *(len(row[i]) for row in cells)) + 2
        for i, column in enumerate(columns)
    ]
    sep = "+" + "+".join("-" * width for width in widths) + "+"

    def line(row: list[str]) -> str:
        body = "|".join(f"{cell:^{widths[i]}}" for i, cell in enumerate(row))
        return f"|{body}|"

    parts = [sep, line(columns), sep, *(line(row) for row in cells), sep]
    return "\n".join(parts)
