from __future__ import annotations

import asyncio
import typing

import discord
from loguru import logger

if typing.TYPE_CHECKING:
    from database.services.duels import DuelTransition

    from .cog import DuelCog

__all__ = ("DuelScheduler",)


class DuelScheduler:
    """One asyncio task; the DB is the only state.

    Every iteration re-reads the nearest boundary across all open duels
    (pending ready-deadlines and active end times) and either fires a due
    transition, sleeps until the next boundary, or exits. Recomputing from
    the DB means restarts/reschedules can't double-fire and missed
    transitions fire on the next boot.
    """

    def __init__(self, cog: DuelCog) -> None:
        self._cog = cog
        self._task: asyncio.Task[None] | None = None

    def reschedule(self) -> None:
        """(Re)start the loop; call after any duel state change."""
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
                transition = await svc.duels.fetch_next_transition()
            if transition is None:
                return
            if transition.due_now:
                if not await self._fire(transition):
                    return
            else:
                logger.info(
                    "Duel {} '{}' scheduled for {}",
                    transition.duel_id,
                    transition.kind,
                    transition.fires_at,
                )
                await discord.utils.sleep_until(transition.fires_at)

    async def _fire(self, transition: DuelTransition) -> bool:
        """Run a transition; False stops the loop.

        Stopping on failure avoids a hot retry spin when a transition fails
        before flipping the DB status it's gated on.
        """
        handler = (
            self._cog.handle_deadline
            if transition.kind == "deadline"
            else self._cog.handle_end
        )
        try:
            await handler(transition.duel_id)
        except Exception:
            logger.opt(exception=True).error(
                "Duel {} transition '{}' failed", transition.duel_id, transition.kind
            )
            return False
        return True
