from __future__ import annotations

import typing

import discord
from discord import ui
from loguru import logger

from utilities.errors import UserFacingError

if typing.TYPE_CHECKING:
    from core import AkandeItx

__all__ = (
    "BaseLayoutView",
    "Card",
    "Confirm",
    "ErrorView",
    "Paginator",
    "send_error",
    "toggle_role",
)


class Card(ui.LayoutView):
    """Card message; items may include interactive rows (e.g. an ActionRow)."""

    def __init__(self, items: list[str | ui.Item]) -> None:
        super().__init__(timeout=None)
        wrapped = [
            ui.TextDisplay(item) if isinstance(item, str) else item for item in items
        ]
        self.add_item(ui.Container(*wrapped))


class ErrorView(ui.LayoutView):
    """Static error-state card for user-facing failures."""

    def __init__(self, message: str) -> None:
        super().__init__(timeout=None)
        self.add_item(
            ui.Container(
                ui.TextDisplay(f"⚠️ {message}"),
                accent_colour=discord.Colour.red(),
            )
        )


async def send_error(itx: discord.Interaction, message: str) -> None:
    """Show a user-facing error, replacing the current view when one exists.

    Deferred/responded interactions get their original response swapped for
    the error card; component interactions get their message's view replaced
    in place; anything else gets a fresh ephemeral error card.
    """
    view = ErrorView(message)
    try:
        if itx.response.is_done():
            await itx.edit_original_response(view=view)
        elif itx.type is discord.InteractionType.component:
            await itx.response.edit_message(view=view)
        else:
            await itx.response.send_message(view=view, ephemeral=True)
    except discord.HTTPException as e:
        logger.debug(f"Failed to deliver user-facing error: {e}")


async def toggle_role(itx: AkandeItx, role_id: int) -> None:
    """Toggle a configured role on the invoker of a deferred component itx."""
    assert itx.guild and isinstance(itx.user, discord.Member)
    role = itx.guild.get_role(role_id)
    if role is None:
        raise UserFacingError("That role is not configured.")
    if role in itx.user.roles:
        await itx.user.remove_roles(role)
        message = f"Removed **{role.name}**."
    else:
        await itx.user.add_roles(role)
        message = f"Added **{role.name}**."
    await itx.followup.send(message, ephemeral=True)


class BaseLayoutView(ui.LayoutView):
    """LayoutView restricted to its invoker, with a user-visible timeout state."""

    def __init__(self, itx: AkandeItx, *, timeout: float) -> None:
        super().__init__(timeout=timeout)
        self.itx = itx

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.itx.user.id:
            await interaction.response.send_message(
                "This isn't for you.", ephemeral=True
            )
            return False
        return True

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: ui.Item
    ) -> None:
        if isinstance(error, UserFacingError):
            await send_error(interaction, str(error))
            return
        await super().on_error(interaction, error, item)

    async def on_timeout(self) -> None:
        for child in self.walk_children():
            if isinstance(child, (ui.Button, ui.Select)):
                child.disabled = True
        self.add_item(ui.TextDisplay("⏱️ Timed out"))
        try:
            await self.itx.edit_original_response(view=self)
        except discord.NotFound:
            pass
        except discord.HTTPException as e:
            logger.debug(f"Failed to edit message on view timeout: {e}")


class _ConfirmButtons(ui.ActionRow["Confirm"]):
    @ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        assert self.view
        await self.view._resolve(interaction, value=True)

    @ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button) -> None:
        assert self.view
        await self.view._resolve(interaction, value=False)


class Confirm(BaseLayoutView):
    """Confirmation prompt with Confirm/Cancel buttons.

    Prefer the ``prompt()`` classmethod. Each item is a ``str`` (wrapped in
    a ``ui.TextDisplay``) or any components-v2 item that is a valid direct
    child of a ``ui.Container`` (``ui.TextDisplay``, ``ui.Section``,
    ``ui.Separator``, ``ui.MediaGallery``, ``ui.File``, ``ui.ActionRow``).
    Nesting is not re-validated here; invalid nesting fails in discord.py's
    own validation.

    Components v2 messages cannot carry ``content=``. Editing this view over
    a message that already has ``content`` requires the caller to clear the
    content first.
    """

    def __init__(
        self,
        itx: AkandeItx,
        *items: str | ui.Item,
        timeout: float = 120.0,
        defer_on_confirm: bool = False,
    ) -> None:
        super().__init__(itx, timeout=timeout)
        self.value: bool | None = None
        self._defer_on_confirm = defer_on_confirm
        self.buttons = _ConfirmButtons()
        self.container = ui.Container(
            *self._build_body(items), ui.Separator(), self.buttons
        )
        self.add_item(self.container)

    @staticmethod
    def _build_body(items: tuple[str | ui.Item, ...]) -> list[ui.Item]:
        return [
            ui.TextDisplay(item) if isinstance(item, str) else item for item in items
        ]

    async def _resolve(self, interaction: discord.Interaction, *, value: bool) -> None:
        self.value = value
        if value and self._defer_on_confirm:
            # Invisible ack (deferred message update); the caller must edit
            # this message with the outcome, else the buttons appear frozen.
            await interaction.response.defer()
            self.stop()
            return
        self.container.remove_item(self.buttons)
        self.container.add_item(
            ui.TextDisplay("✅ Confirmed" if value else "❌ Cancelled")
        )
        await interaction.response.edit_message(view=self)
        self.stop()

    @classmethod
    async def prompt(
        cls,
        itx: AkandeItx,
        *items: str | ui.Item,
        ephemeral: bool = True,
        timeout: float = 120.0,
        defer_on_confirm: bool = False,
    ) -> bool:
        """Send a confirmation prompt and wait for the user's choice.

        Returns ``True`` on confirm; ``False`` on cancel or timeout. To
        distinguish timeout from cancel, construct the view directly and
        inspect ``.value`` (``None`` = timeout, ``False`` = cancel).

        ``defer_on_confirm=True`` skips the "✅ Confirmed" render: a confirm
        click is acknowledged invisibly and the caller renders the outcome
        over this message, saving one visible edit. Cancel always renders.
        """
        view = cls(itx, *items, timeout=timeout, defer_on_confirm=defer_on_confirm)
        if itx.response.is_done():
            await itx.edit_original_response(view=view)
        else:
            await itx.response.send_message(view=view, ephemeral=ephemeral)
        await view.wait()
        return bool(view.value)


class _PaginatorNav(ui.ActionRow["Paginator"]):
    @ui.button(emoji="◀", style=discord.ButtonStyle.grey)
    async def previous(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        assert self.view
        await self.view._flip(interaction, -1)

    @ui.button(label="…", style=discord.ButtonStyle.grey, disabled=True)
    async def counter(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None: ...

    @ui.button(emoji="▶", style=discord.ButtonStyle.grey)
    async def next(self, interaction: discord.Interaction, button: ui.Button) -> None:
        assert self.view
        await self.view._flip(interaction, 1)

    def update_state(self, index: int, total: int) -> None:
        self.counter.label = f"{index + 1}/{total}"


class Paginator(BaseLayoutView):
    """Pages of components-v2 items rendered one ``ui.Container`` per page.

    Each page is a list of ``str`` (wrapped in ``ui.TextDisplay``) or any
    item that is a valid direct child of a ``ui.Container``. Navigation
    wraps around and is omitted entirely for a single page.
    """

    def __init__(
        self,
        itx: AkandeItx,
        pages: list[list[str | ui.Item]],
        *,
        timeout: float = 300.0,
    ) -> None:
        if not pages:
            raise ValueError("Paginator requires at least one page.")
        super().__init__(itx, timeout=timeout)
        self._pages = pages
        self._index = 0
        self._nav = _PaginatorNav()
        self._render()

    def _render(self) -> None:
        self.clear_items()
        items = [
            ui.TextDisplay(item) if isinstance(item, str) else item
            for item in self._pages[self._index]
        ]
        container = ui.Container(*items)
        if len(self._pages) > 1:
            self._nav.update_state(self._index, len(self._pages))
            container.add_item(ui.Separator())
            container.add_item(self._nav)
        self.add_item(container)

    async def _flip(self, interaction: discord.Interaction, delta: int) -> None:
        self._index = (self._index + delta) % len(self._pages)
        self._render()
        await interaction.response.edit_message(view=self)

    async def start(self, *, ephemeral: bool = True) -> None:
        """Send the paginator on its interaction (edit if already responded)."""
        if self.itx.response.is_done():
            await self.itx.edit_original_response(view=self)
        else:
            await self.itx.response.send_message(view=self, ephemeral=ephemeral)
