from __future__ import annotations

import typing

import discord
from discord import app_commands
from discord.ext import commands

import utils
from views import Paginator

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

    @app_commands.command(name="quote", description="One of many quotes.")
    @app_commands.describe(id="ID of the quote")
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID))
    async def quote(self, itx: DoomItx, id: int | None = None):
        if id is None:
            query = "SELECT id, username, content FROM quotes ORDER BY RANDOM() LIMIT 1;"
            res = await itx.client.pool.fetchrow(query)
        else:
            query = "SELECT * FROM quotes WHERE id = $1"
            res = await itx.client.pool.fetchrow(query, id)

        if not res:
            await itx.response.send_message("There is no quote with this index!")
            return

        await itx.response.send_message(f"Quote #{res['id']}: {res['username']}:\n{res['content']}")

    @app_commands.command(name="quotelist", description="List of quotes available with /quote [id]")
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID))
    async def quotelist(self, itx: DoomItx):
        await itx.response.defer(ephemeral=True)
        query = "SELECT * FROM quotes ORDER BY id;"
        rows = await itx.client.pool.fetch(query)
        es = discord.utils.escape_markdown
        row_strings = [f"**{row['id']}** - {es(row['username'])}\n{row['content']}\n" for row in rows]
        chunks = discord.utils.as_chunks(row_strings, 10)
        embeds = [discord.Embed(title=f"Quote List", description="\n".join(chunk)) for chunk in chunks]
        await Paginator(embeds, itx.user).start(itx)


    async def add_quote(self, itx: DoomItx, message: discord.Message):
        query = "INSERT INTO quotes (username, content) VALUES ($1, $2) RETURNING id;"
        res = await itx.client.pool.fetchval(
            query,
            message.author.display_name,
            message.content,
        )
        await itx.response.send_message(f"Added quote {res}")

async def setup(bot: core.Doom):
    await bot.add_cog(Quotes(bot))