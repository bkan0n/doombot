from __future__ import annotations

import typing

import discord
from discord import ui
from discord.ext import commands

from utilities.errors import UserFacingError
from utilities.views import toggle_role

from ._base import BaseCog

if typing.TYPE_CHECKING:
    from collections.abc import Sequence

    from core import Akande, AkandeCtx, AkandeItx
    from database.services.misc import ColorRole


# custom_ids throughout are identical to the old bot so its posted panels
# keep dispatching after the port.
class _PronounButtons(ui.ActionRow["RolesPanel"]):
    @ui.button(
        label="They/Them", style=discord.ButtonStyle.grey, custom_id="they_pronoun"
    )
    async def they_them(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await toggle_role(itx, itx.client.config.roles.pronouns.they_them)

    @ui.button(label="She/Her", style=discord.ButtonStyle.grey, custom_id="she_pronoun")
    async def she_her(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await toggle_role(itx, itx.client.config.roles.pronouns.she_her)

    @ui.button(label="He/Him", style=discord.ButtonStyle.grey, custom_id="he_pronoun")
    async def he_him(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await toggle_role(itx, itx.client.config.roles.pronouns.he_him)


class _PingButtons(ui.ActionRow["RolesPanel"]):
    @ui.button(
        label="Announcements",
        style=discord.ButtonStyle.blurple,
        custom_id="announcements",
    )
    async def announcements(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await toggle_role(itx, itx.client.config.roles.pings.announcements)

    @ui.button(
        label="Movie Night", style=discord.ButtonStyle.grey, custom_id="movie_night"
    )
    async def movie_night(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await toggle_role(itx, itx.client.config.roles.pings.movie_night)

    @ui.button(
        label="Game Night", style=discord.ButtonStyle.grey, custom_id="game_night"
    )
    async def game_night(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await toggle_role(itx, itx.client.config.roles.pings.game_night)


class _SleepPingButtons(ui.ActionRow["RolesPanel"]):
    @ui.button(
        label="EU Sleep Ping", style=discord.ButtonStyle.grey, custom_id="eu_sleep_ping"
    )
    async def eu(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await toggle_role(itx, itx.client.config.roles.pings.eu_sleep)

    @ui.button(
        label="NA Sleep Ping", style=discord.ButtonStyle.grey, custom_id="na_sleep_ping"
    )
    async def na(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await toggle_role(itx, itx.client.config.roles.pings.na_sleep)

    @ui.button(
        label="Asia Sleep Ping",
        style=discord.ButtonStyle.grey,
        custom_id="asia_sleep_ping",
    )
    async def asia(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await toggle_role(itx, itx.client.config.roles.pings.asia_sleep)

    @ui.button(
        label="OCE Sleep Ping",
        style=discord.ButtonStyle.grey,
        custom_id="oce_sleep_ping",
    )
    async def oce(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await toggle_role(itx, itx.client.config.roles.pings.oce_sleep)


class _ColorSelect(ui.Select["RolesPanel"]):
    def __init__(self, colors: Sequence[ColorRole] = ()) -> None:
        options = [
            discord.SelectOption(
                label="None", value="None", description="Remove your color role."
            )
        ]
        options.extend(
            discord.SelectOption(
                label=color.label, value=str(color.role_id), emoji=color.emoji
            )
            for color in colors
        )
        super().__init__(
            custom_id="colors", placeholder="Pick a name color…", options=options
        )

    async def callback(self, itx: AkandeItx) -> None:
        await itx.response.defer(ephemeral=True)
        assert itx.guild and isinstance(itx.user, discord.Member)
        # The registered options list can be stale (or empty, on the
        # startup-registered copy); the database is the source of truth.
        async with itx.client.acquire() as svc:
            colors = await svc.misc.fetch_color_roles()
        owned = [
            role
            for color in colors
            if (role := itx.guild.get_role(color.role_id)) and role in itx.user.roles
        ]
        await itx.user.remove_roles(*owned)
        if self.values[0] == "None":
            await itx.followup.send("Color role removed.", ephemeral=True)
            return
        role = itx.guild.get_role(int(self.values[0]))
        if role is None:
            raise UserFacingError("That role no longer exists.")
        await itx.user.add_roles(role)
        await itx.followup.send(f"Color set to **{role.name}**.", ephemeral=True)


class RolesPanel(ui.LayoutView):
    """Persistent self-assign role panel: pronouns, notification pings, name color.

    Construct without colors to reconnect callbacks on startup; pass the
    color roles when actually posting the panel so the select has options.
    """

    def __init__(self, colors: Sequence[ColorRole] = ()) -> None:
        super().__init__(timeout=None)
        self.add_item(
            ui.Container(
                ui.TextDisplay("## Server Roles"),
                ui.TextDisplay("### Pronouns"),
                _PronounButtons(),
                ui.Separator(),
                ui.TextDisplay("### Notification Pings"),
                _PingButtons(),
                _SleepPingButtons(),
                ui.Separator(),
                ui.TextDisplay("### Name Color"),
                ui.ActionRow(_ColorSelect(colors)),
            )
        )

    async def on_error(
        self, itx: discord.Interaction, error: Exception, item: ui.Item
    ) -> None:
        # Every callback defers first, so a followup is always deliverable.
        if isinstance(error, UserFacingError):
            await itx.followup.send(str(error), ephemeral=True)
            return
        await super().on_error(itx, error, item)


class RolesCog(BaseCog, name="roles", description="Self-assign role panel."):
    @commands.command(name="roles-panel")
    @commands.guild_only()
    @commands.is_owner()
    async def post_roles_panel(self, ctx: AkandeCtx) -> None:
        """Post the persistent self-assign role panel in this channel."""
        async with self.bot.acquire() as svc:
            colors = await svc.misc.fetch_color_roles()
        await ctx.send(view=RolesPanel(colors))

    async def cog_load(self) -> None:
        self.bot.add_view(RolesPanel())


async def setup(bot: Akande) -> None:
    await bot.add_cog(RolesCog(bot))


async def teardown(bot: Akande) -> None:
    await bot.remove_cog("roles")
