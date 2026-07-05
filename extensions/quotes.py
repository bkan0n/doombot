from __future__ import annotations

import itertools
import typing

import discord
from discord import app_commands, ui

from utilities import views
from utilities.errors import UserFacingError

from ._base import BaseCog

if typing.TYPE_CHECKING:
    from core import Akande, AkandeItx


class QuotesCog(BaseCog, name="quotes", description="Quote commands."):
    """Quotes"""

    def __init__(self, bot: Akande) -> None:
        super().__init__(bot)
        self._add_quote_menu = app_commands.ContextMenu(
            name="Add quote", callback=self._add_quote_callback
        )

    async def cog_load(self) -> None:
        self.bot.tree.add_command(self._add_quote_menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(
            self._add_quote_menu.name, type=self._add_quote_menu.type
        )

    async def _add_quote_callback(
        self, itx: AkandeItx, message: discord.Message
    ) -> None:
        if not message.content:
            raise UserFacingError("That message has no text content to quote.")
        async with itx.client.acquire() as svc:
            quote_id = await svc.misc.add_quote(
                message.author.display_name, message.content
            )
        await itx.response.send_message(f"Added quote #{quote_id}.")

    @app_commands.command(name="quote", description="One of many quotes")
    @app_commands.describe(quote_id="ID of the quote (random when omitted)")
    @app_commands.rename(quote_id="id")
    async def quote(self, itx: AkandeItx, quote_id: int | None = None) -> None:
        async with itx.client.acquire() as svc:
            if quote_id is None:
                quote = await svc.misc.fetch_random_quote()
            else:
                quote = await svc.misc.fetch_quote(quote_id)
        if quote is None:
            raise UserFacingError("There is no quote with this ID.")
        await itx.response.send_message(
            f"Quote #{quote.id}: {quote.username}:\n{quote.content}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(
        name="quote-list", description="List of quotes available with /quote"
    )
    async def quote_list(self, itx: AkandeItx) -> None:
        await itx.response.defer(ephemeral=True)
        async with itx.client.acquire() as svc:
            quotes = await svc.misc.fetch_quotes()
        if not quotes:
            raise UserFacingError("There are no quotes yet.")
        escape = discord.utils.escape_markdown
        pages: list[list[str | ui.Item]] = [
            [
                "### Quote List",
                *(
                    f"**{quote.id}** — {escape(quote.username)}\n{quote.content}"
                    for quote in chunk
                ),
            ]
            for chunk in itertools.batched(quotes, 10)
        ]
        await views.Paginator(itx, pages).start()


async def setup(bot: Akande) -> None:
    await bot.add_cog(QuotesCog(bot))


async def teardown(bot: Akande) -> None:
    await bot.remove_cog("quotes")
