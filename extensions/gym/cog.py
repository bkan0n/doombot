from __future__ import annotations

import itertools
import typing

from discord import app_commands, ui

from database.services.gym import ExerciseDefinition
from utilities import checks, views
from utilities.errors import UserFacingError

from .._base import BaseCog
from . import calc
from .views import ExerciseBrowser, exercise_detail_items

if typing.TYPE_CHECKING:
    from core import AkandeItx

Units = typing.Literal["kg", "lb"]
Category = typing.Literal["Max", "Reps", "Time"]

BodyPart = typing.Literal[
    "back",
    "cardio",
    "chest",
    "lower arms",
    "lower legs",
    "neck",
    "shoulders",
    "upper arms",
    "upper legs",
    "waist",
]
Equipment = typing.Literal[
    "assisted",
    "band",
    "barbell",
    "body weight",
    "bosu ball",
    "cable",
    "dumbbell",
    "elliptical machine",
    "ez barbell",
    "kettlebell",
    "leverage machine",
    "medicine ball",
    "resistance band",
    "skierg machine",
    "sled machine",
    "smith machine",
    "stability ball",
    "stationary bike",
    "stepmill machine",
    "trap bar",
    "upper body ergometer",
    "weighted",
    "wheel roller",
]


class ExerciseTransformer(app_commands.Transformer):
    """A PR-tracked exercise from all_exercises; transforms to its definition."""

    async def transform(self, itx: AkandeItx, value: str) -> ExerciseDefinition:
        async with itx.client.acquire() as svc:
            definitions = await svc.gym.fetch_exercise_definitions()
        for definition in definitions:
            if definition.name.casefold() == value.casefold():
                return definition
        raise UserFacingError("This exercise does not exist.")

    async def autocomplete(
        self, itx: AkandeItx, current: str
    ) -> list[app_commands.Choice[str]]:
        async with itx.client.acquire() as svc:
            definitions = await svc.gym.fetch_exercise_definitions()
        needle = current.casefold()
        return [
            app_commands.Choice(name=d.name, value=d.name)
            for d in definitions
            if needle in d.name.casefold()
        ][:25]


async def _autocomplete_catalog_names(
    itx: AkandeItx, current: str
) -> list[app_commands.Choice[str]]:
    async with itx.client.acquire() as svc:
        names = await svc.gym.autocomplete_exercise_names(current)
    return [app_commands.Choice(name=name[:100], value=name) for name in names]


class GymCog(BaseCog, name="gym", description="Gym PRs and exercise tools."):
    """Gym"""

    _gym = app_commands.Group(name="gym", description="Gym PRs and exercise tools")

    async def interaction_check(self, itx: AkandeItx) -> bool:
        gym_channel = itx.client.config.channels.gym
        if itx.channel_id != gym_channel:
            raise UserFacingError(f"Gym commands can only be used in <#{gym_channel}>.")
        return True

    @_gym.command(name="convert", description="Convert between lb and kg")
    @app_commands.describe(value="The weight to convert", unit="Unit of the value")
    async def convert(
        self, itx: AkandeItx, value: float, unit: Units | None = None
    ) -> None:
        kg = calc.lb_to_kg(value)
        lb = calc.kg_to_lb(value)
        if unit == "lb":
            output = f"{value} lb ≈ {kg} kg"
        elif unit == "kg":
            output = f"{value} kg ≈ {lb} lb"
        else:
            output = f"{value} lb ≈ {kg} kg\n{value} kg ≈ {lb} lb"
        await itx.response.send_message(output)

    @_gym.command(name="one-rep-max", description="Calculate your one-rep-max weight")
    @app_commands.describe(
        weight="The weight used in your exercise",
        unit="Unit of the weight",
        reps="The number of reps used (1-36)",
    )
    async def one_rep_max(
        self,
        itx: AkandeItx,
        weight: app_commands.Range[float, 0.0],
        unit: Units,
        reps: app_commands.Range[int, 1, 36],
    ) -> None:
        kg = calc.lb_to_kg(weight) if unit == "lb" else weight
        lb = weight if unit == "lb" else calc.kg_to_lb(weight)
        lines = [f"### Your 1RM based on {reps} reps of {kg} kg / {lb} lb"]
        for formula, method in calc.ONE_REP_MAX_FORMULAS.items():
            max_kg = round(method(kg, reps), 2)
            max_lb = calc.kg_to_lb(max_kg)
            lines.append(f"- {formula}: ≈ {max_kg} kg / {max_lb} lb")
        await itx.response.send_message("\n".join(lines))

    @_gym.command(name="add-pr", description="Add your PR for an exercise")
    @app_commands.describe(
        exercise="The exercise to add a PR for",
        value="Weight, reps, or time (seconds)",
        unit="Unit of weight (weight-based exercises only)",
    )
    async def add_pr(
        self,
        itx: AkandeItx,
        exercise: app_commands.Transform[ExerciseDefinition, ExerciseTransformer],
        value: app_commands.Range[float, 0.0],
        unit: Units | None = None,
    ) -> None:
        await itx.response.defer()
        if exercise.type == "Max":
            kg = calc.lb_to_kg(value) if unit == "lb" else value
            lb = value if unit == "lb" else calc.kg_to_lb(value)
            stored, display = kg, f"{kg} kg / {lb} lb"
        elif exercise.type == "Reps":
            stored, display = float(int(value)), f"{int(value)} reps"
        else:  # Time
            stored, display = value, f"{value} seconds"
        async with itx.client.acquire() as svc:
            await svc.gym.upsert_pr(itx.user.id, exercise.name, stored)
        await itx.edit_original_response(
            content=f"{itx.user.mention} your {exercise.name} PR is set to {display}."
        )

    @_gym.command(name="show-pr", description="PR leaderboard per exercise")
    @app_commands.describe(exercise="The exercise leaderboard to view")
    async def show_pr(
        self,
        itx: AkandeItx,
        exercise: app_commands.Transform[ExerciseDefinition, ExerciseTransformer],
    ) -> None:
        await itx.response.defer()
        async with itx.client.acquire() as svc:
            entries = await svc.gym.fetch_exercise_leaderboard(exercise.name)
        if not entries:
            raise UserFacingError("No PRs submitted for this exercise yet.")

        def fmt(value: float) -> str:
            if exercise.type == "Max":
                return f"{value} kg / {calc.kg_to_lb(value)} lb"
            if exercise.type == "Reps":
                return f"{int(value)} reps"
            return f"{value} seconds"

        pages: list[list[str | ui.Item]] = [
            [
                f"### {exercise.name} Leaderboard",
                *(
                    f"{position}. {entry.nickname} — {fmt(entry.value)}"
                    for position, entry in chunk
                ),
            ]
            for chunk in itertools.batched(enumerate(entries, start=1), 10)
        ]
        await views.Paginator(itx, pages).start(ephemeral=False)

    @_gym.command(name="add-exercise", description="Add an exercise to the PR list")
    @app_commands.describe(name="Exercise name", category="How the PR is measured")
    @checks.is_staff()
    async def add_exercise(
        self, itx: AkandeItx, name: app_commands.Range[str, 1, 100], category: Category
    ) -> None:
        async with itx.client.acquire() as svc:
            definitions = await svc.gym.fetch_exercise_definitions()
            if any(d.name.casefold() == name.casefold() for d in definitions):
                raise UserFacingError("This exercise already exists.")
            await svc.gym.add_exercise(name, category)
        await itx.response.send_message(f"Added {name} to the exercise list.")

    @_gym.command(name="exercise-search", description="Browse the exercise catalog")
    @app_commands.describe(
        location="Body part", equipment="Equipment", name="Exercise name"
    )
    @app_commands.autocomplete(name=_autocomplete_catalog_names)
    async def exercise_search(
        self,
        itx: AkandeItx,
        location: BodyPart | None = None,
        equipment: Equipment | None = None,
        name: str | None = None,
    ) -> None:
        await itx.response.defer(ephemeral=True)
        async with itx.client.acquire() as svc:
            if not location and not equipment and not name:
                random_exercise = await svc.gym.fetch_random_exercise()
                if random_exercise is None:
                    raise UserFacingError("No exercises found.")
                await itx.edit_original_response(
                    view=views.Card(exercise_detail_items(random_exercise))
                )
                return
            results = await svc.gym.search_exercises(location, equipment, name)
        if not results:
            raise UserFacingError("No exercises found.")
        await itx.edit_original_response(view=ExerciseBrowser(itx, results))
