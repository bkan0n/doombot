from __future__ import annotations

import itertools
import typing

import discord
from discord import app_commands

from utilities import transformers, views
from utilities.errors import UserFacingError

from .._base import BaseCog
from . import views as map_views

if typing.TYPE_CHECKING:
    from core import AkandeItx


class MapsCog(BaseCog, name="maps", description="Map related commands."):
    """Maps"""

    _map_maker = app_commands.Group(
        name="map-maker",
        description="Map maker only commands",
    )

    _level = app_commands.Group(
        name="level",
        description="Edit levels",
        parent=_map_maker,
    )

    _creator = app_commands.Group(
        name="creator",
        description="Edit creators",
        parent=_map_maker,
    )

    _edit = app_commands.Group(
        name="edit",
        description="Map code, map name, etc.",
        parent=_map_maker,
    )

    @_edit.command(
        name="code",
        description="Edit your map code.",
    )
    @app_commands.describe(
        new_map_code="New Overwatch Workshop code",
        old_map_code="Current Overwatch Workshop code",
    )
    async def edit_map_code(
        self,
        itx: AkandeItx,
        old_map_code: app_commands.Transform[str, transformers.CodeTransformer],
        new_map_code: app_commands.Transform[
            str, transformers.CodeSubmissionTransformer
        ],
    ) -> None:

        confirmed = await views.Confirm.prompt(
            itx,
            f"Are you sure you want to change your map code from {old_map_code} to {new_map_code}?",
        )
        if not confirmed:
            return

        async with itx.client.acquire() as svc:
            await svc.maps.set_map_code(old_map_code, new_map_code)

    @_creator.command(
        name="remove",
        description="Remove a creator from your map",
    )
    @app_commands.describe(
        map_code="Overwatch Workshop Code", creator="Creator's Discord name"
    )
    async def remove_creator(
        self,
        itx: AkandeItx,
        map_code: app_commands.Transform[str, transformers.CodeTransformer],
        creator: app_commands.Transform[int, transformers.UserTransformer],
    ) -> None:
        assert itx.guild
        member = itx.guild.get_member(creator)
        member_name = member.name if member else "Unknown"
        confirmed = await views.Confirm.prompt(
            itx,
            f"Are you sure you want to remove {member_name} ({creator}) from {map_code}?",
        )
        if not confirmed:
            return

        async with itx.client.acquire() as svc:
            map_data = await svc.maps.fetch_map(map_code=map_code)
            if not map_data:
                raise UserFacingError("There was an error retrieving the map data.")

            if itx.user.id not in map_data.creators_ids:
                raise UserFacingError("You are not a creator of this map.")

            if creator not in map_data.creators_ids:
                raise UserFacingError("That user is not a creator of this map.")

            await svc.maps.remove_creator(map_code=map_code, user_id=creator)

    @_creator.command(name="add", description="Add a creator to your map")
    @app_commands.describe(
        map_code="Overwatch Workshop Code", creator="Creator's Discord name"
    )
    async def add_creator(
        self,
        itx: AkandeItx,
        map_code: app_commands.Transform[str, transformers.CodeTransformer],
        creator: app_commands.Transform[int, transformers.UserTransformer],
    ) -> None:
        assert itx.guild
        member = itx.guild.get_member(creator)
        member_name = member.name if member else "Unknown"
        confirmed = await views.Confirm.prompt(
            itx,
            f"Are you sure you want to add {member_name} (_{creator}_) as a creator for **{map_code}**?",
        )
        if not confirmed:
            return

        async with itx.client.acquire() as svc:
            map_data = await svc.maps.fetch_map(map_code=map_code)
            if not map_data:
                raise UserFacingError("There was an error retrieving the map data.")

            if itx.user.id not in map_data.creators_ids:
                raise UserFacingError("You are not a creator of this map.")

            if creator in map_data.creators_ids:
                raise UserFacingError("That user is already a creator of this map.")

            await svc.maps.add_creator(map_code=map_code, user_id=creator)

    @_level.command(name="add", description="Add a level to your map")
    @app_commands.describe(
        map_code="Overwatch Workshop Code", new_level_name="New level name"
    )
    async def add_level_name(
        self,
        itx: AkandeItx,
        map_code: app_commands.Transform[str, transformers.CodeTransformer],
        new_level_name: str,
    ) -> None:
        await self._check_valid_arguments(itx, map_code, new_level_name)

        confirmed = await views.Confirm.prompt(
            itx,
            f"Is this correct?\nAdding level: {new_level_name} for **{map_code}**?",
        )
        if not confirmed:
            return

        async with itx.client.acquire() as svc:
            await svc.maps.add_levels(map_code, [new_level_name])

    @_level.command(name="remove", description="Remove a level from your map")
    @app_commands.describe(map_code="Overwatch Workshop Code", level_name="Level name")
    async def delete_level_names(
        self,
        itx: AkandeItx,
        map_code: app_commands.Transform[str, transformers.CodeTransformer],
        level_name: app_commands.Transform[str, transformers.MapLevelTransformer],
    ) -> None:
        await self._check_valid_arguments(itx, map_code)

        confirmed = await views.Confirm.prompt(
            itx,
            f"Is this correct?\nDeleting level: {level_name} for **{map_code}**?",
        )
        if not confirmed:
            return
        async with itx.client.acquire() as svc:
            await svc.maps.delete_level(map_code, level_name)

    @staticmethod
    async def _check_valid_arguments(
        itx: AkandeItx, map_code: str, new_level_name: str | None = None
    ) -> None:
        async with itx.client.acquire() as svc:
            map_data = await svc.maps.fetch_map(map_code=map_code)

        if not map_data:
            raise UserFacingError("That map code does not exist.")
        if itx.user.id not in map_data.creators_ids:
            raise UserFacingError("You are not a creator of this map.")
        if new_level_name and new_level_name in map_data.levels:
            raise UserFacingError("That level already exists.")

    @_level.command(name="rename", description="Rename a level in your map")
    @app_commands.describe(
        map_code="Overwatch Workshop Code",
        level_name="Level name",
        new_level_name="New level name",
    )
    async def edit_level_names(
        self,
        itx: AkandeItx,
        map_code: app_commands.Transform[str, transformers.CodeTransformer],
        level_name: app_commands.Transform[str, transformers.MapLevelTransformer],
        new_level_name: str,
    ) -> None:
        await self._check_valid_arguments(itx, map_code)

        confirmed = await views.Confirm.prompt(
            itx,
            f"Is this correct?\nRenaming level: {level_name} to {new_level_name} for **{map_code}**?",
        )

        if not confirmed:
            return

        async with itx.client.acquire() as svc:
            await svc.maps.rename_level(map_code, level_name, new_level_name)

    @app_commands.command(name="submit-map", description="Submit a new map to the bot")
    @app_commands.describe(
        map_code="Overwatch Workshop Code",
        map_name="Overwatch map name",
    )
    async def submit_map(
        self,
        itx: AkandeItx,
        map_code: app_commands.Transform[str, transformers.CodeSubmissionTransformer],
        map_name: app_commands.Transform[str, transformers.MapNameTransformer],
    ) -> None:
        async with itx.client.acquire() as svc:
            map_types = await svc.maps.fetch_map_types()
        modal = map_views.MapSubmitModal(
            map_code=map_code,
            map_name=map_name,
            map_type_options=map_types,
        )
        await itx.response.send_modal(modal)

    @app_commands.command(name="map-search", description="Search for maps")
    @app_commands.describe(
        map_type="Map type",
        map_name="Overwatch map name",
        creator="Creator's Discord name",
        map_code="Overwatch Workshop Code (ignores the other filters)",
    )
    async def map_search(
        self,
        itx: AkandeItx,
        map_type: app_commands.Transform[str, transformers.MapTypeTransformer]
        | None = None,
        map_name: app_commands.Transform[str, transformers.MapNameTransformer]
        | None = None,
        creator: app_commands.Transform[int, transformers.UserTransformer]
        | None = None,
        map_code: app_commands.Transform[str, transformers.CodeTransformer]
        | None = None,
    ) -> None:
        async with itx.client.acquire() as svc:
            if map_code is not None:
                single = await svc.maps.fetch_map(map_code=map_code)
                maps = [single] if single else []
            else:
                maps = await svc.maps.fetch_map(
                    map_type=map_type, map_name=map_name, creator=creator
                )
        if not maps:
            raise UserFacingError("No maps found.")
        await views.Paginator(itx, map_views.map_search_pages(maps)).start()

    @app_commands.command(name="random-map", description="Roll a random map")
    @app_commands.describe(random_level="Also pick a random level from the map")
    async def random_map(self, itx: AkandeItx, random_level: bool = False) -> None:
        async with itx.client.acquire() as svc:
            map_ = await svc.maps.fetch_random_map()
        if not map_:
            raise UserFacingError("No maps found.")
        card = map_views.random_map_card(map_, show_level=random_level)
        await views.Paginator(itx, [card]).start()

    @app_commands.command(name="view-guide", description="View guides for a map")
    @app_commands.describe(map_code="Overwatch Workshop Code")
    async def view_guide(
        self,
        itx: AkandeItx,
        map_code: app_commands.Transform[str, transformers.CodeTransformer],
    ) -> None:
        async with itx.client.acquire() as svc:
            guides = await svc.maps.fetch_guides(map_code)
        if not guides:
            raise UserFacingError("No guides exist for this map.")

        pages: list[list[str | discord.ui.Item]] = [
            [f"## Guides for {map_code}", "\n".join(chunk)]
            for chunk in itertools.batched(guides, 10)
        ]
        await views.Paginator(itx, pages).start()

    @app_commands.command(name="add-guide", description="Add a guide for a map")
    @app_commands.describe(map_code="Overwatch Workshop Code", url="Guide URL")
    async def add_guide(
        self,
        itx: AkandeItx,
        map_code: app_commands.Transform[str, transformers.CodeTransformer],
        url: app_commands.Transform[str, transformers.URLTransformer],
    ) -> None:
        async with itx.client.acquire() as svc:
            guides = await svc.maps.fetch_guides(map_code)
        if url in guides:
            raise UserFacingError("This guide has already been submitted.")

        confirmed = await views.Confirm.prompt(
            itx,
            f"Is this correct?\nMap code: **{map_code}**\nURL: {url}",
        )
        if not confirmed:
            return

        async with itx.client.acquire() as svc:
            await svc.maps.add_guide(map_code, url)
