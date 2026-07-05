from __future__ import annotations

import typing

import discord
from discord import ui

from utilities.formatting import pretty_record

from .models import Outcome

if typing.TYPE_CHECKING:
    from database.services.duels import DuelActivation, DuelInfo, DuelPlayerInfo

    from .cog import DuelCog

__all__ = ("ReadyUpView", "activation_text", "details_text", "result_items")


def details_text(duel: DuelInfo, players: list[DuelPlayerInfo]) -> str:
    player_one, player_two = players
    deadline_f = discord.utils.format_dt(duel.ready_deadline, style="F")
    deadline_r = discord.utils.format_dt(duel.ready_deadline, style="R")
    return (
        f"## ⚔️ <@{player_one.user_id}> vs. <@{player_two.user_id}>\n"
        f"`Map` {duel.map_code}\n"
        f"`Level` {duel.level}\n"
        f"`Wager` {duel.wager} XP\n"
        f"`Length` {duel.duration.days} day(s), starting when both players ready up\n"
        f"`Ready by` {deadline_f} ({deadline_r}), or the duel is cancelled"
    )


def activation_text(activation: DuelActivation) -> str:
    end_f = discord.utils.format_dt(activation.ends_at, style="F")
    end_r = discord.utils.format_dt(activation.ends_at, style="R")
    return (
        "## 🟢 The duel is live!\n"
        f"Submit times with `/duel submit` in this thread before {end_f} ({end_r}).\n"
        "Lower time wins; your best submission counts."
    )


def result_items(
    duel: DuelInfo, players: list[DuelPlayerInfo], outcome: Outcome
) -> list[str | ui.Item]:
    player_one, player_two = players
    times = "\n".join(
        f"<@{p.user_id}> — "
        + (pretty_record(p.record) if p.record is not None else "no submission")
        for p in players
    )
    match outcome:
        case Outcome.VOID:
            verdict = "Nobody submitted a time. The duel is void; no XP changes hands."
        case Outcome.DRAW:
            verdict = "Identical times — a draw! No XP changes hands."
        case Outcome.P1_WIN | Outcome.P2_WIN:
            winner, loser = (
                (player_one, player_two)
                if outcome is Outcome.P1_WIN
                else (player_two, player_one)
            )
            how = " by forfeit" if loser.record is None else ""
            verdict = (
                f"<@{winner.user_id}> wins{how} and takes "
                f"**{duel.wager} XP** from <@{loser.user_id}>!"
            )
    return ["## 🏁 Duel over", times, verdict]


class _ReadyButton(ui.Button["ReadyUpView"]):
    def __init__(self, duel_id: int, player: DuelPlayerInfo) -> None:
        self.user_id = player.user_id
        super().__init__(
            custom_id=f"duel:{duel_id}:ready:{player.num}",
            label=f"Player {player.num} ready!"
            if player.ready
            else f"Player {player.num} ready?",
            style=discord.ButtonStyle.green
            if player.ready
            else discord.ButtonStyle.grey,
            disabled=player.ready,
        )

    def mark_ready(self) -> None:
        assert self.label
        self.label = self.label.replace("?", "!")
        self.style = discord.ButtonStyle.green
        self.disabled = True

    async def callback(self, itx: discord.Interaction) -> None:
        assert self.view
        await self.view.handle_ready(itx, self)


class ReadyUpView(ui.LayoutView):
    """Persistent ready-up card on a duel thread's opening message."""

    def __init__(
        self, cog: DuelCog, duel: DuelInfo, players: list[DuelPlayerInfo]
    ) -> None:
        super().__init__(timeout=None)
        self._cog = cog
        self._duel = duel
        buttons = ui.ActionRow(*(_ReadyButton(duel.id, p) for p in players))
        self.add_item(
            ui.Container(ui.TextDisplay(details_text(duel, players)), buttons)
        )

    async def handle_ready(
        self, itx: discord.Interaction, button: _ReadyButton
    ) -> None:
        if itx.user.id != button.user_id:
            await itx.response.send_message(
                "This isn't your ready button.", ephemeral=True
            )
            return
        async with self._cog.bot.acquire() as svc:
            await svc.duels.set_ready(self._duel.id, itx.user.id)
            activation = await svc.duels.try_activate(self._duel.id)
        button.mark_ready()
        await itx.response.edit_message(view=self)
        if activation is not None:
            assert isinstance(itx.channel, discord.Thread)
            await self._cog.announce_activation(itx.channel, activation)
