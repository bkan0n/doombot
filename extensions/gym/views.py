from __future__ import annotations

import typing

import discord
from discord import ui

from utilities.views import BaseLayoutView

if typing.TYPE_CHECKING:
    from core import AkandeItx
    from database.services.gym import Exercise

_PER_PAGE = 10


def exercise_detail_items(exercise: Exercise) -> list[str | ui.Item]:
    """Detail card body for a single exercise."""
    items: list[str | ui.Item] = [
        f"### {exercise.name}\n"
        f"**Location:** {exercise.location}\n"
        f"**Target:** {exercise.target}\n"
        f"**Equipment:** {exercise.equipment}"
    ]
    if exercise.url:
        items.append(ui.MediaGallery(discord.MediaGalleryItem(exercise.url)))
    return items


class _ExerciseSelectRow(ui.ActionRow["ExerciseBrowser"]):
    @ui.select(placeholder="Select an exercise.")
    async def pick(self, itx: AkandeItx, select: ui.Select[ExerciseBrowser]) -> None:
        assert self.view
        await self.view.show_exercise(itx, int(select.values[0]))

    def update_options(self, exercises: list[Exercise], offset: int) -> None:
        self.pick.options = [
            discord.SelectOption(label=exercise.name[:100], value=str(offset + i))
            for i, exercise in enumerate(exercises)
        ]


class _NavRow(ui.ActionRow["ExerciseBrowser"]):
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

    def update_state(self, page: int, total: int) -> None:
        self.counter.label = f"{page + 1}/{total}"


class ExerciseBrowser(BaseLayoutView):
    """Paged exercise catalog: a select per page, details render in place."""

    def __init__(self, itx: AkandeItx, exercises: list[Exercise]) -> None:
        super().__init__(itx, timeout=300.0)
        self._exercises = exercises
        self._page = 0
        self._selected: Exercise | None = None
        self._select_row = _ExerciseSelectRow()
        self._nav = _NavRow()
        self._render()

    @property
    def _total_pages(self) -> int:
        return -(-len(self._exercises) // _PER_PAGE)

    def _render(self) -> None:
        self.clear_items()
        start = self._page * _PER_PAGE
        self._select_row.update_options(
            self._exercises[start : start + _PER_PAGE], start
        )
        items: list[ui.Item] = [
            ui.TextDisplay(f"## Exercises\n-# {len(self._exercises)} found")
        ]
        if self._selected is not None:
            items.extend(
                ui.TextDisplay(item) if isinstance(item, str) else item
                for item in exercise_detail_items(self._selected)
            )
        items.append(ui.Separator())
        items.append(self._select_row)
        if self._total_pages > 1:
            self._nav.update_state(self._page, self._total_pages)
            items.append(self._nav)
        self.add_item(ui.Container(*items))

    async def show_exercise(self, itx: AkandeItx, index: int) -> None:
        self._selected = self._exercises[index]
        self._render()
        await itx.response.edit_message(view=self)

    async def flip(self, itx: AkandeItx, delta: int) -> None:
        self._page = (self._page + delta) % self._total_pages
        self._render()
        await itx.response.edit_message(view=self)
