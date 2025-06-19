from __future__ import annotations

import typing
from logging import getLogger

from discord import app_commands
from discord.ext import commands, tasks

import utils.utils
from cogs.tournament.utils import CategoryData
from cogs.tournament.utils.data import TournamentData

if typing.TYPE_CHECKING:
    import core
    from core import DoomCtx

logger = getLogger(__name__)


class Tasks(commands.Cog):
    def __init__(self, bot: core.Doom):
        self.bot = bot
        self.cache_all_users.start()
        self.cache_map_code_choices.start()
        self.cache_map_names.start()
        self.cache_map_types.start()
        self.cache_map_data.start()
        self.cache_exercise_names.start()
        self.cache_exercise_names_search.start()
        self.cache_tags.start()
        self.cache_keep_alives.start()
        self.cache_auto_join.start()
        self.cache_insults.start()
        self.cache_tournament.start()

    @commands.command()
    @commands.is_owner()
    async def refresh_cache(
        self,
        ctx: DoomCtx,
    ):
        self.cache_all_users.restart()
        self.cache_map_code_choices.restart()
        self.cache_map_names.restart()
        self.cache_map_types.restart()
        self.cache_map_data.restart()
        self.cache_exercise_names.restart()
        self.cache_exercise_names_search.restart()
        self.cache_tags.restart()
        self.cache_keep_alives.restart()
        self.cache_auto_join.restart()
        self.cache_insults.restart()
        await ctx.message.delete()

    @tasks.loop(hours=24, count=1)
    async def cache_tournament(self):
        await self.bot.wait_until_ready()
        logger.debug("Caching tournament...")
        query = """
            SELECT *
            FROM (SELECT title,
                         start,
                         "end",
                         active,
                         bracket,
                         roles,
                         id,
                         start > now()                as needs_start_task,
                         "end" > now()                as needs_end_task,
                         start < now() and "end" > now() and not active as needs_start_now,
                         "end" < now() and active     as needs_end_now
                  FROM tournament) t
            WHERE id = (SELECT max(id) FROM tournament)
        """
        tournament = await self.bot.database.fetchrow(query)
        if not tournament:
            return
        query = "SELECT * FROM tournament_maps WHERE id=$1;"
        maps = await self.bot.database.fetch(query, tournament["id"])

        map_data = {
            row["category"]: CategoryData(code=row["code"], level=row["level"], creator=row["creator"]) for row in maps
        }

        self.bot.current_tournament = TournamentData(
            client=self.bot,
            title=tournament["title"],
            start=tournament["start"],
            end=tournament["end"],
            bracket=tournament["bracket"],
            data=map_data,
            id_=tournament["id"],
        )

        if tournament["needs_start_task"]:
            utils.start_tournament_task.change_interval(time=self.bot.current_tournament.start.time())
            utils.start_tournament_task.start(self.bot.current_tournament)

        if tournament["needs_end_task"]:
            utils.end_tournament_task.change_interval(time=self.bot.current_tournament.end.time())
            utils.end_tournament_task.start(self.bot.current_tournament)

        if tournament["needs_start_now"]:
            await utils.start_tournament(self.bot.current_tournament)

        if tournament["needs_end_now"]:
            await utils.end_tournament(self.bot.current_tournament)

        logger.debug("Tournament cached.")

    @tasks.loop(hours=24, count=1)
    async def cache_map_code_choices(self):
        logger.debug("Caching map codes...")
        query = "SELECT map_code FROM maps ORDER BY 1;"
        rows = await self.bot.database.fetch(query)
        self.bot.map_codes_choices = [app_commands.Choice(name=row["map_code"], value=row["map_code"]) for row in rows]
        logger.debug("Map codes cached.")

    @tasks.loop(hours=24, count=1)
    async def cache_map_names(self):
        logger.debug("Caching map names...")
        query = "SELECT * FROM all_map_names ORDER BY 1;"
        rows = await self.bot.database.fetch(query)
        self.bot.map_names_choices = [app_commands.Choice(name=row["name"], value=row["name"]) for row in rows]
        self.bot.map_names = [row.name for row in self.bot.map_names_choices]
        logger.debug("Map names cached.")

    @tasks.loop(hours=24, count=1)
    async def cache_map_types(self):
        logger.debug("Caching map types...")
        query = "SELECT * FROM all_map_types ORDER BY 1;"
        rows = await self.bot.database.fetch(query)

        self.bot.map_types_choices = [app_commands.Choice(name=row["name"], value=row["name"]) for row in rows]
        self.bot.map_types = [row.name for row in self.bot.map_types_choices]
        logger.debug("Map types cached.")

    @tasks.loop(hours=24, count=1)
    async def cache_exercise_names(self):
        self.bot.exercise_names = []
        self.bot.exercise_category_map = {}
        query = "SELECT name, type FROM all_exercises ORDER BY 1;"
        rows = await self.bot.database.fetch(query)
        for row in rows:
            self.bot.exercise_names.append(app_commands.Choice(name=row["name"], value=row["name"]))
            self.bot.exercise_category_map[row["name"]] = row["type"]

    @tasks.loop(hours=24, count=1)
    async def cache_exercise_names_search(self):
        query = "SELECT * FROM exercises ORDER BY 1;"
        rows = await self.bot.database.fetch(query)
        self.bot.exercise_names_search = [app_commands.Choice(name=row["name"], value=row["name"]) for row in rows]

    @tasks.loop(hours=24, count=1)
    async def cache_map_data(self):
        query = """
            SELECT DISTINCT array_agg(DISTINCT level) as levels,
                            m.map_code,
                            array_agg(distinct user_id) as user_ids
            FROM maps m
                     LEFT JOIN map_levels ml ON m.map_code = ml.map_code
                     LEFT JOIN map_creators mc ON m.map_code = mc.map_code
            GROUP BY m.map_code
            ORDER BY levels;
        """
        rows = await self.bot.database.fetch(query)
        for row in rows:
            self.bot.map_cache[row["map_code"]] = utils.utils.MapCacheData(
                levels=[y for y in row["levels"]],
                user_ids=[y for y in row["user_ids"]],
                choices=[app_commands.Choice(name=y, value=y) for y in row["levels"]],
            )

    @tasks.loop(hours=24, count=1)
    async def cache_all_users(self):
        self.bot.users_choices = []
        query = "SELECT * FROM users"
        rows = await self.bot.database.fetch(query)
        for row in rows:
            self.bot.all_users[row["user_id"]] = utils.utils.UserCacheData(
                nickname=row["nickname"], alertable=row["alertable"]
            )
            self.bot.users_choices.append(app_commands.Choice(name=row["nickname"], value=str(row["user_id"])))

    @tasks.loop(hours=24, count=1)
    async def cache_tags(self):
        self.bot.tag_cache = []
        self.bot.tag_choices = []
        query = "SELECT * FROM tags;"
        rows = await self.bot.database.fetch(query)
        for row in rows:
            self.bot.tag_cache.append(row["name"])
            self.bot.tag_choices.append(app_commands.Choice(name=row["name"], value=row["name"]))

    @tasks.loop(hours=24, count=1)
    async def cache_keep_alives(self):
        self.bot.keep_alives = []
        query = "SELECT * FROM keep_alives;"
        rows = await self.bot.database.fetch(query)
        for row in rows:
            self.bot.keep_alives.append(row["thread_id"])

    @tasks.loop(hours=24, count=1)
    async def cache_auto_join(self):
        self.bot.auto_join_threads = []
        query = "SELECT * FROM auto_join_thread;"
        rows = await self.bot.database.fetch(query)
        for row in rows:
            self.bot.auto_join_threads.append((row["channel_id"], row["thread_id"]))

    @tasks.loop(hours=24, count=1)
    async def cache_insults(self):
        self.bot.insults = []
        query = "SELECT * FROM insults;"
        rows = await self.bot.database.fetch(query)
        for row in rows:
            self.bot.insults.append(row["value"])


async def setup(bot: core.Doom):
    await bot.add_cog(Tasks(bot))
