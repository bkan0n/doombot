from __future__ import annotations

import typing

from discord import app_commands

from utilities import checks, formatting, transformers, views
from utilities.errors import UserFacingError

from ._base import BaseCog

if typing.TYPE_CHECKING:
    from core import Akande, AkandeItx


class ModCog(BaseCog, name="mod", description="Moderator commands."):
    """Mod"""

    _mod = app_commands.Group(name="mod", description="Moderator commands")

    async def interaction_check(self, itx: AkandeItx) -> bool:
        return checks.ensure_staff(itx)

    @_mod.command(
        name="remove-record",
        description="Remove a user's latest record for a level",
    )
    @app_commands.describe(user="Record owner", map_code="Map code", level="Level name")
    async def remove_record(
        self,
        itx: AkandeItx,
        user: app_commands.Transform[int, transformers.UserTransformer],
        map_code: app_commands.Transform[str, transformers.CodeTransformer],
        level: app_commands.Transform[str, transformers.MapLevelTransformer],
    ) -> None:
        await itx.response.defer(ephemeral=True)
        async with itx.client.acquire() as svc:
            record = await svc.records.fetch_latest_record(user, map_code, level)
        if record is None:
            raise UserFacingError("No records found for that user/map/level.")
        confirmed = await views.Confirm.prompt(
            itx,
            "### Delete this record?",
            f"**Name:** {record.nickname}\n"
            f"**Code:** {record.map_code}\n"
            f"**Level:** {record.level_name}\n"
            f"**Record:** {formatting.pretty_record(record.record)}",
            defer_on_confirm=True,
        )
        if not confirmed:
            return
        async with itx.client.acquire() as svc:
            await svc.records.delete_latest_record(user, map_code, level)
        await itx.edit_original_response(view=views.Card(["🗑️ Record deleted."]))

    @_mod.command(name="change-name", description="Change a user's display nickname")
    @app_commands.describe(user="User to rename", nickname="New nickname")
    async def change_name(
        self,
        itx: AkandeItx,
        user: app_commands.Transform[int, transformers.UserTransformer],
        nickname: app_commands.Range[str, 1, 25],
    ) -> None:
        await itx.response.defer(ephemeral=True)
        async with itx.client.acquire() as svc:
            old = await svc.users.fetch_nickname(user)
            if old is None:
                raise UserFacingError("User not found.")
            await svc.users.set_nickname(user, nickname)
        await itx.edit_original_response(
            view=views.Card([f"Changed **{old}** ({user}) to **{nickname}**."])
        )


async def setup(bot: Akande) -> None:
    await bot.add_cog(ModCog(bot))


async def teardown(bot: Akande) -> None:
    await bot.remove_cog("mod")
