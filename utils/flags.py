from __future__ import annotations

import contextlib
import logging
from enum import IntFlag, auto
from typing import TYPE_CHECKING, Callable

import discord
from discord import PartialEmoji, SelectOption, app_commands

if TYPE_CHECKING:
    import core


log = logging.getLogger(__name__)


class Flags(IntFlag):
    """Flag enum for notification settings."""

    NOTIFY_VERIFIED = auto()
    NOTIFY_NOT_VERIFIED = auto()
    NOTIFY_SPECTACULAR = auto()


ALL_FLAGS = [Flags.NOTIFY_VERIFIED, Flags.NOTIFY_NOT_VERIFIED, Flags.NOTIFY_SPECTACULAR]


def user_setup_required() -> Callable:
    """Check decorator to force users to set up their profile."""

    async def predicate(itx: core.DoomItx) -> bool:
        query = "SELECT flags FROM users WHERE user_id = $1"
        res = await itx.client.database.fetchval(query, itx.user.id)
        if res:
            return True
        view = UserSetupView(itx)
        await itx.response.send_message(
            "You must set up your profile before using this command.",
            view=view,
            ephemeral=True,
        )
        return False

    return app_commands.check(predicate)


notification_select_options = [
    discord.SelectOption(
        label="Record Verified",
        value="0",
        description="Notifications for when a mod verifies your record submission",
    ),
    discord.SelectOption(
        label="Record Denied",
        value="1",
        description="Notifications for when a mod denies your record submission",
    ),
    discord.SelectOption(
        label="Spectacular Records",
        value="2",
        description="Notifications for when your record reaches spectacular records",
    ),
    discord.SelectOption(label="No DMs", value="3", description="Turn off all notifications"),
]


class UserSetupView(discord.ui.View):
    """View for user to change their notification settings and Overwatch usernames."""

    def __init__(
        self,
        original_itx: core.DoomItx,
        notifications_select: NotificationsSelect | None = None,
        username_select: UsernamesSelect | None = None,
    ) -> None:
        super().__init__()
        self.flags: Flags = Flags(0)
        self.original_itx: core.DoomItx = original_itx
        self.notifications_select = notifications_select or NotificationsSelect()
        self.username_select: UsernamesSelect = username_select or UsernamesSelect()
        self.add_item(self.notifications_select)
        self.add_item(self.username_select)

    def build_display(self) -> str:
        """Create content for message."""

        init_string = (
            "You must set up your profile before using this command.\n"
            "-# Entering your in-game name(s) is optional but it helps our mods when verifying records.\n"
        )
        flag_string = self._build_notification_settings()
        name_string = self._build_overwatch_names()
        return init_string + flag_string + name_string

    def _build_notification_settings(self) -> str:
        flag_string = "### Notification Settings\nYou will receive notifications:\n"

        notifications = {
            Flags.NOTIFY_VERIFIED: "Upon record verification",
            Flags.NOTIFY_NOT_VERIFIED: "Upon record denial",
            Flags.NOTIFY_SPECTACULAR: "Upon reaching <#873572468982435860>",
        }

        for flag, description in notifications.items():
            if flag in self.flags:
                flag_string += f"-# {description}\n"

        if not any(flag in self.flags for flag in notifications):
            flag_string += "-# No DM notifications"

        return flag_string

    def _build_overwatch_names(self) -> str:
        name_string = "\n### Overwatch Names\n"

        if not self.username_select.disabled:
            primary_name = self._get_primary_name()

            for i, name in enumerate(self.username_select.options):
                name_string += f"-# {i + 1}. {name.value}"
                if primary_name and primary_name == name.value:
                    name_string += " (Primary)"
                name_string += "\n"
        else:
            default_name = self.original_itx.user.global_name
            name_string += f"-# No names set. Defaulting to Discord username\n-# - {default_name}"

        return name_string

    def _get_primary_name(self) -> str | None:
        _filter = filter(lambda x: x.emoji is not None, self.username_select.options)
        with contextlib.suppress(StopIteration):
            return next(_filter).value
        return None

    @discord.ui.button(label="Add Username", style=discord.ButtonStyle.grey, row=2)
    async def add_username(self, itx: core.DoomItx, button: discord.ui.Button) -> None:
        """Add username to SelectMenu."""
        modal = AliasModal()
        await itx.response.send_modal(modal)
        await modal.wait()
        if modal.value is None:
            return
        if self.username_select.disabled:
            self.username_select.options = []
            self.username_select.disabled = False
        self.username_select.add_option(label=modal.value, value=modal.value)
        await self.original_itx.edit_original_response(content=self.build_display(), view=self)

    @discord.ui.button(label="Edit Selected Name", style=discord.ButtonStyle.grey, row=3)
    async def edit_username(self, itx: core.DoomItx, button: discord.ui.Button) -> None:
        """Edit the selected username."""
        if self.username_select.value is None:
            await itx.response.send_message("You must select a name to edit.")
            return
        old_value = self.username_select.value
        modal = AliasModal(default=old_value)
        await itx.response.send_modal(modal)
        await modal.wait()
        if modal.value is None:
            return
        for i, n in enumerate(self.username_select.options):
            if n.value == old_value:
                self.username_select.options[i].label = modal.value
                self.username_select.options[i].value = modal.value
                break
        await self.original_itx.edit_original_response(content=self.build_display(), view=self)

    @discord.ui.button(label="Remove Selected Name", style=discord.ButtonStyle.grey, row=2)
    async def remove_username(self, itx: core.DoomItx, button: discord.ui.Button) -> None:
        """Remove selected username from SelectMenu."""
        if self.username_select.value is None:
            await itx.response.send_message("You must select a name to remove.")
            return
        await itx.response.defer(ephemeral=True)
        if self.username_select.disabled:
            return
        if len(self.username_select.options) == 1:
            self.username_select.options = []
            self.username_select.disabled = True
            self.username_select.add_option(label="null", value="null")
        else:
            for i, name in enumerate(self.username_select.options):
                if name.value == self.username_select.value:
                    del self.username_select.options[i]
                    break
        await self.original_itx.edit_original_response(content=self.build_display(), view=self)

    @discord.ui.button(label="Set Selected As Primary", style=discord.ButtonStyle.grey, row=3)
    async def set_primary_username(self, itx: core.DoomItx, button: discord.ui.Button) -> None:
        """Set selected username as primary."""
        await itx.response.defer(ephemeral=True)
        for option in self.username_select.options:
            if option.value == self.username_select.value:
                option.emoji = PartialEmoji.from_str("\U00002705")
            else:
                option.emoji = None
        await self.original_itx.edit_original_response(content=self.build_display(), view=self)

    @discord.ui.button(label="Submit Changes", style=discord.ButtonStyle.green, row=4)
    async def submit(self, itx: core.DoomItx, _: discord.ui.Button) -> None:
        """Submit changes made by user."""
        log.info("1")
        if not self.username_select.disabled and not self._get_primary_name():
            await itx.response.send_message("You must select a primary name to continue.", ephemeral=True, view=self)
            return
        log.info("2")
        await itx.response.defer(ephemeral=True)
        self.stop()
        query = "SELECT flags FROM users WHERE user_id=$1"
        if await itx.client.database.fetchval(query, itx.user.id):
            log.info("3")
            await itx.edit_original_response(
                content="You have already completed this task elsewhere. You can close this.", view=None
            )
            return
        log.info("4")
        query = "UPDATE users SET flags = $2 WHERE user_id = $1"
        await itx.client.database.execute(query, itx.user.id, int(self.flags))
        log.info("5")
        if not self.username_select.disabled:
            log.info("6")
            query = 'INSERT INTO alias (user_id, alias, "primary") VALUES ($1, $2, $3)'
            data = [(itx.user.id, x.value, x.emoji is not None) for x in self.username_select.options]
            await itx.client.database.executemany(query, data)
        else:
            log.info("7")
            query = 'INSERT INTO alias (user_id, alias, "primary") VALUES ($1, $2, TRUE)'
            await itx.client.database.execute(query, itx.user.id, itx.user.global_name)
        log.info("8")
        await self.original_itx.edit_original_response(
            content="# Confirmed.\nYou may use any command now. To make more changes, use the `/settings` command.",
            view=None,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, row=4)
    async def cancel(self, itx: core.DoomItx, _: discord.ui.Button) -> None:
        """Cancel entire transaction."""
        self.stop()
        await itx.response.defer(ephemeral=True)
        await self.original_itx.delete_original_response()

    async def on_timeout(self) -> None:
        """Remove the original message upon timeout."""
        with contextlib.suppress(discord.HTTPException):
            await self.original_itx.delete_original_response()


class AliasModal(discord.ui.Modal):
    """Discord Modal to input Overwatch username."""

    def __init__(self, default: str | None = None) -> None:
        super().__init__(title="Overwatch Usernames", timeout=360)
        self.value: str | None = None
        self.name = discord.ui.TextInput(
            label="Overwatch username",
            style=discord.TextStyle.short,
            placeholder="Spaces will be removed.",
            default=default,
        )
        self.add_item(self.name)

    async def on_submit(self, itx: core.DoomItx) -> None:
        """Upon user submission of AliasModal, strip whitespace from user input."""
        await itx.response.defer(ephemeral=True)
        self.value = self.name.value.replace(" ", "")


class UsernamesSelect(discord.ui.Select[UserSetupView]):
    """SelectMenu that contains user Overwatch usernames."""

    def __init__(self, options: list[SelectOption] | None = None) -> None:
        super().__init__(
            options=options or [SelectOption(label="Enter a name to begin.", value="null")],
            row=1,
            placeholder="Selected Name",
            disabled=not bool(options),
        )
        self.value: str | None = None

    async def callback(self, itx: core.DoomItx) -> None:
        """Set selected values as default."""
        await itx.response.defer(ephemeral=True)
        self.value = self.values[0]
        for option in self.options:
            option.default = option.value == self.value


class NotificationsSelect(discord.ui.Select[UserSetupView]):
    """SelectMenu that sets notification settings."""

    view: UserSetupView

    def __init__(self, options: list[SelectOption] | None = None) -> None:
        super().__init__(
            options=options or notification_select_options,
            min_values=0,
            max_values=len(notification_select_options),
            placeholder="Which DM notifications would you like to receive?",
            row=0,
        )

    async def callback(self, itx: core.DoomItx) -> None:
        """SelectMenu that enables/disables notifications."""

        await itx.response.defer(ephemeral=True)

        flag_mapping = {
            "0": Flags.NOTIFY_VERIFIED,
            "1": Flags.NOTIFY_NOT_VERIFIED,
            "2": Flags.NOTIFY_SPECTACULAR,
        }

        for value, flag in flag_mapping.items():
            if value in self.values:
                self.view.flags |= flag
            else:
                self.view.flags &= ~flag

        if len(self.values) == 0 or "3" in self.values:
            self.view.flags = Flags(0)

        for option in self.options:
            option.default = option.value == "3" if "3" in self.values else option.value in self.values

        await self.view.original_itx.edit_original_response(content=self.view.build_display(), view=self.view)
