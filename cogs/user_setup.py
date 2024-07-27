from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from utils import utils
from utils.flags import ALL_FLAGS, Flags, NotificationsSelect, UsernamesSelect, UserSetupView, notification_select_options

if TYPE_CHECKING:
    import core
    from database import Database, DotRecord


class UserSetup(commands.Cog):
    """User setup commands."""

    def __init__(self, bot: core.Doom) -> None:
        self.bot = bot

    @app_commands.command(name="settings")
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID))
    async def settings(self, itx: core.DoomItx) -> None:
        """Set notifications and Overwatch usernames for user."""
        await itx.response.defer(ephemeral=True)

        alias_rows = await self._fetch_aliases(itx.client.database, itx.user.id)
        username_options = self._build_alias_options(alias_rows)
        username_select = UsernamesSelect(username_options)

        notifications_flag = await self._fetch_notification_settings(itx.client.database, itx.user.id)
        notification_options = self._build_notification_options(notifications_flag, deepcopy(notification_select_options))
        notifications_select = NotificationsSelect(notification_options)

        view = UserSetupView(itx, notifications_select, username_select)
        await itx.edit_original_response(view=view)

    @staticmethod
    async def _fetch_aliases(con: Database, user_id: int) -> list[DotRecord]:
        query = "SELECT * FROM alias WHERE user_id=$1"
        return await con.fetch(query, user_id)

    @staticmethod
    def _build_alias_options(rows: list[DotRecord]) -> list[discord.SelectOption]:
        emoji = discord.PartialEmoji.from_str("\U00002705")
        return [
            discord.SelectOption(label=row["alias"], value=row["alias"], emoji=emoji if row["primary"] else None)
            for row in rows
        ]

    @staticmethod
    async def _fetch_notification_settings(con: Database, user_id: int) -> int:
        query = "SELECT flags FROM users WHERE user_id=$1"
        return await con.fetchval(query, user_id)

    @staticmethod
    def _build_notification_options(value: int, options: list[discord.SelectOption]) -> list[discord.SelectOption]:
        user_flag = Flags(value)
        for i, flag in enumerate(ALL_FLAGS):
            options[i].default = flag in user_flag

        return options


async def setup(bot: core.Doom) -> None:
    """Add extension to bot."""
    await bot.add_cog(UserSetup(bot))
