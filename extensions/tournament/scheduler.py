from __future__ import annotations

import asyncio
import typing

import discord
from loguru import logger

if typing.TYPE_CHECKING:
    from .cog import TournamentCog

__all__ = ("TournamentScheduler",)


class TournamentScheduler:
    """One asyncio task; the DB is the only state.

    Every iteration re-reads the latest tournament and either fires a missed
    transition, sleeps until the next boundary, or exits. Because the next
    action is always recomputed from the DB, restarts/reschedules can't
    double-fire and a downed bot fires missed transitions on the next boot.
    """

    def __init__(self, cog: TournamentCog) -> None:
        self._cog = cog
        self._task: asyncio.Task[None] | None = None

    def reschedule(self) -> None:
        """(Re)start the loop; call after any tournament state change."""
        self.cancel()
        self._task = asyncio.create_task(self._run())

    def cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        await self._cog.bot.wait_until_ready()
        while True:
            async with self._cog.bot.acquire() as svc:
                info = await svc.tournament.fetch_latest_tournament_info()
            if info is None:
                return
            if info.needs_start_now:
                if not await self._fire("start", self._cog.start_tournament, info.id):
                    return
            elif info.needs_end_now:
                if not await self._fire("end", self._cog.end_tournament, info.id):
                    return
            elif not info.active and info.needs_start_task:
                logger.info("Tournament {} start scheduled for {}", info.id, info.start)
                await discord.utils.sleep_until(info.start)
            elif info.active and info.needs_end_task:
                logger.info("Tournament {} end scheduled for {}", info.id, info.end)
                await discord.utils.sleep_until(info.end)
            else:
                return

    async def _fire(
        self,
        name: str,
        transition: typing.Callable[[int], typing.Awaitable[None]],
        tournament_id: int,
    ) -> bool:
        """Run a transition; False stops the loop.

        Stopping on failure avoids a hot retry spin when a transition fails
        before flipping the DB flag it's gated on.
        """
        try:
            await transition(tournament_id)
        except Exception:
            logger.opt(exception=True).error(
                "Tournament {} transition '{}' failed", tournament_id, name
            )
            return False
        return True
