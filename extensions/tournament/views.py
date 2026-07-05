from __future__ import annotations

import itertools
import typing

import discord
import msgspec
from discord import ui

from database.services import transaction
from utilities import emojis, views
from utilities.formatting import make_ordinal, pretty_record

from .models import Category, MapEntry, MissionType

if typing.TYPE_CHECKING:
    from datetime import datetime

    from core import AkandeItx
    from database.services.tournament import (
        HallOfFameEntry,
        MissionWithMap,
        Season,
        TournamentLeaderboardEntry,
        TournamentMap,
    )
    from utilities.config import Config

TOURNAMENT_TITLE = "Doomfist Parkour Tournament"
ENTRIES_PER_PAGE = 10

_CATEGORY_ORDER: dict[str, int] = {c: i for i, c in enumerate(Category.playable())}


def _dates_block(start: datetime, end: datetime) -> str:
    return (
        f"**Start**\n{discord.utils.format_dt(start, 'R')}\n"
        f"{discord.utils.format_dt(start, 'F')}\n"
        f"**End**\n{discord.utils.format_dt(end, 'R')}\n"
        f"{discord.utils.format_dt(end, 'F')}"
    )


class TournamentSubmission(msgspec.Struct, frozen=True):
    """Everything a tournament record card needs to render."""

    user_name: str
    category: str
    record: float
    screenshot_url: str | None


def tournament_submission_body(
    sub: TournamentSubmission, *, header: str
) -> list[str | ui.Item]:
    gallery = ui.MediaGallery()
    if sub.screenshot_url:
        gallery.add_item(media=sub.screenshot_url)
    return [
        f"## {header}",
        f"`Name` {discord.utils.escape_markdown(sub.user_name)}\n"
        f"`Category` {sub.category}\n"
        f"`Record` {pretty_record(sub.record)}",
        *((gallery,) if sub.screenshot_url else ()),
    ]


def announcement_body(
    maps: list[TournamentMap], start: datetime, end: datetime, mentions: str
) -> list[str | ui.Item]:
    """The tournament-started announcement.

    The banner file must be attached as banner.png by the caller.
    """
    ordered = sorted(maps, key=lambda m: _CATEGORY_ORDER.get(m.category, 99))
    map_blocks = [
        f"**{m.category}**\n"
        f"`Code` **{m.code}**\n"
        f"`Level` {m.level}\n"
        f"`Creator` {discord.utils.escape_markdown(m.creator)}"
        for m in ordered
    ]
    gallery = ui.MediaGallery()
    gallery.add_item(media="attachment://banner.png")
    return [
        mentions,
        f"## {TOURNAMENT_TITLE}",
        *map_blocks,
        ui.Separator(),
        _dates_block(start, end),
        gallery,
    ]


def end_body(mentions: str) -> list[str | ui.Item]:
    return [
        mentions,
        f"## {TOURNAMENT_TITLE}",
        "**The round has ended!**\nStay tuned for the next announcement!",
    ]


def tournament_leaderboard_pages(
    entries: list[TournamentLeaderboardEntry], category: str, rank: str | None
) -> list[list[str | ui.Item]]:
    """Pages of latest-per-user records, ENTRIES_PER_PAGE per page."""
    title = f"## {category} Leaderboard" + (f" - {rank}" if rank else "")
    ordered = sorted(entries, key=lambda e: e.record)
    lines = [
        f"`{make_ordinal(i)}` {emojis.rank_emoji(e.value)} "
        f"{discord.utils.escape_markdown(e.nickname)} - "
        f"[{pretty_record(e.record)}]({e.screenshot})"
        for i, e in enumerate(ordered, start=1)
    ]
    return [
        [title, "\n".join(chunk)]
        for chunk in itertools.batched(lines, ENTRIES_PER_PAGE)
    ]


def _hof_line(entry: HallOfFameEntry) -> str:
    return (
        f"`{make_ordinal(entry.rank_num)}` - "
        f"{discord.utils.escape_markdown(entry.nickname)} - "
        f"[{pretty_record(entry.record)}]({entry.screenshot}) "
        f"{emojis.rank_emoji(entry.value)}"
    )


def hall_of_fame_body(
    per_category: dict[str, list[HallOfFameEntry]],
) -> list[str | ui.Item]:
    items: list[str | ui.Item] = [f"## {TOURNAMENT_TITLE} - Hall of Fame - Top 3"]
    for category, entries in per_category.items():
        top = "\n".join(_hof_line(e) for e in entries if e.rank_num <= 3)
        items.append(f"**{category}**\n{top or '*No records*'}")
    return items


def archive_pages(
    per_category: dict[str, list[HallOfFameEntry]],
) -> list[list[str | ui.Item]]:
    """Full per-category leaderboards for the Records Archive thread."""
    pages: list[list[str | ui.Item]] = []
    for category, entries in per_category.items():
        for chunk in itertools.batched(entries, ENTRIES_PER_PAGE):
            pages.append([f"## {category}", "\n".join(_hof_line(e) for e in chunk)])
    return pages


def format_mission(m: MissionWithMap) -> str:
    if m.type == MissionType.XP_THRESHOLD:
        text = f"Get {int(m.target or 0)} XP (excluding this mission)"
    elif m.type == MissionType.MISSION_THRESHOLD:
        text = f"Complete {int(m.target or 0)} {m.extra_target} missions"
    elif m.type == MissionType.TOP_PLACEMENT:
        text = f"Get Top 3 in {int(m.target or 0)} categories."
    elif m.type == MissionType.SUB_TIME:
        text = f"Get sub {pretty_record(m.target or 0)}"
    else:  # Completion
        text = "Complete the level."
    return f"- {m.difficulty}: {text}"


def missions_body(missions: list[MissionWithMap], end: datetime) -> list[str | ui.Item]:
    items: list[str | ui.Item] = [f"## {TOURNAMENT_TITLE} - Missions"]
    for category, group_iter in itertools.groupby(missions, key=lambda m: m.category):
        group = list(group_iter)
        map_suffix = f" ({group[0].code} - {group[0].level})" if group[0].code else ""
        lines = "\n".join(format_mission(m) for m in group)
        items.append(f"**{category}{map_suffix}**\n{lines}")
    items.append(ui.Separator())
    items.append(
        f"Ends:\n{discord.utils.format_dt(end, 'R')}\n"
        f"{discord.utils.format_dt(end, 'F')}"
    )
    return items


class _MissionRemoveButton(ui.Button["MissionRemoveView"]):
    def __init__(self, mission: MissionWithMap) -> None:
        super().__init__(label="Remove", style=discord.ButtonStyle.red)
        self._mission = mission

    async def callback(self, itx: AkandeItx) -> None:
        assert self.view
        await self.view.remove(itx, self._mission)


class _MissionNav(ui.ActionRow["MissionRemoveView"]):
    @ui.button(emoji="◀", style=discord.ButtonStyle.grey)
    async def previous(self, itx: AkandeItx, button: ui.Button) -> None:
        assert self.view
        await self.view.flip(itx, -1)

    @ui.button(label="…", style=discord.ButtonStyle.grey, disabled=True)
    async def counter(self, itx: AkandeItx, button: ui.Button) -> None: ...

    @ui.button(emoji="▶", style=discord.ButtonStyle.grey)
    async def next(self, itx: AkandeItx, button: ui.Button) -> None:
        assert self.view
        await self.view.flip(itx, 1)

    def update_state(self, index: int, total: int) -> None:
        self.counter.label = f"{index + 1}/{total}"


class MissionRemoveView(views.BaseLayoutView):
    """Every mission as a section with its own Remove button; deletes on click.

    Paged because a full mission slate (17 sections at 3 components each)
    would exceed the 40-component message cap.
    """

    MISSIONS_PER_PAGE = 10

    def __init__(self, itx: AkandeItx, missions: list[MissionWithMap]) -> None:
        super().__init__(itx, timeout=600.0)
        self.missions = missions
        self._page = 0
        self._nav = _MissionNav()
        self.render()

    @staticmethod
    def _label(m: MissionWithMap) -> str:
        map_suffix = f" ({m.code} - {m.level})" if m.code else ""
        return f"**{m.category}**{map_suffix}\n{format_mission(m).removeprefix('- ')}"

    def render(self) -> None:
        self.clear_items()
        pages = list(itertools.batched(self.missions, self.MISSIONS_PER_PAGE))
        if not pages:
            self.add_item(ui.Container(ui.TextDisplay("✅ All missions removed.")))
            self.stop()
            return
        self._page = min(self._page, len(pages) - 1)
        container = ui.Container(ui.TextDisplay("## Remove Missions"), ui.Separator())
        for mission in pages[self._page]:
            container.add_item(
                ui.Section(
                    ui.TextDisplay(self._label(mission)),
                    accessory=_MissionRemoveButton(mission),
                )
            )
        if len(pages) > 1:
            self._nav.update_state(self._page, len(pages))
            container.add_item(ui.Separator())
            container.add_item(self._nav)
        self.add_item(container)

    async def flip(self, itx: AkandeItx, delta: int) -> None:
        total = len(list(itertools.batched(self.missions, self.MISSIONS_PER_PAGE)))
        self._page = (self._page + delta) % total
        self.render()
        await itx.response.edit_message(view=self)

    async def remove(self, itx: AkandeItx, mission: MissionWithMap) -> None:
        # A mission's ``id`` is its tournament's id (composite primary key).
        async with itx.client.acquire() as svc:
            await svc.tournament.delete_mission(
                mission.category, mission.difficulty, mission.id
            )
        self.missions.remove(mission)
        self.render()
        await itx.response.edit_message(view=self)


def info_pages(config: Config) -> dict[str, str]:
    """Static info panel pages.

    Bracket and map-contest pages were dropped with their features.
    """
    submissions = f"<#{config.channels.tournament.submissions}>"
    return {
        "Rules": (
            "# Tournament Rules\n"
            "1. Any tech that is possible in the chosen framework is allowed.\n"
            "2. Map creators ARE allowed to run their own maps.\n"
            "3. Post your screenshots in a timely manner. "
            "Holding onto good times and sniping on the last day is not allowed.\n"
            "4. Do not cheat and submit false times (See Cheating section below).\n"
            "5. Strategies that require more than one player are not allowed. "
            "Every strategy must be possible in a single player environment.\n"
            "# Cheating/Submitting False Times\n"
            "Submitting a cheated or modified time. Anyone caught cheating with, "
            "but not limited to, any of the following is subject to punishment "
            "by mod and org discretion based on severity.\n"
            "*(Breaking any more than 1 rule will get you immediately "
            "perma-banned from further tournaments)*\n"
            "1. Faking your time in any way.\n"
            "2. Changing the positions of the checkpoints on your own accord "
            "(this is not applied to the makers of the map if there is an "
            "issue on that level that needs to be addressed).\n"
            "3. Changing any other setting in either workshop or in the lobby "
            "unless otherwise specified (e.g. changing cancel timings or "
            "cooldowns on time attack maps).\n"
            "4. Letting another person play for you (including account "
            "sharing). If you contact the Orgs beforehand, we can take a look "
            "at the situation e.g. playing at another persons house on their "
            "account.\n\n"
            "**This is not an inclusive list. If you feel someone has altered "
            "a map or time in any way, bring it up to the Orgs or Mods.**"
        ),
        "How to submit": (
            "# Submissions\n"
            "To submit a time for the tournament use the command "
            f"`/tournament submit` in the {submissions} channel.\n"
            "There are shorter variations as well:\n"
            "- `/ta` - Time Attack\n"
            "- `/mc` - Mildcore\n"
            "- `/hc` - Hardcore\n"
            "- `/bo` - Bonus\n"
        ),
        "Ranks": (
            "To separate hard competition from a more casual approach, "
            "we divide the tournament players by three ranks.\n"
            "- Gold (Bottom)\n"
            "- Diamond (Middle)\n"
            "- Grandmaster (Top)\n"
            "* This is in each category. So, you may be Gold in Hardcore but "
            "Grandmaster in Time Attack.\n\n"
            "Currently, Tournament Orgs decide on which rank each player will "
            "have. Criteria for the ranks depend on one's records over time "
            "versus how the leaderboard does. Depending on your performance, "
            "you may go up or down a rank at a Tournament Orgs discretion.\n\n"
            "The top time in the Gold leaderboard is awarded the same amount "
            "of points as Grandmaster, barring completed missions. XP will be "
            "better spread across the board and let different skill levels "
            "compete.\n\n"
            "If you think you're in the wrong rank, you could always contact "
            "an org to reconsider your rank.\n\n"
            "If you're unsure what your rank is, ask any online org."
        ),
    }


# --- Start wizard -----------------------------------------------------------


class MapEntryModal(ui.Modal, title="Tournament Map"):
    code = ui.TextInput(label="Map Code")
    level = ui.TextInput(label="Level Name")
    creator = ui.TextInput(label="Map Creator")

    def __init__(self, wizard: StartWizard, category: Category) -> None:
        super().__init__(timeout=600.0)
        self._wizard = wizard
        self._category = category

    async def on_submit(self, itx: AkandeItx) -> None:
        self._wizard.maps[self._category] = MapEntry(
            code=self.code.value.upper().strip(),
            level=self.level.value.strip(),
            creator=self.creator.value.strip(),
        )
        self._wizard.render()
        await itx.response.edit_message(view=self._wizard)


class _WizardCategoryRow(ui.ActionRow["StartWizard"]):
    async def _open(self, itx: AkandeItx, category: Category) -> None:
        assert self.view
        await itx.response.send_modal(MapEntryModal(self.view, category))

    @ui.button(label="Time Attack", style=discord.ButtonStyle.blurple)
    async def ta(self, itx: AkandeItx, button: ui.Button) -> None:
        await self._open(itx, Category.TIME_ATTACK)

    @ui.button(label="Mildcore", style=discord.ButtonStyle.blurple)
    async def mc(self, itx: AkandeItx, button: ui.Button) -> None:
        await self._open(itx, Category.MILDCORE)

    @ui.button(label="Hardcore", style=discord.ButtonStyle.blurple)
    async def hc(self, itx: AkandeItx, button: ui.Button) -> None:
        await self._open(itx, Category.HARDCORE)

    @ui.button(label="Bonus", style=discord.ButtonStyle.blurple)
    async def bo(self, itx: AkandeItx, button: ui.Button) -> None:
        await self._open(itx, Category.BONUS)


class _WizardConfirmRow(ui.ActionRow["StartWizard"]):
    @ui.button(label="Create Tournament", style=discord.ButtonStyle.green)
    async def confirm(self, itx: AkandeItx, button: ui.Button) -> None:
        assert self.view
        self.view.confirmed = True
        # Invisible ack; the cog renders the outcome over this message.
        await itx.response.defer()
        self.view.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, itx: AkandeItx, button: ui.Button) -> None:
        assert self.view
        await itx.response.edit_message(
            view=views.Card(["❌ Tournament creation cancelled."])
        )
        self.view.stop()


class StartWizard(views.BaseLayoutView):
    """Draft state for a new tournament: dates fixed, maps set via modals."""

    def __init__(self, itx: AkandeItx, start: datetime, end: datetime) -> None:
        super().__init__(itx, timeout=600.0)
        self.start = start
        self.end = end
        self.maps: dict[Category, MapEntry] = {}
        self.confirmed = False
        self._categories = _WizardCategoryRow()
        self._confirm_row = _WizardConfirmRow()
        self.render()

    def render(self) -> None:
        self.clear_items()
        lines: list[str] = ["## New Tournament", _dates_block(self.start, self.end)]
        for category in Category.playable():
            entry = self.maps.get(category)
            state = (
                f"`{entry.code}` - {entry.level} by {entry.creator}"
                if entry
                else "*not set*"
            )
            lines.append(f"**{category}**: {state}")
        self._confirm_row.confirm.disabled = not self.maps
        self.add_item(
            ui.Container(
                *(ui.TextDisplay(line) for line in lines),
                ui.Separator(),
                self._categories,
                self._confirm_row,
            )
        )


# --- Role-ping prompt (missions publish / announcements) ---------------------

_PINGABLE = ("Time Attack", "Mildcore", "Hardcore", "Bonus", "Trifecta")


class _RolePingSelect(ui.Select["RolePingPrompt"]):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Which roles should be pinged?",
            max_values=len(_PINGABLE),
            options=[discord.SelectOption(label=x, value=x) for x in _PINGABLE],
        )

    async def callback(self, itx: AkandeItx) -> None:
        await itx.response.defer()


class _RolePingButtons(ui.ActionRow["RolePingPrompt"]):
    @ui.button(label="Publish", style=discord.ButtonStyle.green)
    async def confirm(self, itx: AkandeItx, button: ui.Button) -> None:
        assert self.view
        self.view.value = True
        await itx.response.defer()
        self.view.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, itx: AkandeItx, button: ui.Button) -> None:
        assert self.view
        self.view.value = False
        await itx.response.edit_message(view=views.Card(["❌ Cancelled."]))
        self.view.stop()


class RolePingPrompt(views.BaseLayoutView):
    """Preview body + role multi-select + Publish/Cancel."""

    def __init__(self, itx: AkandeItx, *items: str | ui.Item) -> None:
        super().__init__(itx, timeout=300.0)
        self.value = False
        self._select = _RolePingSelect()
        wrapped = [
            ui.TextDisplay(item) if isinstance(item, str) else item for item in items
        ]
        self.add_item(
            ui.Container(
                *wrapped,
                ui.Separator(),
                ui.ActionRow(self._select),
                _RolePingButtons(),
            )
        )

    @classmethod
    async def prompt(
        cls,
        itx: AkandeItx,
        *items: str | ui.Item,
        files: list[discord.File] | None = None,
    ) -> tuple[bool, list[str]]:
        """Returns (published?, selected role keys).

        ``files`` must back any ``attachment://`` references in ``items``;
        the preview is its own message, so they upload here too.
        """
        view = cls(itx, *items)
        if itx.response.is_done():
            await itx.edit_original_response(view=view, attachments=files or [])
        else:
            await itx.response.send_message(
                view=view, ephemeral=True, files=files or []
            )
        await view.wait()
        return view.value, list(view._select.values)


# --- Announcement modal -------------------------------------------------------


class AnnouncementModal(ui.Modal, title="Tournament Announcement"):
    title_input = ui.TextInput(label="Title")
    content = ui.TextInput(label="Announcement Content", style=discord.TextStyle.long)

    def __init__(self) -> None:
        super().__init__(timeout=600.0)
        self.itx: AkandeItx | None = None
        self.thumbnail = ui.FileUpload(required=False)
        self.image = ui.FileUpload(required=False)
        self.add_item(
            ui.Label(
                text="Thumbnail",
                description="Optional image shown beside the title.",
                component=self.thumbnail,
            )
        )
        self.add_item(
            ui.Label(
                text="Banner Image",
                description="Optional image shown below the announcement.",
                component=self.image,
            )
        )

    async def on_submit(self, itx: AkandeItx) -> None:
        self.itx = itx
        # thinking=True: a modal opened from a slash command has no message,
        # so a plain defer() leaves nothing for edit_original_response to edit.
        await itx.response.defer(ephemeral=True, thinking=True)


# --- Season manager -----------------------------------------------------------


class AddSeasonModal(ui.Modal, title="Add New Season"):
    name = ui.TextInput(label="Season Name")

    def __init__(self, manager: SeasonManagerView) -> None:
        super().__init__(timeout=300.0)
        self._manager = manager

    async def on_submit(self, itx: AkandeItx) -> None:
        async with itx.client.acquire() as svc:
            await svc.tournament.create_season(self.name.value)
            self._manager.seasons = await svc.tournament.fetch_seasons()
        self._manager.render()
        await itx.response.edit_message(view=self._manager)


class _SeasonSelect(ui.Select["SeasonManagerView"]):
    def __init__(self, seasons: list[Season]) -> None:
        super().__init__(
            placeholder="Select a season",
            options=[
                discord.SelectOption(
                    label=f"{s.number} | {s.name}",
                    value=str(s.number),
                    emoji="✅" if s.active else None,
                )
                for s in seasons
            ],
        )

    async def callback(self, itx: AkandeItx) -> None:
        assert self.view
        self.view.selected = int(self.values[0])
        await itx.response.defer()


class _SeasonButtons(ui.ActionRow["SeasonManagerView"]):
    @ui.button(label="New Season", style=discord.ButtonStyle.green)
    async def new_season(self, itx: AkandeItx, button: ui.Button) -> None:
        assert self.view
        await itx.response.send_modal(AddSeasonModal(self.view))

    @ui.button(label="Activate Selected", style=discord.ButtonStyle.red)
    async def activate(self, itx: AkandeItx, button: ui.Button) -> None:
        assert self.view
        view = self.view
        if view.selected is None:
            await itx.response.send_message(
                "Select a season from the dropdown first.", ephemeral=True
            )
            return
        target = next(s for s in view.seasons if s.number == view.selected)
        if target.active:
            await itx.response.send_message(
                "That season is already active.", ephemeral=True
            )
            return
        confirmed = await views.Confirm.prompt(
            itx,
            f"Change the active season to **{target.name}**?\n"
            "All XP resets for the new season (old seasons stay saved).",
        )
        if not confirmed:
            return
        async with itx.client.acquire() as svc, transaction(svc.db):
            await svc.tournament.deactivate_active_season()
            await svc.tournament.activate_season(target.number)
        async with itx.client.acquire() as svc:
            view.seasons = await svc.tournament.fetch_seasons()
        view.render()
        await view.itx.edit_original_response(view=view)
        channel = itx.client.get_channel(
            itx.client.config.channels.tournament.announcements
        )
        if isinstance(channel, discord.TextChannel):
            await channel.send(
                view=views.Card(
                    [
                        f"# {target.name}",
                        "## Welcome to the new tournament season!",
                        "All XP has been reset. Don't worry, the old XP "
                        "amounts and leaderboard are still saved!",
                    ]
                )
            )


class SeasonManagerView(views.BaseLayoutView):
    def __init__(self, itx: AkandeItx, seasons: list[Season]) -> None:
        super().__init__(itx, timeout=300.0)
        self.seasons = seasons
        self.selected: int | None = None
        self.render()

    def render(self) -> None:
        self.clear_items()
        active = next((s.name for s in self.seasons if s.active), "None")
        self.add_item(
            ui.Container(
                ui.TextDisplay("## Season Manager"),
                ui.TextDisplay(f"Active season: **{active}**"),
                ui.ActionRow(_SeasonSelect(self.seasons)),
                _SeasonButtons(),
            )
        )


# --- Persistent panels ----------------------------------------------------------


class _TournamentRoleButtons(ui.ActionRow["TournamentRolesView"]):
    # custom_ids are identical to the old bot so its posted panel keeps
    # dispatching after the port.
    @ui.button(
        label="Time Attack", style=discord.ButtonStyle.grey, custom_id="ta_role_"
    )
    async def ta(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await views.toggle_role(itx, itx.client.config.roles.tournament.time_attack)

    @ui.button(label="Mildcore", style=discord.ButtonStyle.grey, custom_id="mc_role_")
    async def mc(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await views.toggle_role(itx, itx.client.config.roles.tournament.mildcore)

    @ui.button(label="Hardcore", style=discord.ButtonStyle.grey, custom_id="hc_role_")
    async def hc(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await views.toggle_role(itx, itx.client.config.roles.tournament.hardcore)

    @ui.button(label="Bonus", style=discord.ButtonStyle.grey, custom_id="bo_role_")
    async def bo(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await views.toggle_role(itx, itx.client.config.roles.tournament.bonus)

    @ui.button(label="Trifecta", style=discord.ButtonStyle.grey, custom_id="tr_role_")
    async def trifecta(self, itx: AkandeItx, button: ui.Button) -> None:
        await itx.response.defer(ephemeral=True)
        await views.toggle_role(itx, itx.client.config.roles.tournament.trifecta)


class TournamentRolesView(ui.LayoutView):
    """Persistent tournament role self-assignment panel."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            ui.Container(
                ui.TextDisplay(
                    "## Tournament Roles\nToggle the categories you want "
                    "to be pinged for."
                ),
                _TournamentRoleButtons(),
            )
        )


class _InfoButton(ui.Button["InfoPanelView"]):
    def __init__(self, key: str, page: str) -> None:
        slug = key.replace(" ", "-").lower()
        super().__init__(label=key, custom_id=f"tournament-info-button{slug}")
        self._page = page

    async def callback(self, itx: AkandeItx) -> None:
        await itx.response.send_message(view=views.Card([self._page]), ephemeral=True)


class InfoPanelView(ui.LayoutView):
    """Persistent tournament info panel with per-page buttons."""

    def __init__(self, config: Config) -> None:
        super().__init__(timeout=None)
        pages = info_pages(config)
        chat = f"<#{config.channels.tournament.chat}>"
        announcements = f"<#{config.channels.tournament.announcements}>"
        header = (
            "# Tournament Information\n"
            "## Basics\n"
            "To be able to take part in these tournaments, use the role "
            "selector in this channel to get the roles you want for the "
            "tournament.\n"
            f"You can ask any questions you have in {chat}.\n\n"
            "At the start of each tournament, which will be announced in "
            f"{announcements}, you will get **up to four** different levels "
            "that you can play to win XP from the tournament.\n"
            "- Time Attack (speedrunning easy levels)\n"
            "- Mildcore (speedrunning levels that are not too hard but not "
            "too easy)\n"
            "- Hardcore (speedrunning hard levels)\n"
            "- Bonus (speedrunning a level that isn't only about Doomfist)\n\n"
            "Click the buttons below to learn more."
        )
        self.add_item(
            ui.Container(
                ui.TextDisplay(header),
                ui.Separator(),
                ui.ActionRow(*(_InfoButton(k, v) for k, v in pages.items())),
            )
        )
