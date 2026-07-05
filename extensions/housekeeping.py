from typing import Literal

import discord
from discord.ext import commands

from core import Akande, AkandeCtx

from ._base import BaseCog


class HousekeepingCog(BaseCog):
    @commands.command()
    @commands.guild_only()
    @commands.is_owner()
    async def sync(
        self,
        ctx: AkandeCtx,
        guilds: commands.Greedy[discord.Object],
        spec: Literal["~", "*", "^", "$"] | None = None,
    ) -> None:
        """Sync commands to Discord.

        ?sync -> global sync
        ?sync ~ -> sync current guild
        ?sync * -> copies all global app commands to the current guild and syncs
        ?sync ^ -> clears all commands from the current
                        guild target and syncs (removes guild commands)
        ?sync id_1 id_2 -> syncs guilds with id 1 and 2
        >sync $ -> Clears global commands
        """
        if not guilds:
            if spec == "~":
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
            elif spec == "*":
                assert ctx.guild
                ctx.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
            elif spec == "^":
                ctx.bot.tree.clear_commands(guild=ctx.guild)
                await ctx.bot.tree.sync(guild=ctx.guild)
                synced = []
            elif spec == "$":
                ctx.bot.tree.clear_commands(guild=None)
                await ctx.bot.tree.sync()
                synced = []
            else:
                synced = await ctx.bot.tree.sync()

            await ctx.send(
                f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild.'}"
            )
            return

    @commands.command(name="migrate-flags")
    @commands.guild_only()
    @commands.is_owner()
    async def migrate_flags(self, ctx: AkandeCtx) -> None:
        """One-time backfill: users.flags from the legacy alertable bool."""
        async with self.bot.acquire() as svc:
            count = await svc.users.backfill_flags_from_alertable()
        await ctx.send(f"Backfilled flags for {count} user(s).")


async def setup(bot: Akande) -> None:
    await bot.add_cog(HousekeepingCog(bot))


async def teardown(bot: Akande) -> None:
    await bot.remove_cog("HousekeepingCog")
