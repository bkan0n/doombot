__all__ = ("make_ordinal", "pretty_record")


def pretty_record(record: float) -> str:
    """Format seconds as [-][H:][MM:]SS.ss, dropping leading zero units."""
    negative = "-" if record < 0 else ""
    hours, rem = divmod(abs(record), 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{negative}{int(hours)}:{int(minutes):02}:{seconds:05.2f}"
    if minutes:
        return f"{negative}{int(minutes)}:{seconds:05.2f}"
    return f"{negative}{seconds:.2f}"


def make_ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 11 -> '11th', 122 -> '122nd'."""
    suffix = ["th", "st", "nd", "rd", "th"][min(n % 10, 4)]
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    return f"{n}{suffix}"
