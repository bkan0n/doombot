from datetime import datetime

import msgspec

from ._base import Service


class TournamentInfo(msgspec.Struct, frozen=True):
    id: int
    title: str | None
    start: datetime
    end: datetime
    active: bool
    bracket: bool
    needs_start_task: bool
    needs_end_task: bool
    needs_start_now: bool
    needs_end_now: bool


class TournamentMap(msgspec.Struct, frozen=True):
    id: int
    code: str
    level: str
    creator: str
    category: str


class TournamentLeaderboardEntry(msgspec.Struct, frozen=True):
    nickname: str
    record: float
    screenshot: str
    value: str
    date_rank: int


class MapContestSubmission(msgspec.Struct, frozen=True):
    map_code: str
    user_id: int


class Mission(msgspec.Struct, frozen=True):
    id: int
    type: str
    target: float | None
    difficulty: str
    category: str
    extra_target: float | None


class MissionWithMap(msgspec.Struct, frozen=True):
    id: int
    type: str
    target: float | None
    difficulty: str
    category: str
    extra_target: float | None
    code: str | None
    level: str | None
    creator: str | None


class GeneralMission(msgspec.Struct, frozen=True):
    type: str
    target: float | None
    extra_target: float | None


class Season(msgspec.Struct, frozen=True):
    number: int
    name: str
    active: bool


class SeasonInfo(msgspec.Struct, frozen=True):
    name: str
    number: int


class HallOfFameEntry(msgspec.Struct, frozen=True):
    user_id: int
    nickname: str
    record: float
    value: str
    category: str
    screenshot: str
    latest: int
    rank_num: int


class LeaderboardXPRow(msgspec.Struct, frozen=True):
    nickname: str
    user_id: int
    record: float
    category: str
    top_record: float | None
    value: str


class DifficultyMissionRow(msgspec.Struct, frozen=True):
    user_id: int
    category: str
    nickname: str
    difficulty: str
    top_record: float | None


class TopPlacementRow(msgspec.Struct, frozen=True):
    user_id: int
    amount: int


class SpreadsheetRecord(msgspec.Struct, frozen=True):
    user_id: int
    nickname: str
    category: str
    record: float
    rank: str
    date_rank: int


class TournamentService(Service):
    """Tournament lifecycle, maps, records, missions, seasons, and XP data."""

    async def fetch_latest_tournament_info(self) -> TournamentInfo | None:
        query = """--sql
            SELECT
              t.id,
              t.title,
              t.start,
              t."end",
              t.active,
              t.bracket,
              t.needs_start_task,
              t.needs_end_task,
              t.needs_start_now,
              t.needs_end_now
            FROM (
              SELECT
                id,
                title,
                start,
                "end",
                active,
                bracket,
                start > NOW() AS needs_start_task,
                "end" > NOW() AS needs_end_task,
                start < NOW() AND "end" > NOW() AND NOT active AS needs_start_now,
                "end" < NOW() AND active AS needs_end_now
              FROM tournament
            ) AS t
            WHERE t.id = (SELECT MAX(id) FROM tournament);
        """
        return await self._db.select_one_or_none(query, schema_type=TournamentInfo)

    async def fetch_tournament_maps(self, tournament_id: int) -> list[TournamentMap]:
        query = """--sql
            SELECT
              id,
              code,
              level,
              creator,
              category
            FROM tournament_maps
            WHERE id = :tournament_id;
        """
        return await self._db.select(
            query, tournament_id=tournament_id, schema_type=TournamentMap
        )

    async def has_upcoming_or_active_tournament(self) -> bool:
        query = """--sql
            SELECT 1
            FROM tournament
            WHERE start > NOW() OR "end" > NOW()
            LIMIT 1;
        """
        row = await self._db.select_value_or_none(query)
        return row is not None

    async def create_tournament(
        self, start: datetime, end: datetime, active: bool, bracket: bool
    ) -> int:
        query = """--sql
            INSERT INTO tournament (start, "end", active, bracket)
            VALUES (:start, :end, :active, :bracket)
            RETURNING id;
        """
        return await self._db.select_value(
            query, start=start, end=end, active=active, bracket=bracket
        )

    async def add_tournament_maps(
        self, rows: list[tuple[int, str, str, str, str]]
    ) -> None:
        query = """--sql
            INSERT INTO tournament_maps (id, code, level, creator, category)
            VALUES ($1, $2, $3, $4, $5);
        """
        await self._db.execute_many(query, rows)

    async def set_tournament_active(self, tournament_id: int, active: bool) -> None:
        query = """--sql
            UPDATE tournament
            SET active = :active
            WHERE id = :tournament_id;
        """
        await self._db.execute(query, tournament_id=tournament_id, active=active)

    async def fetch_latest_tournament_id(self) -> int | None:
        query = """--sql
            SELECT MAX(id)
            FROM tournament;
        """
        return await self._db.select_value_or_none(query)

    async def fetch_active_tournament_id(self) -> int | None:
        query = """--sql
            SELECT id
            FROM tournament
            WHERE active = TRUE;
        """
        return await self._db.select_value_or_none(query)

    async def fetch_tournament_leaderboard(
        self, category: str, rank: str | None
    ) -> list[TournamentLeaderboardEntry]:
        query = """--sql
            WITH all_ranks AS (
              SELECT
                u.user_id,
                u.nickname,
                cats.value AS category,
                COALESCE(ur.value, 'Unranked') AS value
              FROM users AS u
              INNER JOIN tournament_ranks AS cats ON TRUE
              LEFT JOIN user_ranks AS ur
                ON u.user_id = ur.user_id AND cats.value = ur.category
            ),
            
            all_records AS (
              SELECT
                ar.nickname,
                tr.record,
                tr.screenshot,
                ar.value,
                RANK() OVER (
                  PARTITION BY ar.nickname, ar.value, tr.category, ar.category
                  ORDER BY tr.inserted_at DESC
                ) AS date_rank
              FROM tournament_records AS tr
              LEFT JOIN all_ranks AS ar ON tr.user_id = ar.user_id
              WHERE
                tr.tournament_id = (
                  SELECT id
                  FROM tournament
                  WHERE id = (SELECT MAX(t2.id) FROM tournament AS t2)
                )
                AND tr.category = :category
                AND ar.category = :category
                AND (CAST(:rank AS TEXT) IS NULL OR ar.value = :rank)
              ORDER BY tr.record
            )
            
            SELECT
              nickname,
              CAST(record AS FLOAT) AS record,
              screenshot,
              value,
              date_rank
            FROM all_records
            WHERE date_rank = 1;
        """
        return await self._db.select(
            query,
            category=category,
            rank=rank,
            schema_type=TournamentLeaderboardEntry,
        )

    async def has_map_contest_submission(
        self, user_id: int, tournament_id: int
    ) -> bool:
        query = """--sql
            SELECT
              EXISTS(
                SELECT 1
                FROM map_contest
                WHERE user_id = :user_id AND tournament_id = :tournament_id
              );
        """
        return await self._db.select_value(
            query, user_id=user_id, tournament_id=tournament_id
        )

    async def upsert_map_contest_submission(
        self, user_id: int, map_code: str, tournament_id: int
    ) -> None:
        query = """--sql
            INSERT INTO map_contest (user_id, map_code, tournament_id)
            VALUES (:user_id, :map_code, :tournament_id)
            ON CONFLICT (user_id, tournament_id) DO UPDATE
              SET map_code = :map_code;
        """
        await self._db.execute(
            query, user_id=user_id, map_code=map_code, tournament_id=tournament_id
        )

    async def fetch_map_contest_submissions(
        self, tournament_id: int
    ) -> list[MapContestSubmission]:
        query = """--sql
            SELECT
              map_code,
              user_id
            FROM map_contest
            WHERE tournament_id = :tournament_id;
        """
        return await self._db.select(
            query, tournament_id=tournament_id, schema_type=MapContestSubmission
        )

    async def delete_map_contest_map(self, tournament_id: int, map_code: str) -> None:
        query = """--sql
            DELETE FROM map_contest
            WHERE tournament_id = :tournament_id AND map_code = :map_code;
        """
        await self._db.execute(query, tournament_id=tournament_id, map_code=map_code)

    async def fetch_mission(
        self, category: str, difficulty: str, tournament_id: int
    ) -> Mission | None:
        query = """--sql
            SELECT
              id,
              type,
              CAST(target AS FLOAT) AS target,
              difficulty,
              category,
              CAST(extra_target AS FLOAT) AS extra_target
            FROM tournament_missions
            WHERE
              category = :category
              AND difficulty = :difficulty
              AND id = :tournament_id;
        """
        return await self._db.select_one_or_none(
            query,
            category=category,
            difficulty=difficulty,
            tournament_id=tournament_id,
            schema_type=Mission,
        )

    async def upsert_mission(
        self,
        tournament_id: int,
        mission_type: str,
        target: float | None,
        difficulty: str,
        category: str,
        extra_target: float | None,
    ) -> None:
        query = """--sql
            INSERT INTO tournament_missions (
              id, type, target, difficulty, category, extra_target
            )
            VALUES (
              :tournament_id,
              :mission_type,
              :target,
              :difficulty,
              :category,
              :extra_target
            )
            ON CONFLICT (id, category, difficulty)
            DO UPDATE SET target = excluded.target, type = excluded.type;
        """
        await self._db.execute(
            query,
            tournament_id=tournament_id,
            mission_type=mission_type,
            target=target,
            difficulty=difficulty,
            category=category,
            extra_target=extra_target,
        )

    async def delete_mission(
        self, category: str, difficulty: str, tournament_id: int
    ) -> None:
        query = """--sql
            DELETE FROM tournament_missions
            WHERE
              category = :category
              AND difficulty = :difficulty
              AND id = :tournament_id;
        """
        await self._db.execute(
            query,
            category=category,
            difficulty=difficulty,
            tournament_id=tournament_id,
        )

    async def fetch_missions_with_maps(
        self, tournament_id: int
    ) -> list[MissionWithMap]:
        query = """--sql
            SELECT
              tmi.id,
              tmi.type,
              CAST(tmi.target AS FLOAT) AS target,
              tmi.difficulty,
              tmi.category,
              CAST(tmi.extra_target AS FLOAT) AS extra_target,
              tm.code,
              tm.level,
              tm.creator
            FROM tournament_missions AS tmi
            LEFT JOIN tournament_maps AS tm
              ON tmi.category = tm.category AND tmi.id = tm.id
            WHERE tmi.id = :tournament_id
            ORDER BY
              tmi.category != 'General',
              tmi.category != 'Time Attack',
              tmi.category != 'Mildcore',
              tmi.category != 'Hardcore',
              tmi.category != 'Bonus',
              tmi.difficulty != 'Easy',
              tmi.difficulty != 'Medium',
              tmi.difficulty != 'Hard',
              tmi.difficulty != 'Expert';
        """
        return await self._db.select(
            query, tournament_id=tournament_id, schema_type=MissionWithMap
        )

    async def fetch_general_mission(self, tournament_id: int) -> GeneralMission | None:
        query = """--sql
            SELECT
              type,
              CAST(target AS FLOAT) AS target,
              CAST(extra_target AS FLOAT) AS extra_target
            FROM tournament_missions
            WHERE id = :tournament_id AND category = 'General'
            LIMIT 1;
        """
        return await self._db.select_one_or_none(
            query, tournament_id=tournament_id, schema_type=GeneralMission
        )

    async def fetch_active_season_number(self) -> int | None:
        query = """--sql
            SELECT number
            FROM tournament_seasons
            WHERE active = TRUE
            ORDER BY number DESC
            LIMIT 1;
        """
        return await self._db.select_value_or_none(query)

    async def fetch_seasons(self) -> list[Season]:
        query = """--sql
            SELECT
              number,
              name,
              active
            FROM tournament_seasons
            ORDER BY number;
        """
        return await self._db.select(query, schema_type=Season)

    async def fetch_season_names(self) -> list[SeasonInfo]:
        query = """--sql
            SELECT
              name,
              number
            FROM tournament_seasons;
        """
        return await self._db.select(query, schema_type=SeasonInfo)

    async def search_season_names(self, value: str) -> list[SeasonInfo]:
        query = """--sql
            SELECT
              name,
              number
            FROM tournament_seasons
            ORDER BY SIMILARITY(name, CAST(:value AS TEXT)) DESC
            LIMIT 12;
        """
        return await self._db.select(query, value=value, schema_type=SeasonInfo)

    async def deactivate_active_season(self) -> None:
        query = """--sql
            UPDATE tournament_seasons
            SET active = FALSE
            WHERE active = TRUE;
        """
        await self._db.execute(query)

    async def activate_season(self, number: int) -> None:
        query = """--sql
            UPDATE tournament_seasons
            SET active = TRUE
            WHERE number = :number;
        """
        await self._db.execute(query, number=number)

    async def create_season(self, name: str) -> int:
        query = """--sql
            INSERT INTO tournament_seasons (name)
            VALUES (:name)
            RETURNING number;
        """
        return await self._db.select_value(query, name=name)

    async def insert_tournament_record(
        self, user_id: int, category: str, record: float, screenshot: str
    ) -> None:
        query = """--sql
            INSERT INTO tournament_records (
              user_id, category, record, tournament_id, screenshot
            )
            VALUES (
              :user_id,
              :category,
              :record,
              (
                SELECT id FROM tournament
                WHERE active = TRUE LIMIT 1
              ),
              :screenshot
            );
        """
        await self._db.execute(
            query,
            user_id=user_id,
            category=category,
            record=record,
            screenshot=screenshot,
        )

    async def fetch_latest_tournament_record(
        self, user_id: int, category: str, tournament_id: int
    ) -> float | None:
        query = """--sql
            SELECT CAST(record AS FLOAT) AS record
            FROM tournament_records
            WHERE
              user_id = :user_id
              AND category = :category
              AND tournament_id = :tournament_id
            ORDER BY inserted_at DESC
            LIMIT 1;
        """
        return await self._db.select_value_or_none(
            query, user_id=user_id, category=category, tournament_id=tournament_id
        )

    async def fetch_user_rank_value(self, user_id: int, category: str) -> str | None:
        query = """--sql
            SELECT value
            FROM (
              SELECT
                COALESCE(ur.value, 'Unranked') AS value,
                COALESCE(ur.category, :category) AS category
              FROM users AS u
              LEFT JOIN user_ranks AS ur ON u.user_id = ur.user_id
              WHERE u.user_id = :user_id
            ) AS pre
            WHERE category = :category;
        """
        return await self._db.select_value_or_none(
            query, user_id=user_id, category=category
        )

    async def delete_latest_tournament_record(
        self, user_id: int, category: str, tournament_id: int
    ) -> None:
        query = """--sql
            DELETE FROM tournament_records
            WHERE
              user_id = :user_id
              AND tournament_id = :tournament_id
              AND category = :category
              AND inserted_at = (
                SELECT MAX(inserted_at) AS inserted_at
                FROM tournament_records
                WHERE
                  user_id = :user_id
                  AND tournament_id = :tournament_id
                  AND category = :category
              );
        """
        await self._db.execute(
            query, user_id=user_id, category=category, tournament_id=tournament_id
        )

    async def fetch_hall_of_fame(
        self, tournament_id: int, category: str
    ) -> list[HallOfFameEntry]:
        query = """--sql
            WITH t_records AS (
              SELECT
                tr.user_id,
                tr.record,
                COALESCE(ur.value, 'Unranked') AS value,
                tr.category,
                tr.screenshot,
                tr.inserted_at
              FROM tournament_records AS tr
              LEFT JOIN user_ranks AS ur
                ON tr.user_id = ur.user_id AND tr.category = ur.category
              WHERE tr.tournament_id = :tournament_id
            ),
            
            ranks AS (
              SELECT
                user_id,
                record,
                value,
                category,
                screenshot,
                RANK() OVER (
                  PARTITION BY user_id, category
                  ORDER BY inserted_at DESC
                ) AS latest
              FROM t_records
            )
            
            SELECT
              r.user_id,
              u.nickname,
              CAST(r.record AS FLOAT) AS record,
              r.value,
              r.category,
              r.screenshot,
              r.latest,
              RANK() OVER (PARTITION BY r.category ORDER BY r.record) AS rank_num
            FROM ranks AS r
            LEFT JOIN users AS u ON r.user_id = u.user_id
            WHERE r.category = :category AND r.latest = 1
            ORDER BY
              r.category != 'Time Attack',
              r.category != 'Mildcore',
              r.category != 'Hardcore',
              r.category != 'Bonus',
              rank_num;
        """
        return await self._db.select(
            query,
            tournament_id=tournament_id,
            category=category,
            schema_type=HallOfFameEntry,
        )

    async def fetch_leaderboard_xp_rows(
        self, tournament_id: int
    ) -> list[LeaderboardXPRow]:
        query = """--sql
            WITH all_ranks AS (
              SELECT
                u.user_id,
                u.nickname,
                cats.value AS category,
                COALESCE(ur.value, 'Unranked') AS value
              FROM users AS u
              INNER JOIN tournament_ranks AS cats ON TRUE
              LEFT JOIN user_ranks AS ur
                ON u.user_id = ur.user_id AND cats.value = ur.category
            ),
            
            t_records AS (
              SELECT
                tr.user_id,
                tr.record,
                ur.value,
                tr.category,
                RANK() OVER (
                  PARTITION BY ur.user_id, ur.value, tr.category, ur.category
                  ORDER BY tr.inserted_at DESC
                ) AS date_rank
              FROM tournament_records AS tr
              LEFT JOIN all_ranks AS ur
                ON tr.user_id = ur.user_id AND tr.category = ur.category
              WHERE tr.tournament_id = :tournament_id
            ),
            
            top AS (
              SELECT
                category,
                MIN(record) AS top_record
              FROM t_records
              GROUP BY category, value
            ),
            
            top_recs AS (
              SELECT
                r.user_id,
                r.record,
                top.category,
                r.value AS rank
              FROM top
              LEFT JOIN t_records AS r
                ON top.category = r.category AND top.top_record = r.record
            )
            
            SELECT
              u.nickname,
              r.user_id,
              CAST(r.record AS FLOAT) AS record,
              r.category,
              CAST(tr.record AS FLOAT) AS top_record,
              r.value
            FROM t_records AS r
            LEFT JOIN top_recs AS tr
              ON r.category = tr.category AND r.value = tr.rank
            LEFT JOIN users AS u ON r.user_id = u.user_id
            WHERE r.date_rank = 1
            ORDER BY r.category, r.value, r.record;
        """
        return await self._db.select(
            query, tournament_id=tournament_id, schema_type=LeaderboardXPRow
        )

    async def fetch_difficulty_mission_rows(
        self, tournament_id: int
    ) -> list[DifficultyMissionRow]:
        query = """--sql
            WITH t_records AS (
              SELECT
                tr.user_id,
                tr.record,
                COALESCE(ur.value, 'Unranked') AS value,
                tr.category
              FROM tournament_records AS tr
              LEFT JOIN user_ranks AS ur
                ON tr.user_id = ur.user_id AND tr.category = ur.category
              WHERE tr.tournament_id = :tournament_id
            ),
            
            top AS (
              SELECT
                category,
                MIN(record) AS top_record
              FROM t_records
              GROUP BY category, value
            ),
            
            top_recs AS (
              SELECT
                r.user_id,
                r.record,
                top.category,
                r.value AS rank
              FROM top
              LEFT JOIN t_records AS r
                ON top.category = r.category AND top.top_record = r.record
            ),
            
            sub_time_missions AS (
              SELECT
                tournament_missions.target,
                t_records.user_id,
                t_records.category,
                users.nickname,
                tournament_missions.difficulty,
                t_records.value,
                t_records.record
              FROM t_records
              LEFT JOIN tournament_missions
                ON t_records.category = tournament_missions.category
              LEFT JOIN users ON t_records.user_id = users.user_id
              WHERE
                tournament_missions.id = :tournament_id
                AND CASE
                  WHEN tournament_missions.type = 'Sub Time'
                    THEN t_records.record < tournament_missions.target
                  WHEN tournament_missions.type = 'Completion'
                    THEN t_records.record > -10000000
                  ELSE TRUE
                END
              ORDER BY
                t_records.category != 'Time Attack',
                t_records.category != 'Mildcore',
                t_records.category != 'Hardcore',
                t_records.category != 'Bonus',
                tournament_missions.difficulty != 'Expert',
                tournament_missions.difficulty != 'Hard',
                tournament_missions.difficulty != 'Medium',
                tournament_missions.difficulty != 'Easy'
            ),
            
            distinct_values AS (
              SELECT DISTINCT ON (user_id, category, nickname)
                user_id,
                category,
                nickname,
                difficulty,
                value AS rank,
                record
              FROM sub_time_missions
              ORDER BY
                user_id,
                category,
                nickname,
                difficulty != 'Expert',
                difficulty != 'Hard',
                difficulty != 'Medium',
                difficulty != 'Easy'
            )
            
            SELECT
              t.user_id,
              t.category,
              t.nickname,
              t.difficulty,
              CAST(tr.record AS FLOAT) AS top_record
            FROM distinct_values AS t
            LEFT JOIN top_recs AS tr
              ON t.category = tr.category AND t.rank = tr.rank;
        """
        return await self._db.select(
            query, tournament_id=tournament_id, schema_type=DifficultyMissionRow
        )

    async def fetch_top_placement_users(
        self, tournament_id: int, target: int
    ) -> list[TopPlacementRow]:
        query = """--sql
            WITH t_records AS (
              SELECT
                tr.user_id,
                tr.record,
                COALESCE(ur.value, 'Unranked') AS value,
                tr.category,
                RANK() OVER (
                  PARTITION BY ur.user_id, ur.value, tr.category, ur.category
                  ORDER BY tr.inserted_at DESC
                ) AS date_rank
              FROM tournament_records AS tr
              LEFT JOIN user_ranks AS ur
                ON tr.user_id = ur.user_id AND tr.category = ur.category
              WHERE tr.tournament_id = :tournament_id
            ),
            
            ranks AS (
              SELECT
                user_id,
                record,
                value,
                category,
                RANK() OVER (PARTITION BY value, category ORDER BY record)
                  AS rank_num
              FROM t_records
              WHERE date_rank = 1
            ),
            
            top_three AS (
              SELECT
                user_id,
                COUNT(user_id) AS amount
              FROM ranks
              WHERE rank_num <= 3
              GROUP BY user_id
            )
            
            SELECT
              user_id,
              amount
            FROM top_three
            WHERE amount >= :target;
        """
        return await self._db.select(
            query,
            tournament_id=tournament_id,
            target=target,
            schema_type=TopPlacementRow,
        )

    async def fetch_spreadsheet_records(
        self, tournament_id: int
    ) -> list[SpreadsheetRecord]:
        query = """--sql
            WITH recs AS (
              SELECT
                tr.user_id,
                u.nickname,
                tr.category,
                tr.record,
                COALESCE(ur.value, 'Unranked') AS rank,
                RANK() OVER (
                  PARTITION BY u.nickname, ur.value, tr.category, ur.category
                  ORDER BY tr.inserted_at DESC
                ) AS date_rank
              FROM tournament_records AS tr
              LEFT JOIN users AS u ON tr.user_id = u.user_id
              LEFT JOIN user_ranks AS ur
                ON u.user_id = ur.user_id AND tr.category = ur.category
              WHERE tr.tournament_id = :tournament_id
              ORDER BY
                ur.value != 'Grandmaster',
                ur.value != 'Diamond',
                ur.value != 'Gold',
                ur.value != 'Unranked',
                tr.category != 'Time Attack',
                tr.category != 'Mildcore',
                tr.category != 'Hardcore',
                tr.category != 'Bonus',
                tr.record
            )
            
            SELECT
              user_id,
              nickname,
              category,
              CAST(record AS FLOAT) AS record,
              rank,
              date_rank
            FROM recs
            WHERE date_rank = 1;
        """
        return await self._db.select(
            query, tournament_id=tournament_id, schema_type=SpreadsheetRecord
        )
