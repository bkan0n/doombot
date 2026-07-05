from __future__ import annotations

import typing

import discord
from discord import ui

from utilities.errors import UserFacingError
from utilities.views import send_error

if typing.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from core import AkandeItx


class _TagModalBase(ui.Modal):
    async def on_error(self, itx: AkandeItx, error: Exception) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        if isinstance(error, UserFacingError):
            await send_error(itx, str(error))
            return
        await super().on_error(itx, error)


class TagMakeModal(_TagModalBase, title="Create New Tag"):
    name = ui.TextInput(label="Name", required=True, min_length=1, max_length=100)
    content = ui.TextInput(
        label="Content",
        required=True,
        style=discord.TextStyle.long,
        min_length=1,
        max_length=2000,
    )

    def __init__(
        self, callback: Callable[[AkandeItx, str, str], Awaitable[None]]
    ) -> None:
        super().__init__()
        self._callback = callback

    async def on_submit(self, itx: AkandeItx) -> None:
        await self._callback(itx, self.name.value, self.content.value)


class TagEditModal(_TagModalBase, title="Edit Tag"):
    content = ui.TextInput(
        label="Tag Content",
        required=True,
        style=discord.TextStyle.long,
        min_length=1,
        max_length=2000,
    )

    def __init__(
        self, current: str, callback: Callable[[AkandeItx, str], Awaitable[None]]
    ) -> None:
        super().__init__()
        self.content.default = current
        self._callback = callback

    async def on_submit(self, itx: AkandeItx) -> None:
        await self._callback(itx, self.content.value)
