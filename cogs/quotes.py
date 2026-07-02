from __future__ import annotations

import typing

import discord
from discord import app_commands
from discord.ext import commands

import utils

if typing.TYPE_CHECKING:
    import core
    from core import DoomCtx, DoomItx


class Quotes(commands.Cog):
    def __init__(self, bot: core.Doom):
        self.bot = bot
        self.bot.tree.add_command(
            app_commands.ContextMenu(
                name="Add quote",
                callback=self.add_quote,
                guild_ids=[utils.GUILD_ID],
            )
        )

    @commands.hybrid_command(name="quote", description="Get a quote.")
    async def quote(self, ctx: DoomCtx, id: int | None = None):
        if id is None:
            query = "SELECT id, username, content FROM quotes ORDER BY RANDOM() LIMIT 1;"
            res = await ctx.bot.pool.fetchrow(query)
        else:
            query = "SELECT * FROM quotes WHERE id = $1"
            res = await ctx.bot.pool.fetchrow(query, id)

        if not res:
            await ctx.send("There is no quote with this index!")
            return

        await ctx.send(f"Quote #{res['id']}: {res['username']}:\n{res['content']}")

    async def add_quote(self, itx: DoomItx, message: discord.Message):
        query = "INSERT INTO quotes (username, content) VALUES ($1, $2) RETURNING id;"
        res = await itx.client.pool.fetchval(
            query,
            message.author.display_name,
            message.content,
        )
        await itx.response.send_message(f"Added quote {res}")