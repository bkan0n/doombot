from __future__ import annotations

import contextlib
import itertools
import re
import typing

import discord
import msgspec
from discord import ui
from loguru import logger

from utilities import emojis
from utilities.flags import Notification
from utilities.formatting import make_ordinal, pretty_record
from utilities.views import Card

if typing.TYPE_CHECKING:
    from core import Akande, AkandeItx
    from database.services.records import (
        LeaderboardRecord,
        PendingRecord,
        PersonalRecord,
        VerificationCountEntry,
    )

__all__ = (
    "STAR_FORWARD_INTERVAL",
    "RecordSubmission",
    "RejectReasonModal",
    "StarButton",
    "VerificationView",
    "forward_if_spectacular",
    "leaderboard_pages",
    "make_ordinal",
    "personal_record_pages",
    "pretty_record",
    "status_text",
    "submission_body",
    "verification_stats_pages",
)

RECORDS_PER_PAGE = 10
STAR_FORWARD_INTERVAL = 10


class RecordSubmission(msgspec.Struct, frozen=True):
    """Everything a record submission card needs to render."""

    user_name: str
    map_code: str
    level_name: str
    record: float
    video: str | None
    screenshot_url: str | None

    @classmethod
    def from_pending(
        cls,
        pending: PendingRecord,
        *,
        user_name: str,
        screenshot_url: str | None,
    ) -> RecordSubmission:
        return cls(
            user_name=user_name,
            map_code=pending.map_code,
            level_name=pending.level_name,
            record=pending.record,
            video=pending.video,
            screenshot_url=screenshot_url,
        )


def status_text(verifier: str, *, rejected: bool, has_video: bool) -> str:
    """Verification outcome line, shared by the record card and the DM alert."""
    if rejected:
        return f"{emojis.UNVERIFIED} Rejected by {verifier}!"
    if has_video:
        return f"{emojis.VERIFIED} Complete verification by {verifier}!"
    return (
        f"{emojis.HALF_VERIFIED} Partial verification by {verifier}! "
        "No video proof supplied."
    )


def submission_body(
    sub: RecordSubmission,
    *,
    header: str,
    verifier: str | None = None,
    rejected: bool = False,
    superseded: bool = False,
) -> list[str | ui.Item]:
    """The record submission card, top to bottom.

    Used by the confirm prompt, record message, queue post, and the
    post-verification edit. ``verifier`` adds the verification outcome
    line; ``rejected`` flips its wording. ``superseded`` marks a pending
    submission auto-rejected because a faster one replaced it.
    """
    status: tuple[str | ui.Item, ...] = ()
    if superseded:
        status = (
            ui.Separator(),
            f"{emojis.UNVERIFIED} Auto-rejected - superseded by a faster submission.",
        )
    elif verifier is not None:
        status = (
            ui.Separator(),
            status_text(verifier, rejected=rejected, has_video=sub.video is not None),
        )
    gallery = ui.MediaGallery()
    if sub.screenshot_url:
        gallery.add_item(media=sub.screenshot_url)
    return [
        f"## {header}",
        f"`Name` {discord.utils.escape_markdown(sub.user_name)}\n"
        f"`Code` **{sub.map_code}**\n"
        f"`Level` {sub.level_name}\n"
        f"`Record` {pretty_record(sub.record)}"
        + (f"\n`Video` {sub.video}" if sub.video else ""),
        *((gallery,) if sub.screenshot_url else ()),
        *status,
    ]


def _proof_suffix(video: str | None, *, tournament: bool = False) -> str:
    if tournament:
        return emojis.TROPHY
    if video:
        return f"{emojis.VERIFIED} ・ [Video]({video})"
    return emojis.HALF_VERIFIED


def _leaderboard_entry(record: LeaderboardRecord, *, single_level: bool) -> str:
    if single_level:
        placement = emojis.get_placement_emoji(record.rank_num)
        header = f"{placement} {make_ordinal(record.rank_num)}".strip()
    else:
        header = record.level_name
    return (
        f"**{header}** - {discord.utils.escape_markdown(record.nickname)}\n"
        f"`Record` [{pretty_record(record.record)}]({record.screenshot}) "
        f"{_proof_suffix(record.video, tournament=record.tournament)}"
    )


def leaderboard_pages(
    records: list[LeaderboardRecord], title: str, *, single_level: bool
) -> list[list[str | ui.Item]]:
    """Pages of leaderboard entries, RECORDS_PER_PAGE per page.

    single_level=True renders placement ordinals (a level's leaderboard);
    False renders one world record per level, keyed by level name.
    """
    return [
        [
            f"## {title}",
            *(
                _leaderboard_entry(record, single_level=single_level)
                for record in chunk
            ),
        ]
        for chunk in itertools.batched(records, RECORDS_PER_PAGE)
    ]


def personal_record_pages(
    records: list[PersonalRecord], title: str
) -> list[list[str | ui.Item]]:
    """Pages of personal records grouped under map headers."""
    pages: list[list[str | ui.Item]] = []
    for chunk in itertools.batched(records, RECORDS_PER_PAGE):
        page: list[str | ui.Item] = [f"## {title}"]
        group: str | None = None
        for record in chunk:
            creators = record.creators or "Unknown"
            map_name = record.map_name or "Unknown"
            header = (
                f"**{map_name} by "
                f"{discord.utils.escape_markdown(creators)} ({record.map_code})**"
            )
            if header != group:
                page.append(header)
                group = header
            page.append(
                f"`{record.level_name}` "
                f"[{pretty_record(record.record)}]({record.screenshot}) "
                f"{_proof_suffix(record.video)}"
            )
        pages.append(page)
    return pages


def verification_stats_pages(
    entries: list[VerificationCountEntry],
) -> list[list[str | ui.Item]]:
    """Pages of the verifier leaderboard."""
    return [
        [
            "## Verification Leaderboard",
            "\n".join(
                f"`{make_ordinal(entry.rank):^6}` `{entry.amount:^6}` "
                f"{discord.utils.escape_markdown(entry.nickname)}"
                for entry in chunk
            ),
        ]
        for chunk in itertools.batched(entries, RECORDS_PER_PAGE)
    ]


class RejectReasonModal(ui.Modal, title="Rejection Reason"):
    reason = ui.TextInput(label="Reason", style=discord.TextStyle.long)

    def __init__(self) -> None:
        super().__init__(timeout=600.0)

    async def on_submit(self, itx: AkandeItx) -> None:
        await itx.response.send_message("Rejecting record...", ephemeral=True)


class _VerificationButtons(ui.ActionRow["VerificationView"]):
    @ui.button(
        label="Verify",
        style=discord.ButtonStyle.green,
        custom_id="records-verify:accept",
    )
    async def verify(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await _resolve_verification(itx, verified=True)

    @ui.button(
        label="Reject",
        style=discord.ButtonStyle.red,
        custom_id="records-verify:reject",
    )
    async def reject(self, itx: AkandeItx, button: ui.Button) -> None:
        modal = RejectReasonModal()
        await itx.response.send_modal(modal)
        if await modal.wait():
            return
        await _resolve_verification(itx, verified=False, rejection=modal.reason.value)


class VerificationView(ui.LayoutView):
    """Persistent Verify/Reject controls attached to queue messages.

    Constructed bare in ``cog_load`` purely for custom_id dispatch across
    restarts; constructed with card items when posting a queue message.
    """

    def __init__(self, *card_items: str | ui.Item) -> None:
        super().__init__(timeout=None)
        items = [
            ui.TextDisplay(item) if isinstance(item, str) else item
            for item in card_items
        ]
        self.add_item(ui.Container(*items, ui.Separator(), _VerificationButtons()))


class StarButton(ui.DynamicItem[ui.Button], template=r"records-star:(?P<id>[0-9]+)"):
    """Star-vote button on verified record cards.

    One vote per user per record message, tallied in ``top_records``. Every
    ``STAR_FORWARD_INTERVAL``th star forwards the record to the top-records
    channel. The ``custom_id`` carries the record message's own ID so the
    button survives restarts without per-message registration.
    """

    def __init__(self, message_id: int, count: int = 0) -> None:
        super().__init__(
            ui.Button(
                style=discord.ButtonStyle.green,
                emoji=emojis.star_tier_emoji(count),
                label=str(count),
                custom_id=f"records-star:{message_id}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls, itx: AkandeItx, item: ui.Button, match: re.Match[str]
    ) -> StarButton:
        return cls(int(match["id"]))

    async def callback(self, itx: AkandeItx) -> None:
        await itx.response.defer(ephemeral=True)
        assert itx.message
        async with itx.client.acquire() as svc:
            counted = await svc.records.add_top_record_vote(
                itx.user.id, itx.message.id, itx.message.channel.id
            )
            if not counted:
                logger.debug(
                    "Duplicate star vote by {} on record message {}",
                    itx.user.id,
                    itx.message.id,
                )
                await itx.followup.send(
                    "You've already starred this record.", ephemeral=True
                )
                return
            count = await svc.records.fetch_top_record_vote_count(
                itx.message.id, itx.message.channel.id
            )
            notify_user_id: int | None = None
            if count and count % STAR_FORWARD_INTERVAL == 0:
                card = await svc.records.fetch_record_card_data(itx.message.id)
                if card is not None:
                    flags = await svc.users.fetch_flags(card.user_id)
                    if Notification.SPECTACULAR in Notification(flags or 0):
                        notify_user_id = card.user_id
        logger.info(
            "Star vote by {} on record message {} -> {} stars",
            itx.user.id,
            itx.message.id,
            count,
        )
        self.item.label = str(count)
        self.item.emoji = emojis.star_tier_emoji(count)
        with contextlib.suppress(discord.HTTPException):
            await itx.edit_original_response(view=self.view)
        await forward_if_spectacular(
            itx.client, itx.message, count, notify_user_id=notify_user_id
        )


async def forward_if_spectacular(
    bot: Akande,
    message: discord.Message,
    count: int,
    *,
    notify_user_id: int | None = None,
) -> None:
    """Forward the record to the top-records channel at each interval multiple.

    DMs the submitter when they opted into spectacular notifications
    (``notify_user_id`` already reflects that check).
    """
    if count == 0 or count % STAR_FORWARD_INTERVAL:
        return
    channel = bot.get_channel(bot.config.channels.records.top_records)
    if not isinstance(channel, discord.TextChannel):
        logger.warning("Top-records channel unavailable; skipping forward.")
        return
    try:
        await message.forward(channel)
        logger.info("Forwarded spectacular record {} at {} stars", message.id, count)
    except discord.HTTPException as e:
        logger.warning("Forwarding spectacular record {} failed: {}", message.id, e)
        return
    if notify_user_id is None or message.guild is None:
        return
    member = message.guild.get_member(notify_user_id)
    if member is None:
        return
    with contextlib.suppress(discord.HTTPException):
        await member.send(
            f"Your record reached {count} stars and was forwarded to "
            f"{channel.mention}!\n{message.jump_url}"
        )


def _record_jump_url(itx: AkandeItx, pending: PendingRecord) -> str:
    assert itx.guild
    return (
        f"https://discord.com/channels/{itx.guild.id}"
        f"/{pending.channel_id}/{pending.message_id}"
    )


async def _edit_original_message(
    itx: AkandeItx, pending: PendingRecord, *, rejected: bool
) -> None:
    """Edit the record message in place via a partial message.

    The screenshot attachment is retained by omitting ``attachments=`` and
    re-referenced with ``attachment://``, so no fetch, re-download, or
    re-upload round-trips are needed.
    """
    assert itx.guild
    channel = itx.guild.get_channel(pending.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    member = itx.guild.get_member(pending.user_id)
    sub = RecordSubmission.from_pending(
        pending,
        user_name=member.display_name if member else "Unknown",
        screenshot_url="attachment://image.png",
    )
    body = submission_body(
        sub, header="New Personal Record!", verifier=itx.user.mention, rejected=rejected
    )
    if not rejected:
        body.append(ui.ActionRow(StarButton(pending.message_id))) # type: ignore
    try:
        await channel.get_partial_message(pending.message_id).edit(view=Card(body))
    except discord.HTTPException as e:
        logger.warning(
            "Verification edit failed for message {}: {}", pending.message_id, e
        )


async def _dm_submitter(
    itx: AkandeItx,
    pending: PendingRecord,
    *,
    rejected: bool,
    rejection: str | None,
) -> None:
    assert itx.guild
    member = itx.guild.get_member(pending.user_id)
    if member is None:
        return
    lines = [
        f"**Map Code:** {pending.map_code}",
        f"**Level:** {pending.level_name}",
        f"**Record:** {pretty_record(pending.record)}",
        status_text(
            itx.user.mention, rejected=rejected, has_video=pending.video is not None
        ),
    ]
    if rejection is not None:
        lines.append(f"**Reason:** {rejection}")
    lines.append(_record_jump_url(itx, pending))
    with contextlib.suppress(discord.HTTPException):
        await member.send("\n".join(lines))


async def _resolve_verification(
    itx: AkandeItx, *, verified: bool, rejection: str | None = None
) -> None:
    assert itx.message
    async with itx.client.acquire() as svc:
        pending = await svc.records.fetch_pending_record(itx.message.id)
        if pending is None:
            # Already handled by another verifier; drop the stale message.
            with contextlib.suppress(discord.HTTPException):
                await itx.message.delete()
            with contextlib.suppress(discord.HTTPException):
                await itx.followup.send(
                    "This record was already handled.", ephemeral=True
                )
            return
        if verified:
            await svc.records.verify_record(itx.message.id)
            await svc.records.increment_verification_count(itx.user.id)
        else:
            await svc.records.delete_records(
                pending.user_id, pending.map_code, pending.level_name
            )
        flags = await svc.users.fetch_flags(pending.user_id)

    await _edit_original_message(itx, pending, rejected=not verified)
    wanted = Notification.VERIFIED if verified else Notification.DENIED
    if wanted in Notification(flags or 0):
        await _dm_submitter(itx, pending, rejected=not verified, rejection=rejection)
    with contextlib.suppress(discord.HTTPException):
        await itx.message.delete()
