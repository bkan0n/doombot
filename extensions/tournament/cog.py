from __future__ import annotations

import contextlib
import datetime
import pathlib
import typing

import discord
from discord import app_commands, ui
from discord.ext import commands
from loguru import logger
from msgspec import structs

from database.services import transaction
from utilities import transformers, views
from utilities.errors import UserFacingError

from .._base import BaseCog
from . import models
from . import views as t_views
from . import xp as xp_mod
from .scheduler import TournamentScheduler
from .spreadsheet import build_spreadsheet

if typing.TYPE_CHECKING:
    from core import Akande, AkandeCtx, AkandeItx
    from database.services.tournament import (
        HallOfFameEntry,
        SpreadsheetRecord,
        TournamentInfo,
        TournamentMap,
    )

_CATEGORY_CHOICES = [
    app_commands.Choice(name=c, value=c) for c in models.Category.playable()
]
_RANK_CHOICES = [
    app_commands.Choice(name=r, value=r)
    for r in ("All", "Unranked", "Gold", "Diamond", "Grandmaster")
]


def _resolve_dates(start: str, end: str) -> tuple[datetime.datetime, datetime.datetime]:
    """Parse both dates as of now; ``end`` is an offset rebased onto start.

    Relative inputs ("in 1 minute") resolve against the moment of parsing,
    so callers re-invoke this when the times are actually committed.
    """
    try:
        start_dt = transformers.parse_future_date(start)
        end_dt = transformers.parse_future_date(end)
    except ValueError:
        raise UserFacingError(
            "Could not understand that date. Try `tomorrow 18:00` or "
            "`2026-07-10 15:00 UTC`."
        ) from None
    if start_dt <= discord.utils.utcnow():
        raise UserFacingError("The start time is in the past.")
    # 'end' was parsed relative to now; rebase the same offset onto start
    # so "in 7 days" means 7 days of runtime, not 7 days from today.
    return start_dt, end_dt - discord.utils.utcnow() + start_dt


def is_org() -> typing.Any:
    def predicate(itx: AkandeItx) -> bool:
        assert isinstance(itx.user, discord.Member)
        org_role = itx.client.config.roles.tournament.organizer
        if not any(role.id == org_role for role in itx.user.roles):
            raise UserFacingError("This command is for Tournament Organizers only.")
        return True

    return app_commands.check(predicate)


class TournamentCog(BaseCog, name="tournament", description="Tournament commands."):
    """Tournament"""

    _tournament = app_commands.Group(
        name="tournament", description="Tournament commands"
    )
    _org = app_commands.Group(
        name="tournament-org", description="Tournament organizer commands"
    )
    _missions = app_commands.Group(
        name="missions", description="Manage tournament missions", parent=_org
    )

    def __init__(self, bot: Akande) -> None:
        super().__init__(bot)
        self.scheduler = TournamentScheduler(self)

    async def cog_load(self) -> None:
        self.bot.add_view(t_views.TournamentRolesView())
        self.bot.add_view(t_views.InfoPanelView(self.bot.config))
        self.scheduler.reschedule()

    async def cog_unload(self) -> None:
        self.scheduler.cancel()

    # --- helpers --------------------------------------------------------------

    async def _active_tournament(self) -> TournamentInfo:
        async with self.bot.acquire() as svc:
            info = await svc.tournament.fetch_latest_tournament_info()
        if info is None or not info.active:
            raise UserFacingError("There is no active tournament.")
        return info

    def _category_role_ids(self) -> dict[str, int]:
        roles = self.bot.config.roles.tournament
        return {
            models.Category.TIME_ATTACK: roles.time_attack,
            models.Category.MILDCORE: roles.mildcore,
            models.Category.HARDCORE: roles.hardcore,
            models.Category.BONUS: roles.bonus,
            "Trifecta": roles.trifecta,
        }

    def _mention_string(self, keys: typing.Iterable[str]) -> str:
        role_ids = self._category_role_ids()
        return "".join(f"<@&{role_ids[key]}>" for key in keys if key in role_ids)

    def _text_channel(self, channel_id: int) -> discord.TextChannel:
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise UserFacingError("A configured tournament channel is unavailable.")
        return channel

    # --- lifecycle transitions (scheduler entry points) ------------------------

    async def _set_submissions_channel_open(self, open_: bool) -> None:
        guild = self.bot.get_guild(self.bot.config.guild)
        assert guild
        channel = self._text_channel(self.bot.config.channels.tournament.submissions)
        overwrite = channel.overwrites_for(guild.default_role)
        overwrite.update(send_messages=open_)
        await channel.set_permissions(
            guild.default_role,
            overwrite=overwrite,
            reason="Tournament started." if open_ else "Tournament ended.",
        )

    async def _end_scheduled_event(self) -> None:
        guild = self.bot.get_guild(self.bot.config.guild)
        assert guild
        for event in await guild.fetch_scheduled_events():
            if event.name != t_views.TOURNAMENT_TITLE:
                continue
            if event.status is discord.EventStatus.active:
                await event.end()
            elif event.status is discord.EventStatus.scheduled:
                await event.cancel()

    async def start_tournament(self, tournament_id: int) -> None:
        """Scheduler 'start' transition: activate, open submissions, announce."""
        logger.info("Starting tournament {}", tournament_id)
        async with self.bot.acquire() as svc:
            info = await svc.tournament.fetch_latest_tournament_info()
            if info is None or info.id != tournament_id or info.active:
                logger.warning(
                    "Stale start transition for tournament {}; skipping",
                    tournament_id,
                )
                return
            maps = await svc.tournament.fetch_tournament_maps(tournament_id)
            await svc.tournament.set_tournament_active(tournament_id, True)

        await self._set_submissions_channel_open(True)
        mentions = self._mention_string([m.category for m in maps] + ["Trifecta"])
        announcements = self._text_channel(
            self.bot.config.channels.tournament.announcements
        )
        await announcements.send(
            view=views.Card(
                t_views.announcement_body(maps, info.start, info.end, mentions)
            ),
            file=discord.File("assets/event_banner.png", filename="banner.png"),
            allowed_mentions=discord.AllowedMentions(roles=True),
        )

    async def end_tournament(self, tournament_id: int) -> None:
        """Scheduler 'end' transition: XP -> spreadsheet -> announcements -> HoF.

        DB work (deactivate + XP upsert) is transactional and happens before
        any Discord posting, so a Discord failure can't half-award XP.
        """
        logger.info("Ending tournament {}", tournament_id)
        async with self.bot.acquire() as svc:
            info = await svc.tournament.fetch_latest_tournament_info()
            if info is None or info.id != tournament_id or not info.active:
                logger.warning(
                    "Stale end transition for tournament {}; skipping",
                    tournament_id,
                )
                return
            season = await svc.tournament.fetch_active_season_number()
            if season is None:
                raise RuntimeError("No active season; cannot award XP.")
            maps = await svc.tournament.fetch_tournament_maps(tournament_id)
            lb_rows = await svc.tournament.fetch_leaderboard_xp_rows(tournament_id)
            mission_rows = await svc.tournament.fetch_difficulty_mission_rows(
                tournament_id
            )
            general = await svc.tournament.fetch_general_mission(tournament_id)
            top_ids: list[int] = []
            if general and general.type == models.MissionType.TOP_PLACEMENT:
                rows = await svc.tournament.fetch_top_placement_users(
                    tournament_id, int(general.target or 0)
                )
                top_ids = [row.user_id for row in rows]
            spreadsheet_records = await svc.tournament.fetch_spreadsheet_records(
                tournament_id
            )

        totals = xp_mod.compute_xp(lb_rows, mission_rows)
        if general is not None:
            xp_mod.apply_general_mission(totals, general, top_ids)

        async with self.bot.acquire() as svc, transaction(svc.db):
            await svc.tournament.set_tournament_active(tournament_id, False)
            if totals:
                await svc.xp.add_xp_bulk(
                    [(uid, user.total, season) for uid, user in totals.items()]
                )

        # Everything below is best-effort: XP is already safely persisted.
        with contextlib.suppress(discord.HTTPException, UserFacingError):
            await self._set_submissions_channel_open(False)

        # A natural end coincides with the guild event's own end time, but an
        # early end leaves the event running; close it out either way.
        with contextlib.suppress(discord.HTTPException):
            await self._end_scheduled_event()

        mentions = self._mention_string([m.category for m in maps] + ["Trifecta"])
        with contextlib.suppress(discord.HTTPException, UserFacingError):
            announcements = self._text_channel(
                self.bot.config.channels.tournament.announcements
            )
            await announcements.send(
                view=views.Card(t_views.end_body(mentions)),
                allowed_mentions=discord.AllowedMentions(roles=True),
            )

        try:
            await self._post_hall_of_fame(
                tournament_id, info, maps, totals, spreadsheet_records
            )
        except (discord.HTTPException, UserFacingError) as e:
            logger.opt(exception=True).error(
                "Hall of Fame posting failed for tournament {}: {}",
                tournament_id,
                e,
            )

    async def _post_hall_of_fame(
        self,
        tournament_id: int,
        info: TournamentInfo,
        maps: list[TournamentMap],
        totals: dict[int, xp_mod.UserXP],
        spreadsheet_records: list[SpreadsheetRecord],
    ) -> None:
        per_category: dict[str, list[HallOfFameEntry]] = {}
        async with self.bot.acquire() as svc:
            for map_ in maps:
                per_category[map_.category] = await svc.tournament.fetch_hall_of_fame(
                    tournament_id, map_.category
                )
        hof_channel = self._text_channel(
            self.bot.config.channels.tournament.hall_of_fame
        )
        hof_message = await hof_channel.send(
            view=views.Card(t_views.hall_of_fame_body(per_category))
        )
        thread = await hof_message.create_thread(name="Records Archive")
        for page in t_views.archive_pages(per_category):
            await thread.send(view=views.Card(page))
        buffer = build_spreadsheet(spreadsheet_records, totals)
        await thread.send(
            file=discord.File(
                buffer,
                filename=f"DPK_Tournament_{info.end:%d-%m-%Y}.xlsx",
            )
        )

    # --- submissions ------------------------------------------------------------

    async def _submit(
        self,
        itx: AkandeItx,
        category: models.Category,
        screenshot: discord.Attachment,
        record: float,
    ) -> None:
        info = await self._active_tournament()
        async with itx.client.acquire() as svc:
            maps = await svc.tournament.fetch_tournament_maps(info.id)
            if category not in {m.category for m in maps}:
                raise UserFacingError(f"This tournament has no {category} map.")
            previous = await svc.tournament.fetch_latest_tournament_record(
                itx.user.id, category, info.id
            )
        if previous is not None and previous < record:
            raise UserFacingError(
                "Your record must be faster than your previous submission."
            )

        sub = t_views.TournamentSubmission(
            user_name=itx.user.display_name,
            category=category,
            record=record,
            screenshot_url=screenshot.url,
        )
        confirmed = await views.Confirm.prompt(
            itx,
            *t_views.tournament_submission_body(
                sub, header="Tournament Submission - Is this correct?"
            ),
            defer_on_confirm=True,
        )
        if not confirmed:
            return

        channel = self._text_channel(self.bot.config.channels.tournament.submissions)
        sub = structs.replace(sub, screenshot_url="attachment://image.png")
        message = await channel.send(
            view=views.Card(
                t_views.tournament_submission_body(sub, header=f"{category} Submission")
            ),
            file=await screenshot.to_file(filename="image.png"),
        )
        try:
            async with itx.client.acquire() as svc, transaction(svc.db):
                await svc.users.create_if_missing(itx.user.id, itx.user.display_name)
                await svc.tournament.insert_tournament_record(
                    user_id=itx.user.id,
                    category=category,
                    record=record,
                    screenshot=message.jump_url,
                )
        except Exception:
            with contextlib.suppress(discord.HTTPException):
                await message.delete()
            raise

        await itx.edit_original_response(
            view=views.Card([f"✅ Record submitted!\n{message.jump_url}"])
        )
        await self._warn_if_unranked(itx, category)

    async def _warn_if_unranked(
        self, itx: AkandeItx, category: models.Category
    ) -> None:
        if category is models.Category.BONUS:
            return
        async with itx.client.acquire() as svc:
            value = await svc.tournament.fetch_user_rank_value(itx.user.id, category)
        if value != models.Rank.UNRANKED:
            return
        org_chat = self._text_channel(self.bot.config.channels.tournament.org_chat)
        await org_chat.send(
            view=views.Card(
                [
                    f"{itx.user.mention} is **UNRANKED** in {category}.\n"
                    "Please change this user's rank before the end of the "
                    "tournament!"
                ]
            ),
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @app_commands.command(name="ta", description="Submit a Time Attack record")
    @app_commands.describe(
        screenshot="Screenshot proof", record="Record time ([HH:][MM:]SS.ss)"
    )
    async def ta(
        self,
        itx: AkandeItx,
        screenshot: discord.Attachment,
        record: app_commands.Transform[float, transformers.RecordTransformer],
    ) -> None:
        await self._submit(itx, models.Category.TIME_ATTACK, screenshot, record)

    @app_commands.command(name="mc", description="Submit a Mildcore record")
    @app_commands.describe(
        screenshot="Screenshot proof", record="Record time ([HH:][MM:]SS.ss)"
    )
    async def mc(
        self,
        itx: AkandeItx,
        screenshot: discord.Attachment,
        record: app_commands.Transform[float, transformers.RecordTransformer],
    ) -> None:
        await self._submit(itx, models.Category.MILDCORE, screenshot, record)

    @app_commands.command(name="hc", description="Submit a Hardcore record")
    @app_commands.describe(
        screenshot="Screenshot proof", record="Record time ([HH:][MM:]SS.ss)"
    )
    async def hc(
        self,
        itx: AkandeItx,
        screenshot: discord.Attachment,
        record: app_commands.Transform[float, transformers.RecordTransformer],
    ) -> None:
        await self._submit(itx, models.Category.HARDCORE, screenshot, record)

    @app_commands.command(name="bo", description="Submit a Bonus record")
    @app_commands.describe(
        screenshot="Screenshot proof", record="Record time ([HH:][MM:]SS.ss)"
    )
    async def bo(
        self,
        itx: AkandeItx,
        screenshot: discord.Attachment,
        record: app_commands.Transform[float, transformers.RecordTransformer],
    ) -> None:
        await self._submit(itx, models.Category.BONUS, screenshot, record)

    @_tournament.command(name="submit", description="Submit a tournament record")
    @app_commands.describe(
        category="Tournament category",
        screenshot="Screenshot proof",
        record="Record time ([HH:][MM:]SS.ss)",
    )
    @app_commands.choices(category=_CATEGORY_CHOICES)
    async def submit(
        self,
        itx: AkandeItx,
        category: str,
        screenshot: discord.Attachment,
        record: app_commands.Transform[float, transformers.RecordTransformer],
    ) -> None:
        await self._submit(itx, models.Category(category), screenshot, record)

    @_tournament.command(
        name="leaderboard", description="View a tournament category leaderboard"
    )
    @app_commands.describe(category="Tournament category", rank="Filter by rank")
    @app_commands.choices(category=_CATEGORY_CHOICES, rank=_RANK_CHOICES)
    async def leaderboard(
        self, itx: AkandeItx, category: str, rank: str = "All"
    ) -> None:
        rank_filter = None if rank == "All" else rank
        async with itx.client.acquire() as svc:
            entries = await svc.tournament.fetch_tournament_leaderboard(
                category, rank_filter
            )
        if not entries:
            raise UserFacingError("No records found.")
        pages = t_views.tournament_leaderboard_pages(entries, category, rank_filter)
        await views.Paginator(itx, pages).start()

    @_tournament.command(
        name="delete", description="Delete the latest tournament submission"
    )
    @app_commands.describe(
        category="Tournament category",
        user="Whose submission (organizers only; defaults to you)",
    )
    @app_commands.choices(category=_CATEGORY_CHOICES)
    async def delete(
        self,
        itx: AkandeItx,
        category: str,
        user: discord.Member | None = None,
    ) -> None:
        info = await self._active_tournament()
        target = user or itx.user
        if target != itx.user:
            org_role = itx.client.config.roles.tournament.organizer
            assert isinstance(itx.user, discord.Member)
            if not any(role.id == org_role for role in itx.user.roles):
                raise UserFacingError(
                    "Only organizers can delete other players' submissions."
                )
        confirmed = await views.Confirm.prompt(
            itx,
            f"Delete {target.mention}'s latest **{category}** submission?",
        )
        if not confirmed:
            return
        async with itx.client.acquire() as svc:
            await svc.tournament.delete_latest_tournament_record(
                target.id, category, info.id
            )

    # --- org: lifecycle ---------------------------------------------------------

    @_org.command(name="start", description="Create and schedule a tournament")
    @app_commands.describe(
        start="When the tournament starts (e.g. 'tomorrow 18:00')",
        end="How long after start it ends (e.g. 'in 7 days')",
    )
    @is_org()
    async def start(self, itx: AkandeItx, start: str, end: str) -> None:
        async with itx.client.acquire() as svc:
            if await svc.tournament.has_upcoming_or_active_tournament():
                raise UserFacingError("A tournament is already scheduled or active.")
        start_dt, end_dt = _resolve_dates(start, end)

        wizard = t_views.StartWizard(itx, start_dt, end_dt)
        await itx.response.send_message(view=wizard, ephemeral=True)
        await wizard.wait()
        if not wizard.confirmed:
            return
        # Re-resolve so relative inputs ("in 1 minute") count from
        # confirmation; the wizard may outlive the original offset.
        start_dt, end_dt = _resolve_dates(start, end)

        async with itx.client.acquire() as svc, transaction(svc.db):
            tournament_id = await svc.tournament.create_tournament(
                start=start_dt, end=end_dt, active=False, bracket=False
            )
            await svc.tournament.add_tournament_maps(
                [
                    (tournament_id, entry.code, entry.level, entry.creator, category)
                    for category, entry in wizard.maps.items()
                ]
            )

        assert itx.guild
        announcements = self._text_channel(
            self.bot.config.channels.tournament.announcements
        )
        chat = self._text_channel(self.bot.config.channels.tournament.chat)
        event_url: str | None = None
        try:
            banner = pathlib.Path("assets/event_banner.png").read_bytes()
            event = await itx.guild.create_scheduled_event(
                name=t_views.TOURNAMENT_TITLE,
                start_time=start_dt,
                end_time=end_dt,
                privacy_level=discord.PrivacyLevel.guild_only,
                entity_type=discord.EntityType.external,
                location=f"{announcements.mention} {chat.mention}",
                image=banner,
                description="Submit your best times in the tournament for XP!",
            )
            await announcements.send(event.url)
            event_url = event.url
        except discord.HTTPException as e:
            logger.warning("Scheduled event creation failed: {}", e)

        self.scheduler.reschedule()
        summary = f"✅ Tournament #{tournament_id} scheduled."
        if event_url:
            summary += f"\n{event_url}"
        await itx.edit_original_response(view=views.Card([summary]))

    @_org.command(name="end", description="End the active tournament early")
    @is_org()
    async def end(self, itx: AkandeItx) -> None:
        info = await self._active_tournament()
        confirmed = await views.Confirm.prompt(
            itx,
            "## End Tournament Early",
            f"The tournament is scheduled to end "
            f"{discord.utils.format_dt(info.end, 'R')}.\n"
            "End it now? XP is awarded and results are posted immediately.",
            defer_on_confirm=True,
        )
        if not confirmed:
            return
        async with itx.client.acquire() as svc:
            await svc.tournament.end_tournament_now(info.id)
        self.scheduler.reschedule()
        await itx.edit_original_response(
            view=views.Card(["✅ Tournament is ending now."])
        )

    # --- org: player management ---------------------------------------------------

    @_org.command(name="rank", description="Change a player's category rank")
    @app_commands.describe(member="Player", category="Category", rank="New rank")
    @app_commands.choices(
        category=[
            app_commands.Choice(name=c, value=c)
            for c in ("Time Attack", "Mildcore", "Hardcore")
        ],
        rank=[
            app_commands.Choice(name=r, value=r)
            for r in ("Unranked", "Gold", "Diamond", "Grandmaster")
        ],
    )
    @is_org()
    async def rank(
        self, itx: AkandeItx, member: discord.Member, category: str, rank: str
    ) -> None:
        async with itx.client.acquire() as svc:
            await svc.users.create_if_missing(member.id, member.display_name)
            await svc.xp.set_rank(member.id, category, rank)
        await itx.response.send_message(
            f"{member.mention}'s {category} rank is now **{rank}**.",
            ephemeral=True,
        )

    @_org.command(name="xp", description="Grant or remove XP")
    @app_commands.describe(member="Player", xp="XP amount (negative to remove)")
    @is_org()
    async def xp(self, itx: AkandeItx, member: discord.Member, xp: int) -> None:
        async with itx.client.acquire() as svc:
            season = await svc.tournament.fetch_active_season_number()
            if season is None:
                raise UserFacingError("No active season exists.")
            await svc.users.create_if_missing(member.id, member.display_name)
            total = await svc.xp.add_xp(member.id, xp, season)
        await itx.response.send_message(
            f"{member.mention} was given {xp} XP.\n"
            f"New total: **{total}** (was {total - xp}).",
            ephemeral=True,
        )

    # --- org: announcements ----------------------------------------------------------

    @_org.command(
        name="announcement", description="Post a custom tournament announcement"
    )
    @is_org()
    async def announcement(self, itx: AkandeItx) -> None:
        modal = t_views.AnnouncementModal()
        await itx.response.send_modal(modal)
        if await modal.wait() or modal.itx is None:
            return

        thumbnail = modal.thumbnail.values[0] if modal.thumbnail.values else None
        image = modal.image.values[0] if modal.image.values else None
        body: list[str | ui.Item] = [
            f"## {modal.title_input.value}",
            modal.content.value,
        ]
        if thumbnail:
            body[0] = ui.Section(
                ui.TextDisplay(f"## {modal.title_input.value}"),
                accessory=ui.Thumbnail(media="attachment://thumb.png"),
            )
        if image:
            gallery = ui.MediaGallery()
            gallery.add_item(media="attachment://image.png")
            body.append(gallery)

        # File objects are single-use; both the preview and the announcement
        # upload their own copies to satisfy the attachment:// references.
        async def to_files() -> list[discord.File]:
            files: list[discord.File] = []
            if thumbnail:
                files.append(await thumbnail.to_file(filename="thumb.png"))
            if image:
                files.append(await image.to_file(filename="image.png"))
            return files

        published, selected = await t_views.RolePingPrompt.prompt(
            modal.itx, *body, files=await to_files()
        )
        if not published:
            return
        mentions = self._mention_string(selected)
        announcements = self._text_channel(
            self.bot.config.channels.tournament.announcements
        )
        await announcements.send(
            view=views.Card(([mentions] if mentions else []) + body),
            files=await to_files(),
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        await modal.itx.edit_original_response(
            view=views.Card(["✅ Announcement posted."])
        )

    # --- org: seasons ------------------------------------------------------------------

    @_org.command(name="seasons", description="Manage tournament seasons")
    @is_org()
    async def seasons(self, itx: AkandeItx) -> None:
        async with itx.client.acquire() as svc:
            all_seasons = await svc.tournament.fetch_seasons()
        view = t_views.SeasonManagerView(itx, all_seasons)
        await itx.response.send_message(view=view, ephemeral=True)

    # --- org: missions --------------------------------------------------------------------

    async def _active_or_upcoming_tournament(self) -> TournamentInfo:
        """Missions are managed before and during a tournament."""
        async with self.bot.acquire() as svc:
            info = await svc.tournament.fetch_latest_tournament_info()
        if info is None or (not info.active and not info.needs_start_task):
            raise UserFacingError("There is no active or upcoming tournament.")
        return info

    @_missions.command(name="add", description="Add or overwrite a mission")
    @app_commands.describe(
        category="Mission category (General for tournament-wide)",
        difficulty="Mission difficulty",
        mission_type="Mission type",
        target="Target (e.g. '1:23.45', '5000', '3 Hard')",
    )
    @app_commands.choices(
        category=[app_commands.Choice(name=c, value=c) for c in models.Category],
        difficulty=[
            app_commands.Choice(name=d, value=d) for d in models.MissionDifficulty
        ],
        mission_type=[app_commands.Choice(name=t, value=t) for t in models.MissionType],
    )
    @is_org()
    async def missions_add(
        self,
        itx: AkandeItx,
        category: str,
        difficulty: str,
        mission_type: str,
        target: str,
    ) -> None:
        info = await self._active_or_upcoming_tournament()
        cat = models.Category(category)
        mtype = models.MissionType(mission_type)
        if cat is models.Category.GENERAL and mtype not in models.MissionType.general():
            raise UserFacingError(
                "General missions must be XP Threshold, Mission Threshold, "
                "or Top Placement."
            )
        if (
            cat is not models.Category.GENERAL
            and mtype not in models.MissionType.difficulty()
        ):
            raise UserFacingError("Category missions must be Sub Time or Completion.")
        target_value, extra = models.parse_mission_target(mtype, target)

        async with itx.client.acquire() as svc:
            existing = await svc.tournament.fetch_mission(cat, difficulty, info.id)
        prefix = (
            "A mission already exists for this category and difficulty. Overwrite it?"
            if existing
            else "Is this correct?"
        )
        confirmed = await views.Confirm.prompt(
            itx,
            f"{prefix}\n\n"
            f"`Category` {cat}\n"
            f"`Difficulty` {difficulty}\n"
            f"`Type` {mtype}\n"
            f"`Target` {target_value}\n"
            f"`Extra` {extra or '-'}",
        )
        if not confirmed:
            return
        async with itx.client.acquire() as svc:
            await svc.tournament.upsert_mission(
                tournament_id=info.id,
                mission_type=mtype,
                target=target_value,
                difficulty=difficulty,
                category=cat,
                extra_target=extra,
            )

    @_missions.command(name="remove", description="Remove missions")
    @is_org()
    async def missions_remove(self, itx: AkandeItx) -> None:
        info = await self._active_or_upcoming_tournament()
        async with itx.client.acquire() as svc:
            missions = await svc.tournament.fetch_missions_with_maps(info.id)
        if not missions:
            raise UserFacingError("No missions exist for this tournament.")
        view = t_views.MissionRemoveView(itx, missions)
        await itx.response.send_message(view=view, ephemeral=True)

    @_missions.command(name="publish", description="Publish missions to announcements")
    @is_org()
    async def missions_publish(self, itx: AkandeItx) -> None:
        info = await self._active_or_upcoming_tournament()
        async with itx.client.acquire() as svc:
            missions = await svc.tournament.fetch_missions_with_maps(info.id)
        if not missions:
            raise UserFacingError("No missions exist for this tournament.")
        body = t_views.missions_body(missions, info.end)
        published, selected = await t_views.RolePingPrompt.prompt(itx, *body)
        if not published:
            return
        mentions = self._mention_string(selected)
        announcements = self._text_channel(
            self.bot.config.channels.tournament.announcements
        )
        await announcements.send(
            view=views.Card(([mentions] if mentions else []) + body),
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        await itx.edit_original_response(view=views.Card(["✅ Missions published."]))

    # --- owner prefix commands -------------------------------------------------------------

    @commands.command(name="tournament-info-panel")
    @commands.guild_only()
    @commands.is_owner()
    async def post_info_panel(self, ctx: AkandeCtx) -> None:
        """Post the persistent tournament info panel in this channel."""
        await ctx.send(view=t_views.InfoPanelView(self.bot.config))

    @commands.command(name="tournament-roles-panel")
    @commands.guild_only()
    @commands.is_owner()
    async def post_roles_panel(self, ctx: AkandeCtx) -> None:
        """Post the persistent tournament role-select panel in this channel."""
        await ctx.send(view=t_views.TournamentRolesView())

    @commands.command(name="tournament-end-now")
    @commands.guild_only()
    @commands.is_owner()
    async def end_now(self, ctx: AkandeCtx) -> None:
        """Manual escape hatch: run the end-of-tournament pipeline."""
        async with self.bot.acquire() as svc:
            info = await svc.tournament.fetch_latest_tournament_info()
        if info is None or not info.active:
            await ctx.send("No active tournament.")
            return
        await self.end_tournament(info.id)
        await ctx.send("Tournament ended.")
