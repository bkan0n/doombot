from datetime import datetime, timedelta

import msgspec

from ._base import Service


class DuelInfo(msgspec.Struct, frozen=True):
    id: int
    thread_id: int
    message_id: int
    map_code: str
    level: str
    wager: int
    season: int
    duration: timedelta
    status: str
    ready_deadline: datetime
    started_at: datetime | None
    ends_at: datetime | None


class DuelPlayerInfo(msgspec.Struct, frozen=True):
    user_id: int
    num: int
    ready: bool
    record: float | None
    screenshot: str | None


class DuelActivation(msgspec.Struct, frozen=True):
    started_at: datetime
    ends_at: datetime


class DuelTransition(msgspec.Struct, frozen=True):
    duel_id: int
    kind: str
    fires_at: datetime
    due_now: bool


class _XPCheck(msgspec.Struct, frozen=True):
    p1_ok: bool
    p2_ok: bool


class DuelService(Service):
    """Duel lifecycle, per-player duel rows, and pre-duel eligibility checks."""

    async def create_duel(
        self,
        thread_id: int,
        message_id: int,
        map_code: str,
        level: str,
        wager: int,
        season: int,
        duration: timedelta,
        ready_deadline: datetime,
        player_one: int,
        player_two: int,
    ) -> int:
        query = """--sql
            INSERT INTO duels
            (thread_id, message_id, map_code, level, wager, season, duration, ready_deadline)
            VALUES
            (
              :thread_id,
              :message_id,
              :map_code,
              :level,
              :wager,
              :season,
              :duration,
              :ready_deadline
            )
            RETURNING id;
        """
        duel_id: int = await self._db.select_value(
            query,
            thread_id=thread_id,
            message_id=message_id,
            map_code=map_code,
            level=level,
            wager=wager,
            season=season,
            duration=duration,
            ready_deadline=ready_deadline,
        )
        query = """--sql
            INSERT INTO duel_players (duel_id, user_id, num)
            VALUES ($1, $2, $3);
        """
        await self._db.execute_many(
            query, [(duel_id, player_one, 1), (duel_id, player_two, 2)]
        )
        return duel_id

    async def fetch_duel(self, duel_id: int) -> DuelInfo | None:
        query = """--sql
            SELECT
              id,
              thread_id,
              message_id,
              map_code,
              level,
              wager,
              season,
              duration,
              status,
              ready_deadline,
              started_at,
              ends_at
            FROM duels
            WHERE id = :duel_id;
        """
        return await self._db.select_one_or_none(
            query, duel_id=duel_id, schema_type=DuelInfo
        )

    async def fetch_duel_by_thread(self, thread_id: int) -> DuelInfo | None:
        query = """--sql
            SELECT
              id,
              thread_id,
              message_id,
              map_code,
              level,
              wager,
              season,
              duration,
              status,
              ready_deadline,
              started_at,
              ends_at
            FROM duels
            WHERE thread_id = :thread_id;
        """
        return await self._db.select_one_or_none(
            query, thread_id=thread_id, schema_type=DuelInfo
        )

    async def fetch_pending_duels(self) -> list[DuelInfo]:
        query = """--sql
            SELECT
              id,
              thread_id,
              message_id,
              map_code,
              level,
              wager,
              season,
              duration,
              status,
              ready_deadline,
              started_at,
              ends_at
            FROM duels
            WHERE status = 'pending'
            ORDER BY id;
        """
        return await self._db.select(query, schema_type=DuelInfo)

    async def fetch_players(self, duel_id: int) -> list[DuelPlayerInfo]:
        query = """--sql
            SELECT
              user_id,
              num,
              ready,
              record,
              screenshot
            FROM duel_players
            WHERE duel_id = :duel_id
            ORDER BY num;
        """
        return await self._db.select(query, duel_id=duel_id, schema_type=DuelPlayerInfo)

    async def is_either_in_open_duel(self, player_one: int, player_two: int) -> bool:
        query = """--sql
            SELECT 1
            FROM duel_players AS dp
            INNER JOIN duels AS d ON dp.duel_id = d.id
            WHERE
              (dp.user_id = :player_one OR dp.user_id = :player_two)
              AND d.status IN ('pending', 'active')
            LIMIT 1;
        """
        row = await self._db.select_value_or_none(
            query, player_one=player_one, player_two=player_two
        )
        return row is not None

    async def check_xp(
        self, player_one: int, player_two: int, wager: int, season: int
    ) -> bool:
        query = """--sql
            SELECT
              COUNT(*) FILTER (WHERE user_id = :player_one AND xp >= :wager) > 0 AS p1_ok,
              COUNT(*) FILTER (WHERE user_id = :player_two AND xp >= :wager) > 0 AS p2_ok
            FROM user_xp
            WHERE season = :season;
        """
        row = await self._db.select_one_or_none(
            query,
            player_one=player_one,
            player_two=player_two,
            wager=wager,
            season=season,
            schema_type=_XPCheck,
        )
        return row is not None and row.p1_ok and row.p2_ok

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

    async def set_ready(self, duel_id: int, user_id: int) -> None:
        query = """--sql
            UPDATE duel_players
            SET ready = TRUE
            WHERE duel_id = :duel_id AND user_id = :user_id;
        """
        await self._db.execute(query, duel_id=duel_id, user_id=user_id)

    async def try_activate(self, duel_id: int) -> DuelActivation | None:
        """Flip pending → active iff both players are ready; None if not fired."""
        query = """--sql
            UPDATE duels
            SET
              status = 'active',
              started_at = NOW(),
              ends_at = NOW() + duration
            WHERE
              id = :duel_id
              AND status = 'pending'
              AND NOT EXISTS (
                SELECT 1
                FROM duel_players
                WHERE duel_id = :duel_id AND NOT ready
              )
            RETURNING started_at, ends_at;
        """
        return await self._db.select_one_or_none(
            query, duel_id=duel_id, schema_type=DuelActivation
        )

    async def fetch_next_transition(self) -> DuelTransition | None:
        query = """--sql
            SELECT
              duel_id,
              kind,
              fires_at,
              fires_at <= NOW() AS due_now
            FROM (
              SELECT
                id AS duel_id,
                'deadline' AS kind,
                ready_deadline AS fires_at
              FROM duels
              WHERE status = 'pending'
              UNION ALL
              SELECT
                id AS duel_id,
                'end' AS kind,
                ends_at AS fires_at
              FROM duels
              WHERE status = 'active'
            ) AS transitions
            ORDER BY fires_at
            LIMIT 1;
        """
        return await self._db.select_one_or_none(query, schema_type=DuelTransition)

    async def submit_record(
        self, duel_id: int, user_id: int, record: float, screenshot: str
    ) -> float | None:
        """Store a better (lower) time; None means the existing best was kept."""
        query = """--sql
            UPDATE duel_players
            SET
              record = :record,
              screenshot = :screenshot
            WHERE
              duel_id = :duel_id
              AND user_id = :user_id
              AND (record IS NULL OR record > :record)
            RETURNING record;
        """
        value = await self._db.select_value_or_none(
            query,
            duel_id=duel_id,
            user_id=user_id,
            record=record,
            screenshot=screenshot,
        )
        return None if value is None else float(value)

    async def cancel_duel(self, duel_id: int) -> bool:
        query = """--sql
            UPDATE duels
            SET status = 'cancelled'
            WHERE id = :duel_id AND status = 'pending'
            RETURNING TRUE;
        """
        row = await self._db.select_value_or_none(query, duel_id=duel_id)
        return row is not None

    async def complete_duel(
        self, duel_id: int, results: list[tuple[int, int, int]]
    ) -> None:
        """Mark complete and write per-player results as (result, duel_id, user_id)."""
        query = """--sql
            UPDATE duels
            SET status = 'complete'
            WHERE id = :duel_id;
        """
        await self._db.execute(query, duel_id=duel_id)
        query = """--sql
            UPDATE duel_players
            SET result = $1
            WHERE duel_id = $2 AND user_id = $3;
        """
        await self._db.execute_many(query, results)
