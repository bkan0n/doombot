import io

from PIL import Image

from database.services.xp import RankCard
from extensions.xp import card

# --- format_xp -----------------------------------------------------------


def test_format_xp_below_1k_unchanged() -> None:
    assert card.format_xp(0) == "0"
    assert card.format_xp(999) == "999"


def test_format_xp_thousands() -> None:
    assert card.format_xp(1000) == "1k"
    assert card.format_xp(1500) == "1.5k"
    assert card.format_xp(12_345) == "12.3k"


def test_format_xp_millions_boundary() -> None:
    # Old bot printed exactly 1_000_000 unformatted; the boundary is now >=.
    assert card.format_xp(1_000_000) == "1m"
    assert card.format_xp(2_500_000) == "2.5m"


# --- find_level ----------------------------------------------------------


def test_find_level_first_thresholds() -> None:
    # Level 0 requires 100 XP: 5*0^2 + 50*0 + 100.
    assert card.find_level(0) == 0
    assert card.find_level(99) == 0
    assert card.find_level(100) == 1


def test_find_level_clamps_at_100() -> None:
    assert card.find_level(10**9) == 100


# --- find_portrait -------------------------------------------------------


def test_find_portrait_bronze_band_includes_level_20() -> None:
    # Ported quirk: the old `level <= 20` branch keeps level 20 in bronze.
    assert card.find_portrait(0) == "bronze1.png"
    assert card.find_portrait(20) == "bronze1.png"
    assert card.find_portrait(21) == "silver1.png"


def test_find_portrait_variant_within_band() -> None:
    assert card.find_portrait(39) == "silver5.png"
    assert card.find_portrait(40) == "gold1.png"
    assert card.find_portrait(60) == "platinum1.png"
    assert card.find_portrait(80) == "diamond1.png"


def test_find_portrait_caps_at_diamond5() -> None:
    assert card.find_portrait(99) == "diamond5.png"
    assert card.find_portrait(100) == "diamond5.png"
    assert card.find_portrait(150) == "diamond5.png"


# --- render_card ---------------------------------------------------------


def _fake_avatar() -> io.BytesIO:
    buffer = io.BytesIO()
    Image.new("RGBA", (256, 256), (120, 60, 200, 255)).save(buffer, "PNG")
    buffer.seek(0)
    return buffer


def test_render_card_smoke() -> None:
    data = RankCard(
        user_id=1,
        nickname="TestPlayer",
        xp=123_456,
        pos=1,
        time_attack="Gold",
        mildcore="Diamond",
        hardcore="Grandmaster",
        bonus="Unranked",
        wins=3,
        losses=2,
    )
    image = card.render_card(_fake_avatar(), data)
    # Background is 1175x348; the card is downscaled 2x at the end.
    assert image.size == (587, 174)
