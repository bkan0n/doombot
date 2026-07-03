import msgspec

from ._base import Service


class GymRecord(msgspec.Struct, frozen=True):
    user_id: int
    exercise: str
    value: float


class Exercise(msgspec.Struct, frozen=True):
    name: str
    location: str | None
    target: str | None
    equipment: str | None
    url: str | None


class ExerciseDefinition(msgspec.Struct, frozen=True):
    name: str
    type: str


class GymService(Service):
    """Gym PRs, exercise definitions, and exercise search."""

    async def upsert_pr(self, user_id: int, exercise: str, value: float) -> None:
        query = """--sql
            INSERT INTO gym_records (user_id, exercise, value)
            VALUES (:user_id, :exercise, :value)
            ON CONFLICT (user_id, exercise) DO UPDATE
              SET value = :value;
        """
        await self._db.execute(query, user_id=user_id, exercise=exercise, value=value)

    async def add_exercise(self, name: str, exercise_type: str) -> None:
        query = """--sql
            INSERT INTO all_exercises (name, type)
            VALUES (:name, :exercise_type);
        """
        await self._db.execute(query, name=name, exercise_type=exercise_type)

    async def fetch_exercise_prs(self, exercise: str) -> list[GymRecord]:
        query = """--sql
            SELECT
              user_id,
              exercise,
              CAST(value AS FLOAT) AS value
            FROM gym_records
            WHERE exercise = :exercise
            ORDER BY value DESC;
        """
        return await self._db.select(query, exercise=exercise, schema_type=GymRecord)

    async def search_exercises(
        self, location: str | None, equipment: str | None, name: str | None
    ) -> list[Exercise]:
        query = """--sql
            SELECT
              name,
              location,
              target,
              equipment,
              url
            FROM exercises
            WHERE
              (CAST(:location AS TEXT) IS NULL OR location = :location)
              AND (CAST(:equipment AS TEXT) IS NULL OR equipment = :equipment)
              AND (CAST(:name AS TEXT) IS NULL OR name = :name)
            ORDER BY name;
        """
        return await self._db.select(
            query,
            location=location,
            equipment=equipment,
            name=name,
            schema_type=Exercise,
        )

    async def fetch_exercise_definitions(self) -> list[ExerciseDefinition]:
        query = """--sql
            SELECT
              name,
              type
            FROM all_exercises
            ORDER BY name;
        """
        return await self._db.select(query, schema_type=ExerciseDefinition)
