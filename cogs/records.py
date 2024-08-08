from __future__ import annotations

import contextlib
import typing

import discord
from discord import app_commands
from discord.ext import commands

import utils
import views

if typing.TYPE_CHECKING:
    import core
    from core import DoomItx


class Records(commands.Cog):
    """Records"""

    def __init__(self, bot: core.Doom):
        self.bot = bot
        self.bot.tree.add_command(
            app_commands.ContextMenu(
                **utils.personal_records_c,
                callback=self.pr_context_callback,
                guild_ids=[utils.GUILD_ID],
            )
        )
        self.bot.tree.add_command(
            app_commands.ContextMenu(
                **utils.world_records_c,
                callback=self.wr_context_callback,
                guild_ids=[utils.GUILD_ID],
            )
        )

    @app_commands.command(**utils.submit_record)
    @app_commands.describe(**utils.submit_record_args)
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID))
    @app_commands.choices(rating=utils.ALL_STARS_CHOICES)
    async def submit_record(
        self,
        itx: DoomItx,
        map_code: app_commands.Transform[str, utils.MapCodeRecordsTransformer],
        level_name: app_commands.Transform[str, utils.MapLevelTransformer],
        record: app_commands.Transform[float, utils.RecordTransformer],
        screenshot: discord.Attachment,
        video: app_commands.Transform[str, utils.URLTransformer] | None,
        rating: int | None,
    ) -> None:
        await itx.response.defer(ephemeral=False)
        if map_code not in itx.client.map_cache.keys():
            raise utils.InvalidMapCodeError

        if level_name not in itx.client.map_cache[map_code]["levels"]:
            raise utils.InvalidMapLevelError

        query = """
            SELECT record, hidden_id FROM records r 
            LEFT OUTER JOIN maps m on r.map_code = m.map_code
            WHERE r.map_code = $1 AND level_name = $2 AND user_id = $3
            ORDER BY inserted_at DESC
        """
        old_row = await itx.client.database.fetchrow(
            query,
            map_code,
            level_name,
            itx.user.id,
        )
        if old_row and old_row["record"] < record:
            raise utils.RecordNotFasterError

        user = itx.client.all_users[itx.user.id]

        view = views.Confirm(
            itx,
            f"{utils.TIME} Waiting for verification...\n",
        )
        new_screenshot = await screenshot.to_file(filename="image.png")

        embed = utils.record_embed(
            {
                "map_code": map_code,
                "map_level": level_name,
                "record": utils.pretty_record(record),
                "video": video,
                "user_name": user["nickname"],
                "user_url": itx.user.display_avatar.url,
            }
        )
        channel_msg = await itx.edit_original_response(
            content=f"{itx.user.mention}, is this correct?",
            embed=embed,
            view=view,
            attachments=[new_screenshot],
        )
        await view.wait()
        if not view.value:
            return
        new_screenshot2 = await screenshot.to_file(filename="image.png")
        verification_msg = await itx.client.get_channel(utils.VERIFICATION_QUEUE).send(embed=embed, file=new_screenshot2)

        if old_row and old_row["hidden_id"]:
            with contextlib.suppress(discord.NotFound):
                await itx.guild.get_channel(utils.VERIFICATION_QUEUE).get_partial_message(old_row["hidden_id"]).delete()

        view = views.VerificationView()
        await verification_msg.edit(view=view)
        query = """
            INSERT INTO records
            (map_code, user_id, level_name, record, screenshot,
            video, message_id, channel_id, hidden_id) 
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """
        await itx.client.database.execute(
            query,
            map_code,
            itx.user.id,
            level_name,
            record,
            channel_msg.jump_url,
            video,
            channel_msg.id,
            channel_msg.channel.id,
            verification_msg.id,
        )
        if rating:
            query = """
                INSERT INTO map_level_ratings (map_code, level, rating, user_id) 
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (map_code, level, user_id) DO UPDATE SET rating = excluded.rating 
            """
            await itx.client.database.execute(
                query,
                map_code,
                level_name,
                rating,
                itx.user.id,
            )

    @app_commands.command(**utils.leaderboard)
    @app_commands.describe(**utils.leaderboard_args)
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID), discord.Object(id=195387617972322306))
    async def view_records(
        self,
        itx: DoomItx,
        map_code: app_commands.Transform[str, utils.MapCodeRecordsTransformer],
        level_name: app_commands.Transform[str, utils.MapLevelTransformer] | None,
        verified: bool | None = False,
    ) -> None:
        await itx.response.defer(ephemeral=True)
        if map_code not in itx.client.map_cache.keys():
            raise utils.InvalidMapCodeError

        query = """
        WITH base_record_data AS (
                SELECT
                    coalesce(a.alias, u.nickname) AS alias,
                    u.user_id,
                    m.map_code,
                    m.map_name,
                    r.level_name,
                    r.record,
                    r.screenshot,
                    r.video,
                    r.verified,
                    r.inserted_at,
                    rank() OVER (
                        PARTITION BY r.map_code, r.user_id, level_name ORDER BY inserted_at DESC
                    ) AS latest
            
                FROM records r
                LEFT JOIN alias a ON r.user_id = a.user_id AND a.primary = TRUE
                LEFT JOIN users u ON r.user_id = u.user_id
                LEFT JOIN maps m ON r.map_code = m.map_code
                WHERE r.map_code = $1
                    AND ($4::boolean IS FALSE OR r.video IS NOT NULL)
                    AND ($3::text IS NULL OR r.level_name = $3)
                    AND verified = TRUE
            ), base_tournament_records AS (
                SELECT
                    coalesce(a.alias, u.nickname) AS alias,
                    tr.user_id,
                    tr.record,
                    tr.screenshot,
                    tr.inserted_at,
                    tm.code as map_code,
                    tm.level AS level_name,
                    rank() OVER (
                       PARTITION BY tr.user_id, tm.code, tm.level ORDER BY inserted_at DESC
                    ) AS latest
                FROM tournament_records tr
                LEFT JOIN tournament_maps tm ON tr.category = tm.category AND tr.tournament_id = tm.id
                LEFT JOIN alias a ON tr.user_id = a.user_id AND a."primary" = TRUE
                LEFT JOIN users u ON tr.user_id = u.user_id
                WHERE tm.code = $1
                    AND ($3::text IS NULL OR tm.level = $3)
            ), latest_base_records AS (
                SELECT
                    brd.alias,
                    brd.user_id,
                    brd.map_code,
                    brd.map_name,
                    brd.level_name,
                    brd.record,
                    brd.screenshot,
                    brd.video,
                    brd.verified,
                    brd.inserted_at,
                    FALSE AS tournament
                FROM base_record_data brd
                WHERE latest = 1
            ), latest_base_tournament_records AS (
                SELECT
                    btr.alias,
                    btr.user_id,
                    btr.map_code,
                    NULL AS map_name,
                    btr.level_name,
                    btr.record,
                    btr.screenshot,
                    NULL AS video,
                    TRUE AS verified,
                    btr.inserted_at,
                    TRUE AS tournament
                FROM base_tournament_records btr
                WHERE latest = 1
            ), all_records_union AS (
                SELECT * FROM latest_base_tournament_records lbtr
                UNION DISTINCT (
                    SELECT * FROM latest_base_records
                )
            ), all_records_with_rank AS (
                SELECT
                    rank() OVER ( PARTITION BY alr.map_code, alr.level_name ORDER BY alr.record ) AS rank_num,
                    *
                FROM all_records_union alr
            )
            SELECT
                arwr.alias AS nickname,
                arwr.level_name,
                arwr.record,
                arwr.screenshot,
                arwr.video,
                arwr.tournament,
                arwr.verified,
                arwr.map_code,
                arwr.map_name,
                arwr.rank_num,
                string_agg(coalesce(a.alias, u.nickname), ', ') AS creator_name
            FROM all_records_with_rank arwr
            LEFT JOIN map_creators mc ON arwr.map_code = mc.map_code
            LEFT JOIN alias a ON mc.user_id = a.user_id AND a."primary" = TRUE
            LEFT JOIN users u ON mc.user_id = u.user_id
            WHERE
                ($4::boolean IS FALSE OR video IS NOT NULL)
                AND ($2::boolean IS NOT FALSE OR rank_num = 1)
            GROUP BY
                arwr.alias,
                arwr.level_name,
                arwr.record,
                arwr.screenshot,
                arwr.video,
                arwr.tournament,
                arwr.verified,
                arwr.map_code,
                arwr.map_name,
                arwr.rank_num
            ORDER BY map_code, level_name, record;
        """

        records = await itx.client.database.fetch(query, map_code, bool(level_name), level_name, verified)
        if not records:
            raise utils.NoRecordsFoundError

        if level_name:
            embeds = utils.all_levels_records_embed(records, f"Leaderboard - {map_code} - {level_name}", True)
        else:
            embeds = utils.all_levels_records_embed(records, f"Leaderboard - {map_code}")

        view = views.Paginator(embeds, itx.user)
        await view.start(itx)

    @app_commands.command(**utils.personal_records)
    @app_commands.describe(**utils.personal_records_args)
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID), discord.Object(id=195387617972322306))
    async def personal_records_slash(
        self,
        itx: DoomItx,
        user: discord.Member | discord.User | None = None,
        wr_only: bool | None = None,
    ):
        await self._personal_records(itx, user, wr_only)

    async def pr_context_callback(self, itx: DoomItx, user: discord.Member):
        await self._personal_records(itx, user, False)

    async def wr_context_callback(self, itx: DoomItx, user: discord.Member):
        await self._personal_records(itx, user, True)

    @staticmethod
    async def _personal_records(itx, user, wr_only):
        await itx.response.defer(ephemeral=True)
        if not user:
            user = itx.user

        query = """
            WITH base_personal_records AS (
                SELECT
                    coalesce(a.alias, u.nickname) AS nickname,
                    r.user_id,
                    r.level_name,
                    r.record,
                    r.screenshot,
                    r.video,
                    r.verified,
                    r.map_code,
                    rank() OVER (
                        PARTITION BY r.map_code, level_name, r.user_id
                        ORDER BY inserted_at DESC
                    ) AS latest,
                    RANK() OVER (
                        PARTITION BY r.map_code, level_name
                        ORDER BY record
                    ) AS rank_num
                FROM records r
                LEFT JOIN alias a ON r.user_id = a.user_id AND a."primary" = TRUE
                LEFT JOIN users u ON r.user_id = u.user_id
                WHERE verified = TRUE
            )
            SELECT
                bpr.nickname,
                bpr.level_name,
                bpr.record,
                bpr.screenshot,
                bpr.video,
                bpr.verified,
                bpr.map_code,
                m.map_name,
                bpr.rank_num,
                string_agg(coalesce(a.alias, u.nickname), ', ') as creators
            FROM base_personal_records bpr
            LEFT JOIN maps m ON bpr.map_code = m.map_code
            LEFT JOIN map_creators mc ON bpr.map_code = mc.map_code
            LEFT JOIN alias a ON mc.user_id = a.user_id AND a."primary" = TRUE
            LEFT JOIN users u ON mc.user_id = u.user_id
            WHERE 
                latest = 1 
                AND bpr.user_id = $1
                AND ($2 IS FALSE OR bpr.rank_num = 1)
            GROUP BY
                bpr.nickname,
                bpr.level_name,
                bpr.record,
                bpr.screenshot,
                bpr.video,
                bpr.verified,
                bpr.map_code,
                m.map_name,
                bpr.rank_num
            ORDER BY map_code, substr(level_name, 1, 5) <> 'Level', level_name;
        """
        records = await itx.client.database.fetch(query, user.id, wr_only)
        if not records:
            raise utils.NoRecordsFoundError
        embeds = utils.pr_records_embed(
            records,
            f"Personal {'World ' if wr_only else ''}Records | {itx.client.all_users[user.id]['nickname']}",
        )
        view = views.Paginator(embeds, itx.user)
        await view.start(itx)

    @app_commands.command(name="verification-stats")
    @app_commands.describe(**utils.u_args)
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID))
    async def verification_stats(
        self,
        itx: DoomItx,
        user: app_commands.Transform[int, utils.UserTransformer] | None = None,
    ):
        await itx.response.defer(ephemeral=True)
        if user:
            query = """
                SELECT v.user_id, amount, nickname
                FROM verification_counts v
                         LEFT JOIN users u on v.user_id = u.user_id
                WHERE v.user_id = $1;
            """
            res = await itx.client.database.fetchrow(
                query,
                user,
            )
            await itx.edit_original_response(content=f"{res['nickname']} has **{res['amount']}** verifications!")
        else:
            query = """
                SELECT v.user_id,
                       amount,
                       nickname,
                       RANK() OVER (
                           ORDER BY amount DESC
                           ) rank
                FROM verification_counts v
                         LEFT JOIN users u on v.user_id = u.user_id
                ORDER BY amount DESC;
            """
            res = await itx.client.database.fetch(query)
            leaderboard = ""
            for placement, record in enumerate(res):
                leaderboard += f"`{utils.make_ordinal(record['rank']):^6}` `{record['amount']:^6}` `{record['nickname']}`\n"

            await itx.edit_original_response(content=leaderboard)


async def setup(bot):
    """Add Cog to Discord bot."""
    await bot.add_cog(Records(bot))
