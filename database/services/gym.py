import msgspec

from ._base import Service


class GymLeaderboardEntry(msgspec.Struct, frozen=True):
    nickname: str
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

    async def fetch_exercise_leaderboard(
        self, exercise: str
    ) -> list[GymLeaderboardEntry]:
        query = """--sql
            SELECT
              COALESCE(u.nickname, 'Unknown User') AS nickname,
              CAST(g.value AS FLOAT) AS value
            FROM gym_records AS g
            LEFT JOIN users AS u ON g.user_id = u.user_id
            WHERE g.exercise = :exercise
            ORDER BY g.value DESC;
        """
        return await self._db.select(
            query, exercise=exercise, schema_type=GymLeaderboardEntry
        )

    async def autocomplete_exercise_names(self, search: str) -> list[str]:
        query = """--sql
            SELECT name
            FROM exercises
            ORDER BY SIMILARITY(name, :search) DESC, name
            LIMIT 25;
        """
        rows = await self._db.select(query, search=search)
        return [row["name"] for row in rows]

    async def fetch_random_exercise(self) -> Exercise | None:
        query = """--sql
            SELECT
              name,
              location,
              target,
              equipment,
              url
            FROM exercises
            ORDER BY RANDOM()
            LIMIT 1;
        """
        return await self._db.select_one_or_none(query, schema_type=Exercise)

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
