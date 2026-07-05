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
    "MapSubmitModal",
    "map_search_pages",
    "map_submission_body",
    "random_map_card",
)

MAPS_PER_PAGE = 5

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
        "**Levels**\n" + "\n".join(sub.levels),
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
            label="Level Names",
            style=discord.TextStyle.paragraph,
            placeholder="Add all level names, each on a new line.\nLevel 1\nLevel 2\nTrial of Agony",
        )
        self.add_item(self.levels)

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

    async def on_submit(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, itx: AkandeItx
    ) -> None:
        levels = list(
            dict.fromkeys(
                stripped
                for line in self.levels.value.splitlines()
                if (stripped := line.strip())
            )
        )
        if not levels:
            raise UserFacingError("At least one level name is required.")

        sub = MapSubmission(
            map_code=self.map_code,
            map_name=self.map_name,
            map_types=self.map_types.values,
            description=self.description.value,
            levels=levels,
            image_url=self.image.url if self.image else None,
        )
        confirmed = await views.Confirm.prompt(
            itx,
            *map_submission_body(sub, header="Map Submission - Is this correct?"),
        )
        if not confirmed:
            return

        async with itx.client.acquire() as svc, transaction(svc.db):
            await svc.maps.create_map(
                map_name=sub.map_name,
                map_type=sub.map_types,
                map_code=sub.map_code,
                description=sub.description or None,
                image=None,
            )
            await svc.maps.add_creator(sub.map_code, itx.user.id)
            await svc.maps.add_levels(sub.map_code, sub.levels)

        await self._announce(itx, sub)

    async def on_error(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, itx: AkandeItx, error: Exception
    ) -> None:
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
