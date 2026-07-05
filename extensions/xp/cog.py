from __future__ import annotations

import asyncio
import io
import itertools
import typing

import discord
from discord import app_commands, ui

from utilities import formatting, transformers, views
from utilities.errors import UserFacingError

from .._base import BaseCog
from . import card

if typing.TYPE_CHECKING:
    from core import AkandeItx


class XPCog(BaseCog, name="xp", description="XP and rank card commands."):
    """XP"""

    @app_commands.command(name="rank", description="View a player's rank card")
    @app_commands.describe(user="Player (defaults to you)")
    async def rank(self, itx: AkandeItx, user: discord.Member | None = None) -> None:
        await itx.response.defer(ephemeral=True)
        member = user or itx.user
        async with itx.client.acquire() as svc:
            season = await svc.tournament.fetch_active_season_number()
            if season is None:
                raise UserFacingError("No active season exists.")
            data = await svc.xp.fetch_rank_card_data(member.id, season)
        if data is None:
            raise UserFacingError(
                f"{member.display_name} has no XP data for the current season."
            )
        avatar = io.BytesIO()
        await member.display_avatar.save(avatar)
        image = await asyncio.to_thread(card.render_card, avatar, data)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        buffer.seek(0)
        await itx.edit_original_response(
            attachments=[discord.File(buffer, filename="rank_card.png")]
        )

    @app_commands.command(
        name="xp-leaderboard", description="View the seasonal XP leaderboard"
    )
    @app_commands.describe(season="Season (defaults to the active season)")
    async def xp_leaderboard(
        self,
        itx: AkandeItx,
        season: app_commands.Transform[int, transformers.SeasonTransformer]
        | None = None,
    ) -> None:
        await itx.response.defer(ephemeral=True)
        async with itx.client.acquire() as svc:
            if season is None:
                season = await svc.tournament.fetch_active_season_number()
                if season is None:
                    raise UserFacingError("No active season exists.")
            entries = await svc.xp.fetch_xp_leaderboard(season)
        if not entries:
            await itx.edit_original_response(
                content="The XP leaderboard for this season is currently empty."
            )
            return
        pages: list[list[str | ui.Item]] = [
            [
                f"### XP Leaderboard — Season {season}",
                *(
                    f"**{formatting.make_ordinal(entry.rank)} — {entry.nickname}**"
                    f"\nXP: {entry.xp}"
                    for entry in chunk
                ),
            ]
            for chunk in itertools.batched(entries, 10)
        ]
        await views.Paginator(itx, pages).start()
