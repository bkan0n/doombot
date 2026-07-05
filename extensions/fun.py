from __future__ import annotations

import json
import random
import typing

import discord
from discord import app_commands
from discord.ext import commands

from utilities import checks, views
from utilities.errors import UserFacingError

from ._base import BaseCog

if typing.TYPE_CHECKING:
    from core import Akande, AkandeCtx, AkandeItx

with open("assets/emoji-data.json", encoding="utf8") as f:
    _EMOJI_MAP: dict[str, dict[str, int]] = json.load(f)

_COMMON_WORDS = frozenset(
    "a an as is if of the it its or are this with so to at was and".split()
)

_UWU_TABLE = str.maketrans("lrLR", "wwWW")


def emojify(text: str) -> str:
    """Follow each word with an emoji, weighted by co-occurrence frequency."""
    out: list[str] = []
    for word in text.split():
        out.append(word)
        frequencies = _EMOJI_MAP.get(word.lower())
        if frequencies and word.lower() not in _COMMON_WORDS:
            emoji, weights = zip(*frequencies.items())
            out.append(random.choices(emoji, weights)[0])
    return " ".join(out)


def uwuify(text: str) -> str:
    return text.translate(_UWU_TABLE)


class FunCog(BaseCog, name="fun", description="Fun commands."):
    @commands.command(name="joe-army", aliases=["joe_army"])
    @commands.guild_only()
    async def joe_army(self, ctx: AkandeCtx) -> None:
        """March the Joe army through the channel."""
        flag = "<a:_:1105236433523974305>"
        salute = "<:_:1105236435600146493>"
        left_hulk = "<:joehulk:1105236434660630598>"
        right_hulk = "<:joehulkR:1105236430697021491>"
        running = "<a:runningjoe:1105236437290455132>"
        row = (
            f"{flag}{salute * 3}{left_hulk * 3}{running * 3}"
            f"{right_hulk * 3}{salute * 3}{flag}\n"
        )
        await ctx.send(row * 4)
        await ctx.message.delete(delay=2)

    @app_commands.command(name="blarg", description="BLARG")
    async def blarg(self, itx: AkandeItx) -> None:
        await itx.response.send_message("BLARG")

    @app_commands.command(name="brug-mode", description="Emojify text")
    @app_commands.describe(text="Text")
    async def brug_mode(self, itx: AkandeItx, text: str) -> None:
        await itx.response.send_message(emojify(text)[:2000])

    @app_commands.command(name="uwu", description="UwUfy text")
    @app_commands.describe(text="Text")
    async def uwu(self, itx: AkandeItx, text: str) -> None:
        await itx.response.send_message(uwuify(text)[:2000])

    @app_commands.command(name="u", description="Insult someone")
    @app_commands.describe(user="Who to insult")
    @app_commands.checks.cooldown(1, 5.0, key=lambda itx: itx.user.id)
    async def u(self, itx: AkandeItx, user: discord.Member) -> None:
        async with itx.client.acquire() as svc:
            insult = await svc.misc.fetch_random_insult()
        if insult is None:
            raise UserFacingError("There are no insults yet.")
        await itx.response.send_message(f"{user.display_name}{insult}")

    @app_commands.command(name="u-add", description="Add insults, don't fuck up")
    @app_commands.describe(insult="Appended directly after the target's display name")
    @checks.is_staff()
    async def u_add(self, itx: AkandeItx, insult: str) -> None:
        confirmed = await views.Confirm.prompt(
            itx, f"**Is this correct?**\n\n{itx.user.display_name}{insult}"
        )
        if not confirmed:
            return
        async with itx.client.acquire() as svc:
            await svc.misc.add_insult(insult)


async def setup(bot: Akande) -> None:
    await bot.add_cog(FunCog(bot))


async def teardown(bot: Akande) -> None:
    await bot.remove_cog("fun")
