from typing import TYPE_CHECKING

import msgspec

from ._base import Service

if TYPE_CHECKING:
    from datetime import datetime


class DuelXPCheck(msgspec.Struct, frozen=True):
    p1_xp: bool
    p2_xp: bool


class DuelService(Service):
    """Duel lifecycle, per-player duel rows, and pre-duel eligibility checks."""

    async def create_duel(
        self,
        thread_id: int,
        thread_msg: int,
        wager: int,
        start: datetime,
        end: datetime,
    ) -> int:
        query = """--sql
            INSERT INTO duels (thread_id, thread_msg, wager, start, "end")
            VALUES (:thread_id, :thread_msg, :wager, :start, :end)
            RETURNING id;
        """
        return await self._db.select_value(
            query,
            thread_id=thread_id,
            thread_msg=thread_msg,
            wager=wager,
            start=start,
            end=end,
        )

    async def add_duel_players(self, rows: list[tuple[int, bool, int, int]]) -> None:
        query = """--sql
            INSERT INTO user_duels (user_id, ready, duel_id, num)
            VALUES ($1, $2, $3, $4);
        """
        await self._db.execute_many(query, rows)

    async def is_either_in_duel(self, player_one: int, player_two: int) -> bool:
        query = """--sql
            SELECT 1
            FROM user_duels
            WHERE (user_id = :player_one OR user_id = :player_two) AND result = 0
            LIMIT 1;
        """
        row = await self._db.select_value_or_none(
            query, player_one=player_one, player_two=player_two
        )
        return row is not None

    async def check_xp(self, player_one: int, player_two: int, wager: int) -> bool:
        query = """--sql
            WITH p1 AS (
              SELECT
                1 AS id,
                xp >= :wager AS p1_xp
              FROM user_xp
              WHERE user_id = :player_one
            ),
            
            p2 AS (
              SELECT
                1 AS id,
                xp >= :wager AS p2_xp
              FROM user_xp
              WHERE user_id = :player_two
            )
            
            SELECT
              p1.p1_xp,
              p2.p2_xp
            FROM p1
            INNER JOIN p2 ON p1.id = p2.id
            LIMIT 1;
        """
        row = await self._db.select_one_or_none(
            query,
            player_one=player_one,
            player_two=player_two,
            wager=wager,
            schema_type=DuelXPCheck,
        )
        return row is not None and row.p1_xp and row.p2_xp

    async def fetch_random_map_code(self) -> str | None:
        query = """--sql
            SELECT map_code
            FROM maps
            LIMIT
              1
              OFFSET FLOOR(RANDOM() * (SELECT COUNT(m.map_code) FROM maps AS m));
        """
        return await self._db.select_value_or_none(query)

    async def fetch_random_level(self, map_code: str) -> str | None:
        query = """--sql
            SELECT level
            FROM map_levels
            WHERE map_code = :map_code
            LIMIT
              1
              OFFSET FLOOR(
                RANDOM()
                * (
                  SELECT COUNT(*)
                  FROM map_levels AS ml
                  WHERE ml.map_code = :map_code
                )
              );
        """
        return await self._db.select_value_or_none(query, map_code=map_code)

    async def set_ready(self, duel_id: int, user_id: int, ready: bool) -> None:
        query = """--sql
            UPDATE user_duels
            SET ready = :ready
            WHERE duel_id = :duel_id AND user_id = :user_id;
        """
        await self._db.execute(query, duel_id=duel_id, user_id=user_id, ready=ready)
