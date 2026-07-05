from __future__ import annotations

import contextlib
import io
import typing

import discord
from discord import app_commands, ui
from discord.ext import commands
from loguru import logger
from msgspec import structs

from database.services import transaction
from utilities import emojis, transformers, views
from utilities.errors import UserFacingError

from .._base import BaseCog
from . import views as record_views

if typing.TYPE_CHECKING:
    from core import Akande, AkandeItx
    from database.services.records import PreviousRecord


_STAR_CHOICES = [
    app_commands.Choice(name=stars, value=i)
    for i, stars in enumerate(emojis.generate_all_star_rating_strings())
]


class RecordsCog(BaseCog, name="records", description="Record related commands."):
    """Records"""

    def __init__(self, bot: Akande) -> None:
        super().__init__(bot)
        self._pr_context_menu = app_commands.ContextMenu(
            name="Personal Records", callback=self._pr_context_callback
        )
        self._wr_context_menu = app_commands.ContextMenu(
            name="World Records", callback=self._wr_context_callback
        )

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(record_views.StarButton)
        self.bot.add_view(record_views.VerificationView())
        self.bot.tree.add_command(self._pr_context_menu)
        self.bot.tree.add_command(self._wr_context_menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(
            self._pr_context_menu.name, type=self._pr_context_menu.type
        )
        self.bot.tree.remove_command(
            self._wr_context_menu.name, type=self._wr_context_menu.type
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        """Lazily convert legacy record embeds when a star reaction lands.

        New-style (components-v2) messages are ignored entirely - the
        StarButton is their only vote path. Legacy messages get the vote
        counted (deduped in ``top_records``, historical votes carry over)
        and are rebuilt in place as a components-v2 card from DB data.
        """
        records_cfg = self.bot.config.channels.records
        if (
            self.bot.user is None
            or payload.user_id == self.bot.user.id
            or payload.channel_id not in (records_cfg.spr_records, records_cfg.records)
            or payload.emoji.id != emojis.UPPER_REACTION_ID
        ):
            return
        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        if message.flags.components_v2:
            logger.debug(
                "Ignoring star reaction on components-v2 message {}",
                payload.message_id,
            )
            return

        async with self.bot.acquire() as svc:
            card = await svc.records.fetch_record_card_data(payload.message_id)
            if card is None or not card.verified:
                return
            counted = await svc.records.add_top_record_vote(
                payload.user_id, payload.message_id, payload.channel_id
            )
            count = await svc.records.fetch_top_record_vote_count(
                payload.message_id, payload.channel_id
            )

        # Legacy embeds consumed their uploaded screenshot (attachments is
        # empty and the file lives at embeds[0].image), so re-upload it as a
        # fresh attachment for the converted card.
        screenshot = await self._download_legacy_screenshot(message)
        sub = record_views.RecordSubmission(
            user_name=card.nickname,
            map_code=card.map_code,
            level_name=card.level_name,
            record=card.record,
            video=card.video,
            screenshot_url="attachment://image.png" if screenshot else None,
        )
        body = record_views.submission_body(sub, header="New Personal Record!")
        # DynamicItem's view type is View | LayoutView, which pyright can't
        # narrow to ActionRow's LayoutView-bound type parameter.
        body.append(ui.ActionRow(record_views.StarButton(message.id, count)))  # pyright: ignore[reportArgumentType]
        try:
            await message.edit(
                content=None,
                embed=None,
                view=views.Card(body),
                attachments=[screenshot] if screenshot else [],
            )
        except discord.HTTPException as e:
            logger.warning("Legacy record conversion failed for {}: {}", message.id, e)
            return
        logger.info(
            "Converted legacy record message {} ({} stars, vote counted: {})",
            message.id,
            count,
            counted,
        )
        if counted:
            await record_views.forward_if_spectacular(self.bot, message, count)

    async def _download_legacy_screenshot(
        self, message: discord.Message
    ) -> discord.File | None:
        if not (message.embeds and (url := message.embeds[0].image.url)):
            return None
        async with self.bot.session.get(url) as resp:
            if not resp.ok:
                logger.warning(
                    "Screenshot download failed for legacy record {}: HTTP {}",
                    message.id,
                    resp.status,
                )
                return None
            return discord.File(io.BytesIO(await resp.read()), "image.png")

    @app_commands.command(
        name="submit-record", description="Submit a record for a map level"
    )
    @app_commands.describe(
        map_code="Overwatch Workshop Code",
        level_name="Level name",
        record="Record time ([HH:][MM:]SS.ss)",
        screenshot="Screenshot proof of the record",
        video="Video proof URL (fully verifies the record)",
        rating="Difficulty rating for the level",
    )
    @app_commands.choices(rating=_STAR_CHOICES)
    async def submit_record(
        self,
        itx: AkandeItx,
        map_code: app_commands.Transform[str, transformers.CodeTransformer],
        level_name: app_commands.Transform[str, transformers.MapLevelTransformer],
        record: app_commands.Transform[float, transformers.RecordTransformer],
        screenshot: discord.Attachment,
        video: app_commands.Transform[str, transformers.URLTransformer] | None = None,
        rating: int | None = None,
    ) -> None:
        async with itx.client.acquire() as svc:
            previous = await svc.records.fetch_previous_record(
                map_code, level_name, itx.user.id
            )
        if previous and previous.record < record:
            raise UserFacingError(
                "Your record must be faster than your previous submission."
            )

        sub = record_views.RecordSubmission(
            user_name=itx.user.display_name,
            map_code=map_code,
            level_name=level_name,
            record=record,
            video=video,
            screenshot_url=screenshot.url,
        )
        confirmed = await views.Confirm.prompt(
            itx,
            *record_views.submission_body(
                sub, header="Record Submission - Is this correct?"
            ),
            defer_on_confirm=True,
        )
        if not confirmed:
            return

        if not isinstance(itx.channel, (discord.TextChannel, discord.Thread)):
            raise UserFacingError("Records can only be submitted in a text channel.")

        sub = structs.replace(sub, screenshot_url="attachment://image.png")
        file = await screenshot.to_file(filename="image.png")
        channel_msg = await itx.channel.send(
            view=views.Card(
                record_views.submission_body(
                    sub, header=f"{emojis.TIME} Waiting for verification..."
                )
            ),
            file=file,
        )

        assert itx.guild
        queue_msg: discord.Message | None = None
        try:
            queue_channel = itx.guild.get_channel(
                itx.client.config.channels.submission.verification_queue
            )
            if not isinstance(queue_channel, discord.TextChannel):
                raise UserFacingError("The verification queue channel is unavailable.")
            queue_file = await screenshot.to_file(filename="image.png")
            queue_msg = await queue_channel.send(
                view=record_views.VerificationView(
                    *record_views.submission_body(sub, header="New record submission")
                ),
                file=queue_file,
            )

            async with itx.client.acquire() as svc, transaction(svc.db):
                await svc.records.insert_record(
                    map_code=map_code,
                    user_id=itx.user.id,
                    level_name=level_name,
                    record=record,
                    screenshot=channel_msg.jump_url,
                    video=video,
                    message_id=channel_msg.id,
                    channel_id=channel_msg.channel.id,
                    hidden_id=queue_msg.id,
                )
                if rating:
                    await svc.records.upsert_level_rating(
                        map_code, level_name, rating, itx.user.id
                    )
        except Exception as exc:
            if queue_msg is not None:
                with contextlib.suppress(discord.HTTPException):
                    await queue_msg.delete()
            with contextlib.suppress(discord.HTTPException):
                await channel_msg.delete()
            # UserFacingError reaches the user via the global tree handler;
            # anything else gets a generic error card here before re-raising.
            if not isinstance(exc, UserFacingError):
                await views.send_error(
                    itx,
                    "Submission failed - this record was not saved. Please try again.",
                )
            raise

        if previous and previous.hidden_id:
            await self._retire_superseded_submission(itx, sub, previous, queue_channel)

        await itx.edit_original_response(
            view=views.Card(
                [
                    f"✅ Record submitted - waiting for verification.\n"
                    f"{channel_msg.jump_url}"
                ]
            )
        )

    @staticmethod
    async def _retire_superseded_submission(
        itx: AkandeItx,
        sub: record_views.RecordSubmission,
        previous: PreviousRecord,
        queue_channel: discord.TextChannel,
    ) -> None:
        """Drop the superseded queue post and mark its record message auto-rejected."""
        assert previous.hidden_id
        with contextlib.suppress(discord.HTTPException):
            await queue_channel.get_partial_message(previous.hidden_id).delete()
        assert itx.guild
        old_channel = itx.guild.get_channel_or_thread(previous.channel_id)
        if not isinstance(old_channel, (discord.TextChannel, discord.Thread)):
            return
        old_sub = structs.replace(sub, record=previous.record, video=previous.video)
        with contextlib.suppress(discord.HTTPException):
            await old_channel.get_partial_message(previous.message_id).edit(
                view=views.Card(
                    record_views.submission_body(
                        old_sub, header="Record Submission", superseded=True
                    )
                )
            )

    @app_commands.command(
        name="leaderboard", description="View the leaderboard for a map"
    )
    @app_commands.describe(
        map_code="Overwatch Workshop Code",
        level_name="Level name (omit to show the world record for every level)",
        verified="Show only video-verified records",
    )
    async def leaderboard(
        self,
        itx: AkandeItx,
        map_code: app_commands.Transform[str, transformers.CodeTransformer],
        level_name: app_commands.Transform[str, transformers.MapLevelTransformer]
        | None = None,
        verified: bool = False,
    ) -> None:
        async with itx.client.acquire() as svc:
            records = await svc.records.fetch_leaderboard(
                map_code, level_name, verified
            )
        if not records:
            raise UserFacingError("No records found.")
        title = f"Leaderboard - {map_code}" + (f" - {level_name}" if level_name else "")
        pages = record_views.leaderboard_pages(
            records, title, single_level=level_name is not None
        )
        await views.Paginator(itx, pages).start()

    @app_commands.command(
        name="personal-records", description="View a user's personal records"
    )
    @app_commands.describe(
        user="User to look up (defaults to you)",
        wr_only="Show only world records",
    )
    async def personal_records(
        self,
        itx: AkandeItx,
        user: discord.Member | discord.User | None = None,
        wr_only: bool = False,
    ) -> None:
        await self._personal_records(itx, user, wr_only)

    async def _pr_context_callback(self, itx: AkandeItx, user: discord.Member) -> None:
        await self._personal_records(itx, user, False)

    async def _wr_context_callback(self, itx: AkandeItx, user: discord.Member) -> None:
        await self._personal_records(itx, user, True)

    @staticmethod
    async def _personal_records(
        itx: AkandeItx,
        user: discord.Member | discord.User | None,
        wr_only: bool,
    ) -> None:
        target = user or itx.user
        async with itx.client.acquire() as svc:
            records = await svc.records.fetch_personal_records(target.id, wr_only)
        if not records:
            raise UserFacingError("No records found.")
        title = f"Personal {'World ' if wr_only else ''}Records - {target.display_name}"
        pages = record_views.personal_record_pages(records, title)
        await views.Paginator(itx, pages).start()

    @app_commands.command(
        name="verification-stats", description="View verification counts"
    )
    @app_commands.describe(user="User to look up (omit for the leaderboard)")
    async def verification_stats(
        self,
        itx: AkandeItx,
        user: app_commands.Transform[int, transformers.UserTransformer] | None = None,
    ) -> None:
        async with itx.client.acquire() as svc:
            if user is not None:
                count = await svc.records.fetch_verification_count(user)
                if count is None:
                    raise UserFacingError("No verifications found for that user.")
                await itx.response.send_message(
                    f"{count.nickname} has **{count.amount}** verifications!",
                    ephemeral=True,
                )
                return
            entries = await svc.records.fetch_verification_leaderboard()
        if not entries:
            raise UserFacingError("No verifications found.")
        pages = record_views.verification_stats_pages(entries)
        await views.Paginator(itx, pages).start()
