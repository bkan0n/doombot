from __future__ import annotations

import math
import typing
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

if typing.TYPE_CHECKING:
    import io

    from database.services.xp import RankCard

__all__ = ("find_level", "find_portrait", "format_xp", "render_card")

_ASSETS = Path("assets/rank_card")

_PORTRAIT_TIERS: typing.Final = ("bronze", "silver", "gold", "platinum", "diamond")

_RANK_LOGOS: typing.Final[dict[str, str]] = {
    "Unranked": "bronze.png",
    "Gold": "gold.png",
    "Diamond": "diamond.png",
    "Grandmaster": "grandmaster.png",
}
_POSITION_PORTRAITS: typing.Final[dict[int, str]] = {
    1: "gold_position.png",
    2: "silver_position.png",
    3: "bronze_position.png",
}

# Card geometry: the background is 1175x348 and the finished card is
# downscaled 2x. Positions are the old bot's layout arithmetic, pre-folded.
_CENTER_X = 602  # half the canvas width plus the background art's 15px inset
_AVATAR_SIZE = 200
_AVATAR_POS = (55, 74)
_LEVEL_PORTRAIT_POS = (-60, -30)
_RANK_LOGO_SIZE = (100, 100)
_RANK_LOGO_XS = (340, 473, 606)
_RANK_LOGO_Y = 94
_NAME_Y = 203
_XP_Y = 248
_DUELS_CENTER_X = 789
_WINS_Y = 98
_LOSSES_Y = 138
_PLACE_CIRCLE = (930, 69, 1140, 279)
_PLACE_CIRCLE_FILL = (9, 10, 11, 255)
_PLACE_FONT_SIZES: typing.Final[dict[int, int]] = {1: 120, 2: 110, 3: 100}
_POSITION_PORTRAIT_POS = (825, -28)
_WHITE = (255, 255, 255)


def format_xp(xp: int) -> str:
    """Abbreviate an XP total: 1500 -> '1.5k', 2_500_000 -> '2.5m'."""
    for threshold, suffix in ((1_000_000, "m"), (1_000, "k")):
        if xp >= threshold:
            return f"{xp / threshold:.1f}".removesuffix(".0") + suffix
    return str(xp)


def find_level(xp: int) -> int:
    """Level for an XP total; the curve tops out at level 100."""
    total = 0
    for level in range(100):
        total += 5 * level**2 + 50 * level + 100
        if total > xp:
            return level
    return 100


def find_portrait(level: int) -> str:
    """Portrait filename: tiers step every 20 levels, variants 1-5 within.

    Level 20 stays in bronze (ported quirk) and 100+ is always diamond5.
    """
    if level >= 100:
        return "diamond5.png"
    tier = _PORTRAIT_TIERS[0 if level <= 20 else level // 20]
    variant = math.ceil(level % 20 / 4) or 1
    return f"{tier}{variant}.png"


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_ASSETS / "fonts" / name, size)


def _open_asset(*parts: str) -> Image.Image:
    return Image.open(_ASSETS.joinpath(*parts)).convert("RGBA")


def _circular_avatar(avatar: io.BytesIO) -> tuple[Image.Image, Image.Image]:
    image = Image.open(avatar).convert("RGBA")
    image.thumbnail((_AVATAR_SIZE, _AVATAR_SIZE))
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, _AVATAR_SIZE, _AVATAR_SIZE), fill=255)
    return image, mask


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    y: float,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> None:
    x = center_x - draw.textlength(text, font=font) // 2
    draw.text((x, y), text, fill=_WHITE, font=font)


def render_card(avatar: io.BytesIO, data: RankCard) -> Image.Image:
    """Compose the rank card; synchronous, call via ``asyncio.to_thread``."""
    background = _open_asset("background.png")
    img = Image.new("RGBA", background.size, (0, 0, 0, 0))
    img.paste(background)
    draw = ImageDraw.Draw(img, "RGBA")

    avatar_img, mask = _circular_avatar(avatar)
    img.paste(avatar_img, _AVATAR_POS, mask)

    level_portrait = _open_asset("portraits", find_portrait(find_level(data.xp)))
    img.paste(level_portrait, _LEVEL_PORTRAIT_POS, level_portrait)

    categories = (data.time_attack, data.mildcore, data.hardcore)
    for x, rank in zip(_RANK_LOGO_XS, categories, strict=True):
        logo = _open_asset("ranks", _RANK_LOGOS[rank])
        logo.thumbnail(_RANK_LOGO_SIZE)
        img.paste(logo, (x, _RANK_LOGO_Y), logo)

    name_font = _font("avenir.otf", 50)
    _draw_centered(draw, _CENTER_X, _NAME_Y, data.nickname[:18], name_font)

    duels_font = _font("segoeui.ttf", 30)
    _draw_centered(draw, _DUELS_CENTER_X, _WINS_Y, f"{data.wins} W", duels_font)
    _draw_centered(draw, _DUELS_CENTER_X, _LOSSES_Y, f"{data.losses} L", duels_font)

    xp_text = f"Total XP: {format_xp(data.xp)}"
    _draw_centered(draw, _CENTER_X, _XP_Y, xp_text, _font("segoeui.ttf", 40))

    draw.ellipse(_PLACE_CIRCLE, fill=_PLACE_CIRCLE_FILL)
    place = str(data.pos)
    place_font = _font("segoeui.ttf", _PLACE_FONT_SIZES.get(len(place), 85))
    ascent, _ = place_font.getmetrics()
    place_y = img.height // 2 - (ascent - place_font.getbbox(place)[1])
    circle_center_x = (_PLACE_CIRCLE[0] + _PLACE_CIRCLE[2]) // 2
    _draw_centered(draw, circle_center_x, place_y, place, place_font)

    position_portrait = _open_asset(
        "portraits", _POSITION_PORTRAITS.get(data.pos, "no_position.png")
    )
    img.paste(position_portrait, _POSITION_PORTRAIT_POS, position_portrait)

    return img.resize((img.width // 2, img.height // 2))
