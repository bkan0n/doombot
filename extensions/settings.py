from __future__ import annotations

import typing

import discord
from discord import app_commands, ui

from utilities.errors import UserFacingError
from utilities.flags import Notification
from utilities.views import BaseLayoutView, send_error

from ._base import BaseCog

if typing.TYPE_CHECKING:
    from core import Akande, AkandeItx
    from database.services.users import UserAlias

_NOTIFICATION_OPTIONS = (
    (Notification.VERIFIED, "Record Verified", "DM when a mod verifies your record"),
    (Notification.DENIED, "Record Denied", "DM when a mod denies your record"),
    (
        Notification.SPECTACULAR,
        "Spectacular Records",
        "DM when your record reaches the top-records channel",
    ),
)
_NO_DMS_VALUE = "none"


class _NotificationsRow(ui.ActionRow["SettingsView"]):
    def __init__(self, flags: Notification) -> None:
        super().__init__()
        options = [
            discord.SelectOption(
                label=label,
                value=str(flag.value),
                description=description,
                default=flag in flags,
            )
            for flag, label, description in _NOTIFICATION_OPTIONS
        ]
        options.append(
            discord.SelectOption(
                label="No DMs",
                value=_NO_DMS_VALUE,
                description="Turn off all notifications",
                default=flags == Notification(0),
            )
        )
        self.notifications.options = options
        self.notifications.max_values = len(options)

    @ui.select(placeholder="Which DM notifications would you like?", min_values=0)
    async def notifications(
        self, itx: AkandeItx, select: ui.Select[SettingsView]
    ) -> None:
        assert self.view
        flags = Notification(0)
        if _NO_DMS_VALUE not in select.values:
            for value in select.values:
                flags |= Notification(int(value))
        async with itx.client.acquire() as svc:
            await svc.users.set_flags(itx.user.id, int(flags))
        await self.view.refresh(itx)


class _AliasRow(ui.ActionRow["SettingsView"]):
    def __init__(self, aliases: list[UserAlias], selected: str | None) -> None:
        super().__init__()
        if aliases:
            self.aliases.options = [
                discord.SelectOption(
                    label=alias.alias,
                    value=alias.alias,
                    emoji="✅" if alias.primary else None,
                    default=alias.alias == selected,
                )
                for alias in aliases
            ]
        else:
            self.aliases.options = [
                discord.SelectOption(label="No usernames yet", value=_NO_DMS_VALUE)
            ]
            self.aliases.disabled = True

    @ui.select(placeholder="Select a username…")
    async def aliases(self, itx: AkandeItx, select: ui.Select[SettingsView]) -> None:
        assert self.view
        self.view.selected_alias = select.values[0]
        await self.view.refresh(itx)


class _ButtonsRow(ui.ActionRow["SettingsView"]):
    @ui.button(label="Add Username", style=discord.ButtonStyle.grey)
    async def add_username(self, itx: AkandeItx, button: ui.Button) -> None:
        assert self.view
        await itx.response.send_modal(_AliasModal(self.view))

    @ui.button(label="Set Primary", style=discord.ButtonStyle.grey)
    async def set_primary(self, itx: AkandeItx, button: ui.Button) -> None:
        assert self.view
        alias = self.view.selected_alias
        if alias is None:
            raise UserFacingError("Select a username first.")
        async with itx.client.acquire() as svc:
            await svc.users.set_primary_alias(itx.user.id, alias)
        await self.view.refresh(itx)

    @ui.button(label="Remove Username", style=discord.ButtonStyle.grey)
    async def remove_username(self, itx: AkandeItx, button: ui.Button) -> None:
        assert self.view
        alias = self.view.selected_alias
        if alias is None:
            raise UserFacingError("Select a username first.")
        async with itx.client.acquire() as svc:
            await svc.users.remove_alias(itx.user.id, alias)
            remaining = await svc.users.fetch_aliases(itx.user.id)
            if remaining and not any(a.primary for a in remaining):
                await svc.users.set_primary_alias(itx.user.id, remaining[0].alias)
        self.view.selected_alias = None
        await self.view.refresh(itx)

    @ui.button(label="Change Nickname", style=discord.ButtonStyle.grey)
    async def change_nickname(self, itx: AkandeItx, button: ui.Button) -> None:
        assert self.view
        await itx.response.send_modal(_NicknameModal(self.view))


class _SettingsModal(ui.Modal):
    """Base modal: routes UserFacingError to the shared error card."""

    def __init__(self, view: SettingsView) -> None:
        super().__init__()
        self._view = view

    async def on_error(self, itx: AkandeItx, error: Exception) -> None:
        if isinstance(error, UserFacingError):
            await send_error(itx, str(error))
            return
        await super().on_error(itx, error)


class _AliasModal(_SettingsModal, title="Add Overwatch Username"):
    name = ui.TextInput(
        label="Overwatch username",
        placeholder="Spaces will be removed.",
        min_length=1,
        max_length=32,
    )

    async def on_submit(self, itx: AkandeItx) -> None:
        alias = self.name.value.replace(" ", "")
        async with itx.client.acquire() as svc:
            existing = await svc.users.fetch_aliases(itx.user.id)
            if any(a.alias == alias for a in existing):
                raise UserFacingError("That username is already added.")
            await svc.users.add_alias(itx.user.id, alias, primary=not existing)
        await self._view.refresh(itx)


class _NicknameModal(_SettingsModal, title="Change Nickname"):
    nickname = ui.TextInput(label="Nickname", min_length=1, max_length=25)

    async def on_submit(self, itx: AkandeItx) -> None:
        async with itx.client.acquire() as svc:
            await svc.users.set_nickname(itx.user.id, self.nickname.value)
        self._view.nickname = self.nickname.value
        await self._view.refresh(itx)


class SettingsView(BaseLayoutView):
    """Live settings editor: every change persists, then re-renders."""

    def __init__(
        self,
        itx: AkandeItx,
        *,
        nickname: str,
        flags: Notification,
        aliases: list[UserAlias],
    ) -> None:
        super().__init__(itx, timeout=300.0)
        self.nickname = nickname
        self.selected_alias: str | None = None
        self._build(flags, aliases)

    def _build(self, flags: Notification, aliases: list[UserAlias]) -> None:
        self.clear_items()
        notification_lines = [
            f"-# {'🔔' if flag in flags else '🔕'} {label}"
            for flag, label, _ in _NOTIFICATION_OPTIONS
        ]
        alias_lines = [
            f"-# {alias.alias}{' ✅' if alias.primary else ''}" for alias in aliases
        ] or ["-# No usernames set."]
        self.add_item(
            ui.Container(
                ui.TextDisplay(f"## Settings\n**Nickname:** {self.nickname}"),
                ui.TextDisplay(
                    "### DM Notifications\n" + "\n".join(notification_lines)
                ),
                _NotificationsRow(flags),
                ui.Separator(),
                ui.TextDisplay(
                    "### Overwatch Usernames\n"
                    "-# Helps mods verify your records.\n" + "\n".join(alias_lines)
                ),
                _AliasRow(aliases, self.selected_alias),
                _ButtonsRow(),
            )
        )

    async def refresh(self, itx: AkandeItx) -> None:
        async with itx.client.acquire() as svc:
            flags = await svc.users.fetch_flags(itx.user.id)
            aliases = await svc.users.fetch_aliases(itx.user.id)
            nickname = await svc.users.fetch_nickname(itx.user.id)
        self.nickname = nickname or self.nickname
        self._build(Notification(flags or 0), aliases)
        if itx.response.is_done():
            await self.itx.edit_original_response(view=self)
        else:
            await itx.response.edit_message(view=self)


class SettingsCog(BaseCog, name="settings", description="User settings."):
    """Settings"""

    @app_commands.command(
        name="settings",
        description="Set DM notifications, Overwatch usernames, and your nickname",
    )
    async def settings(self, itx: AkandeItx) -> None:
        await itx.response.defer(ephemeral=True)
        async with itx.client.acquire() as svc:
            await svc.users.create_if_missing(itx.user.id, itx.user.display_name)
            flags = await svc.users.fetch_flags(itx.user.id)
            aliases = await svc.users.fetch_aliases(itx.user.id)
            nickname = await svc.users.fetch_nickname(itx.user.id)
        view = SettingsView(
            itx,
            nickname=nickname or itx.user.display_name,
            flags=Notification(flags or 0),
            aliases=aliases,
        )
        await itx.edit_original_response(view=view)


async def setup(bot: Akande) -> None:
    await bot.add_cog(SettingsCog(bot))


async def teardown(bot: Akande) -> None:
    await bot.remove_cog("settings")
