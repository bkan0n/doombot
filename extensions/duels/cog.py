from __future__ import annotations

import datetime
import typing

import discord
from discord import app_commands, ui
from loguru import logger

from database.services import transaction
from utilities import transformers, views
from utilities.errors import UserFacingError
from utilities.formatting import pretty_record

from .._base import BaseCog
from . import models
from . import views as d_views
from .scheduler import DuelScheduler

if typing.TYPE_CHECKING:
    from core import Akande, AkandeItx
    from database.services.duels import DuelActivation, DuelInfo, DuelPlayerInfo

_READY_WINDOW = datetime.timedelta(hours=24)
_LENGTH_CHOICES = [
    app_commands.Choice(name=f"{n} Day" if n == 1 else f"{n} Days", value=n)
    for n in range(1, 8)
]


class DuelCog(BaseCog, name="duels", description="XP-wagered 1v1 duels."):
    """Duels"""

    duel = app_commands.Group(
        name="duel", description="XP-wagered 1v1 time trials", guild_only=True
    )

    def __init__(self, bot: Akande) -> None:
        super().__init__(bot)
        self.scheduler = DuelScheduler(self)

    async def cog_load(self) -> None:
        async with self.bot.acquire() as svc:
            pending = await svc.duels.fetch_pending_duels()
            rosters = [await svc.duels.fetch_players(d.id) for d in pending]
        for duel, players in zip(pending, rosters, strict=True):
            self.bot.add_view(
                d_views.ReadyUpView(self, duel, players), message_id=duel.message_id
            )
        self.scheduler.reschedule()

    async def cog_unload(self) -> None:
        self.scheduler.cancel()

    # --- commands -------------------------------------------------------------

    @duel.command(name="challenge", description="Challenge a player to a duel")
    @app_commands.choices(length=_LENGTH_CHOICES)
    @app_commands.describe(
        user="Who you're challenging",
        length="How long the duel runs once both players ready up",
        wager="XP both players stake; winner takes it from the loser",
        map_code="Map to duel on (random if omitted)",
        level="Level to duel on (random if omitted)",
    )
    async def challenge(
        self,
        itx: AkandeItx,
        user: discord.Member,
        length: int,
        wager: app_commands.Range[int, 1],
        map_code: app_commands.Transform[str, transformers.CodeTransformer]
        | None = None,
        level: app_commands.Transform[str, transformers.MapLevelTransformer]
        | None = None,
    ) -> None:
        await itx.response.defer(ephemeral=True)
        if user.bot:
            raise UserFacingError("You can't duel a bot.")
        if user.id == itx.user.id:
            raise UserFacingError("You can't duel yourself.")
        if level is not None and map_code is None:
            raise UserFacingError("A level requires a map code.")

        forum = itx.guild and itx.guild.get_channel(self.bot.config.channels.duels)
        if not isinstance(forum, discord.ForumChannel):
            raise UserFacingError("The duels channel is not configured.")

        async with self.bot.acquire() as svc:
            season = await svc.tournament.fetch_active_season_number()
            if season is None:
                raise UserFacingError("No active season exists.")
            if await svc.duels.is_either_in_open_duel(itx.user.id, user.id):
                raise UserFacingError("One of you is already in an open duel.")
            if not await svc.duels.check_xp(itx.user.id, user.id, wager, season):
                raise UserFacingError(
                    f"Both players need at least {wager} XP this season."
                )
            if map_code is None:
                map_code = await svc.duels.fetch_random_map_code()
                if map_code is None:
                    raise UserFacingError("There are no maps to duel on.")
            if level is None:
                level = await svc.duels.fetch_random_level(map_code)
                if level is None:
                    raise UserFacingError("That map has no levels.")

            created = await forum.create_thread(
                name=f"{itx.user.name} vs. {user.name}",
                view=views.Card(["⚔️ Setting up the duel..."]),
            )
            duel_id = await svc.duels.create_duel(
                thread_id=created.thread.id,
                message_id=created.message.id,
                map_code=map_code,
                level=level,
                wager=wager,
                season=season,
                duration=datetime.timedelta(days=length),
                ready_deadline=discord.utils.utcnow() + _READY_WINDOW,
                player_one=itx.user.id,
                player_two=user.id,
            )
            duel = await svc.duels.fetch_duel(duel_id)
            players = await svc.duels.fetch_players(duel_id)

        assert duel is not None
        await created.message.edit(view=d_views.ReadyUpView(self, duel, players))
        self.scheduler.reschedule()
        await itx.followup.send(
            f"Duel created: {created.thread.jump_url}", ephemeral=True
        )

    @duel.command(name="submit", description="Submit a time for your active duel")
    @app_commands.describe(
        record="Your time, e.g. 12.34 or 1:02.50",
        screenshot="Proof of the run",
    )
    async def submit(
        self,
        itx: AkandeItx,
        record: app_commands.Transform[float, transformers.RecordTransformer],
        screenshot: discord.Attachment,
    ) -> None:
        duel, players = await self._duel_here(itx, status="active")
        me = discord.utils.get(players, user_id=itx.user.id)
        if me is None:
            raise UserFacingError("You aren't a player in this duel.")
        if not (screenshot.content_type or "").startswith("image/"):
            raise UserFacingError("The screenshot must be an image.")

        if me.record is None or record < me.record:
            improved, note = True, ""
        else:
            improved, note = (
                False,
                f"\n-# Existing best {pretty_record(me.record)} kept.",
            )
        file = await screenshot.to_file()
        gallery = ui.MediaGallery(
            discord.MediaGalleryItem(f"attachment://{file.filename}")
        )
        card = views.Card(
            [f"### {itx.user.display_name} — {pretty_record(record)}{note}", gallery]
        )
        await itx.response.send_message(view=card, file=file)
        if improved:
            message = await itx.original_response()
            async with self.bot.acquire() as svc:
                await svc.duels.submit_record(
                    duel.id, itx.user.id, record, message.jump_url
                )

    @duel.command(name="cancel", description="Cancel a duel that hasn't started")
    async def cancel(self, itx: AkandeItx) -> None:
        duel, players = await self._duel_here(itx, status="pending")
        if all(p.user_id != itx.user.id for p in players):
            raise UserFacingError("You aren't a player in this duel.")
        if not await views.Confirm.prompt(itx, "Cancel this duel?"):
            return
        async with self.bot.acquire() as svc:
            cancelled = await svc.duels.cancel_duel(duel.id)
        if not cancelled:
            raise UserFacingError("This duel can no longer be cancelled.")
        self.scheduler.reschedule()
        thread = await self._fetch_thread(duel.thread_id)
        if thread is not None:
            await thread.send(view=views.Card(["🚫 Duel cancelled by a player."]))
            await thread.edit(archived=True, locked=True)

    # --- transitions ------------------------------------------------------------

    async def announce_activation(
        self, thread: discord.Thread, activation: DuelActivation
    ) -> None:
        await thread.send(view=views.Card([d_views.activation_text(activation)]))
        self.scheduler.reschedule()

    async def handle_deadline(self, duel_id: int) -> None:
        """Ready deadline hit: activate if both readied (self-heal), else cancel."""
        async with self.bot.acquire() as svc:
            activation = await svc.duels.try_activate(duel_id)
            cancelled = (
                False
                if activation is not None
                else await svc.duels.cancel_duel(duel_id)
            )
            duel = await svc.duels.fetch_duel(duel_id)
        assert duel is not None
        thread = await self._fetch_thread(duel.thread_id)
        if thread is None:
            logger.warning("Duel {} thread {} is gone", duel_id, duel.thread_id)
            return
        if activation is not None:
            await self.announce_activation(thread, activation)
        elif cancelled:
            await thread.send(
                view=views.Card(["🚫 Duel cancelled — not everyone readied in time."])
            )
            await thread.edit(archived=True, locked=True)

    async def handle_end(self, duel_id: int) -> None:
        async with self.bot.acquire() as svc:
            duel = await svc.duels.fetch_duel(duel_id)
            assert duel is not None and duel.status == "active"
            players = await svc.duels.fetch_players(duel_id)
            player_one, player_two = players
            outcome = models.decide(player_one.record, player_two.record)
            result_one, result_two = models.RESULTS[outcome]
            async with transaction(svc.db):
                await svc.duels.complete_duel(
                    duel_id,
                    [
                        (result_one, duel_id, player_one.user_id),
                        (result_two, duel_id, player_two.user_id),
                    ],
                )
                for player, result in (
                    (player_one, result_one),
                    (player_two, result_two),
                ):
                    if result:
                        await svc.xp.add_xp(
                            player.user_id, result * duel.wager, duel.season
                        )
        thread = await self._fetch_thread(duel.thread_id)
        if thread is None:
            logger.warning("Duel {} thread {} is gone", duel_id, duel.thread_id)
            return
        await thread.send(view=views.Card(d_views.result_items(duel, players, outcome)))
        await thread.edit(archived=True, locked=True)

    # --- helpers ----------------------------------------------------------------

    async def _duel_here(
        self, itx: AkandeItx, *, status: str
    ) -> tuple[DuelInfo, list[DuelPlayerInfo]]:
        if not isinstance(itx.channel, discord.Thread):
            raise UserFacingError("Use this inside a duel thread.")
        async with self.bot.acquire() as svc:
            duel = await svc.duels.fetch_duel_by_thread(itx.channel.id)
            if duel is None:
                raise UserFacingError("This isn't a duel thread.")
            if duel.status != status:
                raise UserFacingError(f"This duel isn't {status}.")
            players = await svc.duels.fetch_players(duel.id)
        return duel, players

    async def _fetch_thread(self, thread_id: int) -> discord.Thread | None:
        channel = self.bot.get_channel(thread_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(thread_id)
            except discord.HTTPException:
                return None
        return channel if isinstance(channel, discord.Thread) else None
