from __future__ import annotations

import typing

import discord
from discord import app_commands
from discord.ext import commands

import utils
import views
from cogs.tournament.utils import Categories_NoGen, Category
from cogs.tournament.utils.errors import TournamentNotActiveError
from cogs.tournament.utils.utils import ORG_CHAT, ORGANIZER

if typing.TYPE_CHECKING:
    import core


class TournamentSubmissions(commands.Cog):
    def __init__(self, bot: core.Doom):
        self.bot = bot

    tournament = app_commands.Group(
        name="tournament",
        description="tournament",
        guild_ids=[195387617972322306, utils.GUILD_ID],
    )

    async def insert_record(self, category: Category, user_id: int, screenshot_url: str, record: float):
        query = """
            INSERT INTO tournament_records (user_id, category, record, tournament_id, screenshot)
            VALUES ($1, $2, $3, (SELECT id FROM tournament WHERE active = TRUE LIMIT 1), $4)
        """
        await self.bot.database.execute(query, user_id, category, record, screenshot_url)

    async def get_tournament_id(self) -> int:
        tournament_id_if_exists = self.bot.current_tournament and self.bot.current_tournament.id
        query = "SELECT id FROM tournament WHERE active = TRUE;"
        fetch_id_if_needed = await self.bot.database.fetchval(query)
        return tournament_id_if_exists or await fetch_id_if_needed

    async def get_old_record(self, user_id: int, category: Category, tournament_id: int):
        query = """
            SELECT record, rank()
                over (order by inserted_at DESC) as date_rank FROM tournament_records 
            WHERE user_id = $1 AND
            category = $2 AND 
            tournament_id = $3;
        """
        return await self.bot.database.fetchval(
            query,
            user_id,
            category,
            tournament_id,
        )

    @staticmethod
    async def get_image_url(itx: core.DoomItx):
        return (await itx.original_response()).embeds[0].image.url

    async def submission(
        self,
        itx: core.DoomItx,
        screenshot: discord.Attachment,
        record: float,
        category: Category,
    ):
        await itx.response.defer()
        tournament_id = await self.get_tournament_id()
        if not tournament_id:
            raise TournamentNotActiveError
        old_record = await self.get_old_record(
            itx.user.id,
            category,
            tournament_id,
        )
        if old_record and old_record < record:
            raise utils.RecordNotFasterError
        pretty_record = utils.pretty_record(record)
        embed = utils.DoomEmbed(
            title=f"{itx.client.all_users[itx.user.id]['nickname']}'s {category} Submission",
            description=f"> Record: {pretty_record}",
            image="attachment://image.png",
        )

        view = views.Confirm(itx, confirm_msg="")
        await itx.edit_original_response(
            content=f"{itx.user.mention}, is this correct?",
            embed=embed,
            attachments=[await screenshot.to_file(filename="image.png")],
            view=view,
        )
        await view.wait()
        if not view.value:
            return
        url = await self.get_image_url(itx)
        await self.insert_record(category, itx.user.id, url, record)
        query = """
            SELECT value FROM (SELECT 
            coalesce(value, 'Unranked') as value ,
            coalesce(category, $2) as category
            FROM users u
            LEFT JOIN user_ranks ur on u.user_id = ur.user_id
            WHERE u.user_id = $1) pre WHERE category = $2
        """
        value = await itx.client.database.fetchval(query, itx.user.id, category)
        if value == "Unranked" and category != "Bonus":
            await itx.guild.get_channel(ORG_CHAT).send(
                f"{itx.user.mention} is **UNRANKED** in {category}.\n"
                "Please change this users rank before the end of the tournament!"
            )

    @app_commands.command()
    @app_commands.guilds(discord.Object(id=195387617972322306), discord.Object(id=utils.GUILD_ID))
    async def ta(
        self,
        itx: core.DoomItx,
        screenshot: discord.Attachment,
        record: app_commands.Transform[float, utils.RecordTransformer],
    ):
        await self.submission(itx, screenshot, record, Category.TIME_ATTACK)

    @app_commands.command()
    @app_commands.guilds(discord.Object(id=195387617972322306), discord.Object(id=utils.GUILD_ID))
    async def mc(
        self,
        itx: core.DoomItx,
        screenshot: discord.Attachment,
        record: app_commands.Transform[float, utils.RecordTransformer],
    ):
        await self.submission(itx, screenshot, record, Category.MILDCORE)

    @app_commands.command()
    @app_commands.guilds(discord.Object(id=195387617972322306), discord.Object(id=utils.GUILD_ID))
    async def hc(
        self,
        itx: core.DoomItx,
        screenshot: discord.Attachment,
        record: app_commands.Transform[float, utils.RecordTransformer],
    ):
        await self.submission(itx, screenshot, record, Category.HARDCORE)

    @app_commands.command()
    @app_commands.guilds(discord.Object(id=195387617972322306), discord.Object(id=utils.GUILD_ID))
    async def bo(
        self,
        itx: core.DoomItx,
        screenshot: discord.Attachment,
        record: app_commands.Transform[float, utils.RecordTransformer],
    ):
        await self.submission(itx, screenshot, record, Category.BONUS)

    @tournament.command()
    async def submit(
        self,
        itx: core.DoomItx,
        category: typing.Literal["Time Attack", "Mildcore", "Hardcore", "Bonus"],
        screenshot: discord.Attachment,
        record: app_commands.Transform[float, utils.RecordTransformer],
    ):
        await self.submission(itx, screenshot, record, category)

    @tournament.command()
    async def delete(
        self,
        itx: core.DoomItx,
        category: Categories_NoGen,
        user: discord.Member | None = None,
    ):
        tournament_id = await self.get_tournament_id()
        if not tournament_id:
            raise TournamentNotActiveError

        if user and user != itx.user and itx.guild.get_role(ORGANIZER) not in itx.user.roles:
            raise utils.NoPermissionsError

        if not user:
            user = itx.user

        view = views.Confirm(itx)
        await itx.response.send_message(
            f"Do you want to delete {user.mention}'s latest {category} submission?",
            view=view,
        )

        await view.wait()
        if not view.value:
            return

        query = """
            DELETE
            FROM tournament_records
            WHERE user_id = $1
              AND tournament_id = $3
              AND category = $2
              AND inserted_at = (SELECT max(inserted_at) as inserted_at
                                   FROM tournament_records
                                   WHERE user_id = $1
                                     AND tournament_id = $3
                                     AND category = $2);
        """
        await itx.client.database.execute(query, user.id, category, tournament_id)
