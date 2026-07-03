from __future__ import annotations

import typing

import discord
from discord import ui
from loguru import logger

if typing.TYPE_CHECKING:
    from core import AkandeItx

__all__ = (
    "BaseLayoutView",
    "Confirm",
)


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

    async def on_timeout(self) -> None:
        for child in self.walk_children():
            if hasattr(child, "disabled"):
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
        await self.view._resolve(interaction, value=True)

    @ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button) -> None:
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
        self, itx: AkandeItx, *items: str | ui.Item, timeout: float = 120.0
    ) -> None:
        super().__init__(itx, timeout=timeout)
        self.value: bool | None = None
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
    ) -> bool:
        """Send a confirmation prompt and wait for the user's choice.

        Returns ``True`` on confirm; ``False`` on cancel or timeout. To
        distinguish timeout from cancel, construct the view directly and
        inspect ``.value`` (``None`` = timeout, ``False`` = cancel).
        """
        view = cls(itx, *items, timeout=timeout)
        if itx.response.is_done():
            await itx.edit_original_response(view=view)
        else:
            await itx.response.send_message(view=view, ephemeral=ephemeral)
        await view.wait()
        return bool(view.value)
