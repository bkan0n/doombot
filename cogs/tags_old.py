from __future__ import annotations

import typing

import discord
from discord import app_commands
from discord.ext import commands

import cogs
import utils
import views

if typing.TYPE_CHECKING:
    import core
    from core import DoomItx


class Tags(discord.ext.commands.GroupCog, group_name=utils.tags["name"]):
    """Tags"""

    @app_commands.command(**utils.view_tag)
    @app_commands.describe(**utils.view_tag_args)
    @app_commands.autocomplete(name=cogs.tags_autocomplete)
    @app_commands.checks.cooldown(3, 30, key=lambda i: (i.guild_id, i.user.id))
    async def view(
        self,
        itx: DoomItx,
        name: str,
    ) -> None:
        await itx.response.defer()
        if name not in itx.client.tag_cache:
            fuzzed_options = utils.fuzz_multiple(name, itx.client.tag_cache)
            fuzz_desc = [f"{utils.NUMBER_EMOJI[i + 1]} - {x}\n" for i, x in enumerate(fuzzed_options)]

            embed = utils.DoomEmbed(
                title="Tags",
                description=(f"Couldn't find `{name}`. Did you mean:\n" + "".join(fuzz_desc)),
            )
            view = views.TagFuzzView(itx, fuzzed_options)
            await itx.edit_original_response(embed=embed, view=view)
            await view.wait()

            return
        query = "SELECT * FROM tags WHERE name=$1;"
        tag = await itx.client.database.fetchrow(
            query,
            name,
        )

        value = discord.utils.escape_mentions(tag["value"]).replace(r"\n", "\n")
        await itx.edit_original_response(content=f"**{tag['name']}**\n\n{value}")

    @app_commands.command(**utils.create_tag)
    async def create(self, itx: DoomItx):
        if (
            itx.guild.get_role(959433020664868907) not in itx.user.roles
            and itx.guild.get_role(utils.STAFF) not in itx.user.roles
        ):
            raise utils.NoPermissionsError
        modal = views.TagCreate()
        await itx.response.send_modal(modal)


async def setup(bot: core.Doom):
    # await bot.add_cog(
    #     Tags(bot),
    #     guilds=[
    #         discord.Object(id=utils.GUILD_ID),
    #         discord.Object(id=195387617972322306),
    #     ],
    # )
    ...
