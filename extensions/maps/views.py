from __future__ import annotations

import re
import typing

import discord
import msgspec
from discord import ui
from loguru import logger
from msgspec import structs

from database.services import transaction
from utilities import emojis, views
from utilities.errors import UserFacingError

if typing.TYPE_CHECKING:
    from core import AkandeItx
    from database.services.maps import MapSearchResult, RandomMapResult

__all__ = (
    "MapSubmission",
    "MapSubmissionReview",
    "MapSubmitModal",
    "map_search_pages",
    "map_submission_body",
    "random_map_card",
)

MAPS_PER_PAGE = 5

_LEVELS_LABEL = "Level Names"
_LEVELS_DESCRIPTION = (
    "One level per line. Without individual levels, users cannot submit their times."
)
_LEVELS_MAX_LENGTH = 2000

_OFFICIAL_BANNER = (
    "<:_:998055526468423700>"
    "<:_:998055528355860511>"
    "<:_:998055530440437840>"
    "<:_:998055532030079078>"
    "<:_:998055534068510750>"
    "<:_:998055536346021898>\n"
    "<:_:998055527412142100>"
    "<:_:998055529219887154>"
    "<:_:998055531346415656>"
    "<:_:998055533225455716>"
    "<:_:998055534999654480>"
    "<:_:998055537432338532>\n"
)


def _map_details(
    map_: MapSearchResult | RandomMapResult, *, rating: float | None
) -> str:
    banner = _OFFICIAL_BANNER if map_.official else ""
    desc = f"\n`Description` {map_.desc}" if map_.desc else ""
    return (
        f"### {map_.map_code}\n"
        f"{banner}"
        f"`Rating` {emojis.stars_rating_string(rating)}\n"
        f"`Creator` {discord.utils.escape_markdown(map_.creators)}\n"
        f"`Map` {map_.map_name}\n"
        f"`Type` {map_.map_type}"
        f"{desc}"
    )


def _map_card(map_: MapSearchResult, *, with_image: bool) -> ui.Item:
    details = ui.TextDisplay(_map_details(map_, rating=map_.rating))
    if with_image and map_.image:
        return ui.Section(details, accessory=ui.Thumbnail(map_.image))
    return details


def map_search_pages(maps: list[MapSearchResult]) -> list[list[str | ui.Item]]:
    """Build paginator pages of map cards, ``MAPS_PER_PAGE`` per page.

    A single result renders as one full card with its image shown large.
    """
    if len(maps) == 1:
        map_ = maps[0]
        page: list[str | ui.Item] = ["## Map Search", _map_card(map_, with_image=False)]
        if map_.levels:
            page.append(ui.TextDisplay(f"`Levels` {', '.join(map_.levels)}"))
        if map_.image:
            gallery = ui.MediaGallery()
            gallery.add_item(media=map_.image)
            page.append(gallery)
        return [page]

    pages: list[list[str | ui.Item]] = []
    for start in range(0, len(maps), MAPS_PER_PAGE):
        page = ["## Map Search"]
        for map_ in maps[start : start + MAPS_PER_PAGE]:
            page.append(_map_card(map_, with_image=True))
            page.append(ui.Separator())
        page.pop()
        pages.append(page)
    return pages


def random_map_card(map_: RandomMapResult, *, show_level: bool) -> list[str | ui.Item]:
    """Build a single-page card for a random map roll."""
    card: list[str | ui.Item] = [
        "## Random Map",
        ui.TextDisplay(_map_details(map_, rating=map_.rating)),
    ]
    if show_level and map_.level:
        card.append(ui.Separator())
        card.append(
            ui.TextDisplay(
                f"`Random Level` {map_.level} - "
                f"{emojis.stars_rating_string(map_.avg_rating)}"
            )
        )
    if map_.image:
        gallery = ui.MediaGallery()
        gallery.add_item(media=map_.image)
        card.append(gallery)
    return card


def _map_banner_url(map_name: str) -> str:
    """Default CDN banner: map name lowercased, non-letters stripped."""
    slug = re.sub(r"[^a-z]", "", map_name.lower())
    return f"https://cdn.bkan0n.com/assets/map_banners/{slug}.png"


def _parse_levels(raw: str) -> list[str]:
    """Unique, stripped level names in input order; error if none remain."""
    levels = list(
        dict.fromkeys(
            stripped for line in raw.splitlines() if (stripped := line.strip())
        )
    )
    if not levels:
        raise UserFacingError("At least one level name is required.")
    return levels


def _levels_display(levels: list[str]) -> str:
    """Numbered level list with a count header, for previews and cards."""
    lines = "\n".join(f"{n}. {level}" for n, level in enumerate(levels, start=1))
    return f"**Levels ({len(levels)})**\n{lines}"


class MapSubmission(msgspec.Struct, frozen=True):
    """Everything a map submission card needs to render."""

    map_code: str
    map_name: str
    map_types: list[str]
    description: str
    levels: list[str]
    image_url: str | None


def map_submission_body(
    sub: MapSubmission,
    *,
    header: str,
    showcase_image: bool = False,
) -> list[str | ui.Item]:
    """The map submission card, top to bottom.

    Used by the confirm preview and the new-maps announcement.
    ``showcase_image=False`` renders the image as a small thumbnail beside
    the details; ``True`` renders it large in a gallery at the bottom.
    """
    details = (
        f"`Code` **{sub.map_code}**\n"
        f"`Map` {sub.map_name}\n"
        f"`Type` {', '.join(sub.map_types)}"
        + (f"\n`Description` {sub.description}" if sub.description else "")
    )
    detail_item: str | ui.Item = details
    if sub.image_url and not showcase_image:
        detail_item = ui.Section(
            ui.TextDisplay(details), accessory=ui.Thumbnail(sub.image_url)
        )
    gallery = ui.MediaGallery()
    if sub.image_url:
        gallery.add_item(media=sub.image_url)
    return [
        f"## {header}",
        detail_item,
        ui.Separator(),
        _levels_display(sub.levels),
        *((gallery,) if showcase_image and sub.image_url else ()),
    ]


class MapSubmitModal(ui.Modal, title="Map Submission"):
    """Collects map types, description, levels, and screenshot for a new map.

    Slash-command arguments (code, name) are validated by their transformers
    before this modal opens; the modal gathers everything the command line
    can't express, then hands off to a Confirm preview.
    """

    def __init__(
        self,
        *,
        map_code: str,
        map_name: str,
        map_type_options: list[str],
    ) -> None:
        super().__init__()
        self.map_code = map_code
        self.map_name = map_name

        options = [discord.SelectOption(label=t) for t in map_type_options[:25]]
        self.map_types = ui.Select(
            placeholder="Map type(s)",
            min_values=1,
            max_values=len(options),
            options=options,
        )
        self.add_item(ui.Label(text="Map type(s)", component=self.map_types))

        self.description = ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=100,
        )
        self.add_item(self.description)

        self.levels = ui.TextInput(
            style=discord.TextStyle.paragraph,
            placeholder="Level 1\nLevel 2\nTrial of Agony",
            max_length=_LEVELS_MAX_LENGTH,
        )
        self.add_item(
            ui.Label(
                text=_LEVELS_LABEL,
                description=_LEVELS_DESCRIPTION,
                component=self.levels,
            )
        )

        self._screenshot = ui.FileUpload(required=False)
        self.add_item(
            ui.Label(
                text="Screenshot",
                description="Optional image shown on the map card.",
                component=self._screenshot,
            )
        )

    @property
    def image(self) -> discord.Attachment | None:
        return self._screenshot.values[0] if self._screenshot.values else None

    async def on_submit(self, itx: AkandeItx) -> None:
        sub = MapSubmission(
            map_code=self.map_code,
            map_name=self.map_name,
            map_types=self.map_types.values,
            description=self.description.value,
            levels=_parse_levels(self.levels.value),
            image_url=self.image.url if self.image else None,
        )
        final = await MapSubmissionReview.prompt(itx, sub)
        if final is None:
            return

        async with itx.client.acquire() as svc, transaction(svc.db):
            await svc.maps.create_map(
                map_name=final.map_name,
                map_type=final.map_types,
                map_code=final.map_code,
                description=final.description or None,
                image=None,
            )
            await svc.maps.add_creator(final.map_code, itx.user.id)
            await svc.maps.add_levels(final.map_code, final.levels)

        await self._announce(itx, final)

    async def on_error(self, itx: AkandeItx, error: Exception) -> None:
        if isinstance(error, UserFacingError):
            await views.send_error(itx, str(error))
            return
        await super().on_error(itx, error)

    async def _announce(self, itx: AkandeItx, sub: MapSubmission) -> None:
        assert itx.guild
        channel = itx.guild.get_channel(itx.client.config.channels.submission.new_maps)
        if not isinstance(channel, discord.TextChannel):
            logger.warning("New-maps channel not found; skipping announcement.")
            return

        file = await self.image.to_file(filename="image.png") if self.image else None
        if file:
            sub = structs.replace(sub, image_url="attachment://image.png")
        else:
            # No screenshot supplied - fall back to the default map banner.
            sub = structs.replace(sub, image_url=_map_banner_url(sub.map_name))
        view = views.Card(
            map_submission_body(
                sub,
                header=f"New map by {itx.user.display_name}",
                showcase_image=True,
            )
        )
        message = (
            await channel.send(view=view, file=file)
            if file
            else await channel.send(view=view)
        )

        if message.attachments:
            async with itx.client.acquire() as svc:
                await svc.maps.set_map_image(sub.map_code, message.attachments[0].url)

        await message.create_thread(name=f"Discuss {sub.map_code} here.")


class _LevelEditModal(ui.Modal, title="Edit Levels"):
    """Bulk editor for the staged level list.

    Editing the pre-filled text is add, remove, and rename in one gesture:
    insert a line, delete a line, or change a line.
    """

    def __init__(self, review: MapSubmissionReview) -> None:
        super().__init__()
        self._review = review
        self.levels = ui.TextInput(
            style=discord.TextStyle.paragraph,
            default="\n".join(review.sub.levels),
            max_length=_LEVELS_MAX_LENGTH,
        )
        self.add_item(
            ui.Label(
                text=_LEVELS_LABEL,
                description=_LEVELS_DESCRIPTION,
                component=self.levels,
            )
        )

    async def on_submit(self, itx: AkandeItx) -> None:
        await self._review.update_levels(itx, _parse_levels(self.levels.value))

    async def on_error(self, itx: AkandeItx, error: Exception) -> None:
        if isinstance(error, UserFacingError):
            await views.send_error(itx, str(error))
            return
        await super().on_error(itx, error)


class _ReviewButtons(ui.ActionRow["MapSubmissionReview"]):
    @ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        assert self.view
        await self.view._resolve(interaction, confirmed=True)

    @ui.button(label="Edit Levels", style=discord.ButtonStyle.grey)
    async def edit_levels(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        assert self.view
        await interaction.response.send_modal(_LevelEditModal(self.view))

    @ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button) -> None:
        assert self.view
        await self.view._resolve(interaction, confirmed=False)


class MapSubmissionReview(views.BaseLayoutView):
    """Map submission preview with in-place level editing.

    ``prompt()`` returns the final ``MapSubmission`` (including any level
    edits) on confirm, or ``None`` on cancel/timeout.
    """

    def __init__(
        self, itx: AkandeItx, sub: MapSubmission, *, timeout: float = 300.0
    ) -> None:
        super().__init__(itx, timeout=timeout)
        self.sub = sub
        self.result: MapSubmission | None = None
        self._buttons = _ReviewButtons()
        self._render(self._buttons)

    def _render(self, footer: ui.Item) -> None:
        self.clear_items()
        body = [
            ui.TextDisplay(item) if isinstance(item, str) else item
            for item in map_submission_body(
                self.sub, header="Map Submission - Is this correct?"
            )
        ]
        self.add_item(ui.Container(*body, ui.Separator(), footer))

    async def update_levels(self, itx: discord.Interaction, levels: list[str]) -> None:
        """Swap the staged level list and re-render the preview in place."""
        self.sub = structs.replace(self.sub, levels=levels)
        self._render(self._buttons)
        await itx.response.edit_message(view=self)

    async def _resolve(self, itx: discord.Interaction, *, confirmed: bool) -> None:
        self.result = self.sub if confirmed else None
        self._render(ui.TextDisplay("✅ Confirmed" if confirmed else "❌ Cancelled"))
        await itx.response.edit_message(view=self)
        self.stop()

    @classmethod
    async def prompt(cls, itx: AkandeItx, sub: MapSubmission) -> MapSubmission | None:
        view = cls(itx, sub)
        if itx.response.is_done():
            await itx.edit_original_response(view=view)
        else:
            await itx.response.send_message(view=view, ephemeral=True)
        await view.wait()
        return view.result
