from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from ._base import BaseCog

if TYPE_CHECKING:
    from core import Akande


class Events(BaseCog):
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        async with self.bot.acquire() as svc:
            await svc.users.create_if_missing(member.id, member.name[:25])


async def setup(bot: Akande):
    await bot.add_cog(Events(bot))


async def teardown(bot: Akande):
    await bot.remove_cog("Events")
