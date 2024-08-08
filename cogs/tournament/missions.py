from __future__ import annotations

import typing
from typing import Any, Tuple

from discord import app_commands
from discord.ext import commands

import utils
import views
from cogs.tournament.utils import Categories, Category, Difficulty, MissionDifficulty, MissionType, Type
from cogs.tournament.utils.data import missions_embed
from cogs.tournament.utils.errors import (
    InvalidMissionType,
    MismatchedMissionCategoryType,
    NoMissionExists,
    TargetNotInteger,
    TournamentNotActiveError,
)
from cogs.tournament.utils.utils import ANNOUNCEMENTS, role_map
from cogs.tournament.views.announcement import TournamentRolesDropdown
from database import DotRecord
from utils import pretty_record, time_convert

if typing.TYPE_CHECKING:
    import core


class Missions(commands.Cog):
    def __init__(self, bot: core.Doom):
        self.bot = bot

    missions = app_commands.Group(
        name="missions",
        description="Missions",
        guild_ids=[195387617972322306, utils.GUILD_ID],
    )

    @missions.command()
    async def add(
        self,
        itx: core.DoomItx,
        category: Categories,
        difficulty: Difficulty,
        mission_type: Type,
        target: str,
    ):
        if "-" in mission_type:
            raise InvalidMissionType

        if not itx.client.current_tournament:
            raise TournamentNotActiveError

        await itx.response.defer()
        # Verify if mission type goes with category
        if category == Category.GENERAL and mission_type not in MissionType.general():
            raise MismatchedMissionCategoryType

        if category != Category.GENERAL and mission_type not in MissionType.difficulty():
            raise MismatchedMissionCategoryType

        target, extra = self.validate_target(mission_type, target)
        query = "SELECT * FROM tournament_missions WHERE category=$1 AND difficulty=$2 and id=$3;"
        old_mission = await itx.client.database.fetchrow(
            query,
            category,
            difficulty,
            itx.client.current_tournament.id,
        )
        if old_mission:
            content = (
                "There's already a mission in this category and difficulty.\n" "Are you sure you want to overwrite this?\n\n"
            )
        else:
            content = "Is this correct?\n\n"
        content += (
            f"**Category: **{category}\n"
            f"**Difficulty: ** {difficulty}\n"
            f"**Type: ** {mission_type}\n"
            f"**Target: ** {target}\n"
            f"**Extra: ** {extra}\n"
        )
        view = views.Confirm(itx)
        await itx.edit_original_response(content=content, view=view)
        await view.wait()
        if not view.value:
            return
        query = """
            INSERT INTO tournament_missions (id, type, target, difficulty, category, extra_target) 
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (id, category, difficulty)
            DO UPDATE SET target = EXCLUDED.target, type = EXCLUDED.type
        """
        await itx.client.database.execute(
            query,
            itx.client.current_tournament.id,
            mission_type,
            target,
            difficulty,
            category,
            extra,
        )

    def validate_target(self, mission_type: Type, target: str) -> tuple[float | int | Any, Any | None]:
        extra = None
        if mission_type == MissionType.MISSION_THRESHOLD:
            res, extra = target.split(maxsplit=1)
            res = self._convert_to_int(res)
            extra = extra.capitalize()
            if extra not in MissionDifficulty.diffs():
                raise ValueError
        elif mission_type in MissionType.general():
            res = self._convert_to_int(target)
        elif mission_type == MissionType.SUB_TIME:
            res = time_convert(target)
        else:
            res = 0
        return res, extra

    @staticmethod
    def _convert_to_int(value):
        try:
            return int(value)
        except ValueError:
            raise TargetNotInteger

    @missions.command()
    async def remove(
        self,
        itx: core.DoomItx,
        category: Categories,
        difficulty: Difficulty,
    ):
        if not itx.client.current_tournament:
            raise TournamentNotActiveError

        await itx.response.defer(ephemeral=True)
        query = "SELECT * FROM tournament_missions WHERE category=$1 AND difficulty=$2 and id=$3;"
        mission = await itx.client.database.fetchrow(
            query,
            category,
            difficulty,
            itx.client.current_tournament.id,
        )
        if not mission:
            raise NoMissionExists

        view = views.Confirm(itx)
        await itx.edit_original_response(
            content=(
                "Are you sure you want to delete this mission?\n\n"
                f"**Category: **{category}\n"
                f"**Difficulty: ** {difficulty}\n"
                f"**Type: ** {mission['type']}\n"
                f"**Target: ** {mission['target']}\n"
            ),
            view=view,
        )
        await view.wait()
        if not view.value:
            return
        query = "DELETE FROM tournament_missions WHERE category = $1 AND difficulty = $2 and id = $3;"
        await itx.client.database.execute(
            query,
            category,
            difficulty,
            itx.client.current_tournament.id,
        )

    @missions.command()
    async def publish(self, itx: core.DoomItx):
        if not itx.client.current_tournament:
            raise TournamentNotActiveError

        await itx.response.defer(ephemeral=True)
        query = """
            SELECT 
                tmi.id,
                type,
                target,
                difficulty,
                tmi.category,
                extra_target,
                code,
                level,
                creator
            FROM tournament_missions tmi
            LEFT JOIN tournament_maps tm on tmi.category = tm.category AND tmi.id = tm.id
            WHERE tmi.id = $1
            ORDER BY tmi.category != 'General',
                     tmi.category != 'Time Attack',
                     tmi.category != 'Mildcore',
                     tmi.category != 'Hardcore',
                     tmi.category != 'Bonus',
                     difficulty != 'Easy',
                     difficulty != 'Medium',
                     difficulty != 'Hard',
                     difficulty != 'Expert'
        """
        missions = await itx.client.database.fetch(query, itx.client.current_tournament.id)
        if not missions:
            raise NoMissionExists

        embed = missions_embed(self.pretty_missions(missions))
        # TODO: add ending tourny time
        end_time = self.bot.current_tournament.end_formatted
        embed.description = embed.description + f"\n\nEnds:\n{end_time}"

        view = views.Confirm(itx)
        dropdown = TournamentRolesDropdown()
        view.add_item(dropdown)
        await itx.edit_original_response(content="Is this correct?", embed=embed, view=view)
        await view.wait()
        if not view.value:
            return

        roles = [itx.guild.get_role(role_map[x]) for x in dropdown.values]
        mentions = "".join([r.mention for r in roles])
        await itx.guild.get_channel(ANNOUNCEMENTS).send(content=mentions, embed=embed)

    def pretty_missions(self, missions: list[DotRecord]):
        description = "__**Missions**__\n"
        cur_category = missions[0]["category"]
        if missions[0]["code"]:
            map_data = f"({missions[0]['code']} - {missions[0]['level']})"
        else:
            map_data = ""
        mission_text = ""
        for mission in missions:
            if mission["category"] not in cur_category:
                description += f"\n**{cur_category} {map_data}**\n"
                description += mission_text
                mission_text = ""
                cur_category = mission["category"]
                map_data = f"({mission['code']} - {mission['level']})"

            mission_text += self.format_missions(
                mission["difficulty"], mission["type"], mission["target"], mission["extra_target"]
            )
        if mission_text:
            description += f"\n**{cur_category} {map_data}**\n"
            description += mission_text
        return description

    @staticmethod
    def format_missions(
        difficulty: str,
        mission_type: str,
        target: str | int | float,
        extra: str,
    ) -> str:
        """Format missions into user-friendly strings."""
        formatted = ""
        if mission_type == MissionType.XP_THRESHOLD:
            formatted += f"Get {target} XP (excluding this mission)\n"
        elif mission_type == MissionType.MISSION_THRESHOLD:
            formatted += f"Complete {int(target)} {extra} missions\n"
        elif mission_type == MissionType.TOP_PLACEMENT:
            formatted += f"Get Top 3 in {target} categories.\n"
        elif mission_type == MissionType.SUB_TIME:
            formatted += f"Get sub {pretty_record(float(target))}\n"
        elif mission_type == MissionType.COMPLETION:
            formatted += "Complete the level.\n"

        return f"- {difficulty}: {formatted}"
