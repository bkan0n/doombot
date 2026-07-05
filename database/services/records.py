import msgspec

from ._base import Service


class PreviousRecord(msgspec.Struct, frozen=True):
    record: float
    hidden_id: int | None
    message_id: int
    channel_id: int
    video: str | None


class LeaderboardRecord(msgspec.Struct, frozen=True):
    nickname: str
    level_name: str
    record: float
    screenshot: str
    video: str | None
    tournament: bool
    verified: bool
    map_code: str
    map_name: str | None
    rank_num: int
    creator_name: str | None


class PersonalRecord(msgspec.Struct, frozen=True):
    nickname: str
    level_name: str
    record: float
    screenshot: str
    video: str | None
    verified: bool
    map_code: str
    map_name: str | None
    rank_num: int
    creators: str | None


class VerificationCount(msgspec.Struct, frozen=True):
    user_id: int
    amount: int
    nickname: str


class VerificationCountEntry(msgspec.Struct, frozen=True):
    user_id: int
    amount: int
    nickname: str
    rank: int


class LatestUserRecord(msgspec.Struct, frozen=True):
    user_id: int
    map_code: str
    level_name: str
    record: float
    nickname: str


class PendingRecord(msgspec.Struct, frozen=True):
    user_id: int
    map_code: str
    level_name: str
    record: float
    video: str | None
    message_id: int
    channel_id: int


class RecordCardData(msgspec.Struct, frozen=True):
    user_id: int
    map_code: str
    level_name: str
    record: float
    video: str | None
    verified: bool
    nickname: str


class RecordService(Service):
    """Record submission, leaderboards, verification, and top-record votes."""

    async def fetch_previous_record(
        self, map_code: str, level_name: str, user_id: int
    ) -> PreviousRecord | None:
        query = """--sql
            SELECT
              CAST(r.record AS FLOAT) AS record,
              r.hidden_id,
              r.message_id,
              r.channel_id,
              r.video
            FROM records AS r
            LEFT OUTER JOIN maps AS m ON r.map_code = m.map_code
            WHERE
              r.map_code = :map_code
              AND r.level_name = :level_name
              AND r.user_id = :user_id
            ORDER BY r.inserted_at DESC
            LIMIT 1;
        """
        return await self._db.select_one_or_none(
            query,
            map_code=map_code,
            level_name=level_name,
            user_id=user_id,
            schema_type=PreviousRecord,
        )

    async def insert_record(
        self,
        map_code: str,
        user_id: int,
        level_name: str,
        record: float,
        screenshot: str,
        video: str | None,
        message_id: int,
        channel_id: int,
        hidden_id: int,
    ) -> None:
        query = """--sql
            INSERT INTO records (
              map_code,
              user_id,
              level_name,
              record,
              screenshot,
              video,
              message_id,
              channel_id,
              hidden_id
            )
            VALUES (
              :map_code,
              :user_id,
              :level_name,
              :record,
              :screenshot,
              :video,
              :message_id,
              :channel_id,
              :hidden_id
            );
        """
        await self._db.execute(
            query,
            map_code=map_code,
            user_id=user_id,
            level_name=level_name,
            record=record,
            screenshot=screenshot,
            video=video,
            message_id=message_id,
            channel_id=channel_id,
            hidden_id=hidden_id,
        )

    async def upsert_level_rating(
        self, map_code: str, level: str, rating: int, user_id: int
    ) -> None:
        query = """--sql
            INSERT INTO map_level_ratings (map_code, level, rating, user_id)
            VALUES (:map_code, :level, :rating, :user_id)
            ON CONFLICT (map_code, level, user_id)
            DO UPDATE SET rating = excluded.rating;
        """
        await self._db.execute(
            query, map_code=map_code, level=level, rating=rating, user_id=user_id
        )

    async def fetch_leaderboard(
        self, map_code: str, level_name: str | None, video_only: bool
    ) -> list[LeaderboardRecord]:
        query = """--sql
            WITH base_record_data AS (
              SELECT
                COALESCE(a.alias, u.nickname) AS alias,
                u.user_id,
                m.map_code,
                m.map_name,
                r.level_name,
                r.record,
                r.screenshot,
                r.video,
                r.verified,
                r.inserted_at,
                RANK() OVER (
                  PARTITION BY r.map_code, r.user_id, r.level_name
                  ORDER BY r.inserted_at DESC
                ) AS latest
              FROM records AS r
              LEFT JOIN alias AS a ON r.user_id = a.user_id AND a."primary" = TRUE
              LEFT JOIN users AS u ON r.user_id = u.user_id
              LEFT JOIN maps AS m ON r.map_code = m.map_code
              WHERE
                r.map_code = :map_code
                AND (CAST(:video_only AS BOOLEAN) IS FALSE OR r.video IS NOT NULL)
                AND (CAST(:level_name AS TEXT) IS NULL OR r.level_name = :level_name)
                AND r.verified = TRUE
            ),
            
            base_tournament_records AS (
              SELECT
                COALESCE(a.alias, u.nickname) AS alias,
                tr.user_id,
                tr.record,
                tr.screenshot,
                tr.inserted_at,
                tm.code AS map_code,
                tm.level AS level_name,
                RANK() OVER (
                  PARTITION BY tr.user_id, tm.code, tm.level
                  ORDER BY tr.inserted_at DESC
                ) AS latest
              FROM tournament_records AS tr
              LEFT JOIN tournament_maps AS tm
                ON tr.category = tm.category AND tr.tournament_id = tm.id
              LEFT JOIN alias AS a ON tr.user_id = a.user_id AND a."primary" = TRUE
              LEFT JOIN users AS u ON tr.user_id = u.user_id
              WHERE
                tm.code = :map_code
                AND (CAST(:level_name AS TEXT) IS NULL OR tm.level = :level_name)
            ),
            
            latest_base_records AS (
              SELECT
                brd.alias,
                brd.user_id,
                brd.map_code,
                brd.map_name,
                brd.level_name,
                brd.record,
                brd.screenshot,
                brd.video,
                brd.verified,
                brd.inserted_at,
                FALSE AS tournament
              FROM base_record_data AS brd
              WHERE brd.latest = 1
            ),
            
            latest_base_tournament_records AS (
              SELECT
                btr.alias,
                btr.user_id,
                btr.map_code,
                NULL AS map_name,
                btr.level_name,
                btr.record,
                btr.screenshot,
                NULL AS video,
                TRUE AS verified,
                btr.inserted_at,
                TRUE AS tournament
              FROM base_tournament_records AS btr
              WHERE btr.latest = 1
            ),
            
            all_records_union AS (
              SELECT
                lbtr.alias,
                lbtr.user_id,
                lbtr.map_code,
                lbtr.map_name,
                lbtr.level_name,
                lbtr.record,
                lbtr.screenshot,
                lbtr.video,
                lbtr.verified,
                lbtr.inserted_at,
                lbtr.tournament
              FROM latest_base_tournament_records AS lbtr
              UNION DISTINCT
              SELECT
                lbr.alias,
                lbr.user_id,
                lbr.map_code,
                lbr.map_name,
                lbr.level_name,
                lbr.record,
                lbr.screenshot,
                lbr.video,
                lbr.verified,
                lbr.inserted_at,
                lbr.tournament
              FROM latest_base_records AS lbr
            ),
            
            all_records_with_rank AS (
              SELECT
                alr.alias,
                alr.user_id,
                alr.map_code,
                alr.map_name,
                alr.level_name,
                alr.record,
                alr.screenshot,
                alr.video,
                alr.verified,
                alr.tournament,
                RANK() OVER (
                  PARTITION BY alr.map_code, alr.level_name
                  ORDER BY alr.record
                ) AS rank_num
              FROM all_records_union AS alr
            )
            
            SELECT
              arwr.alias AS nickname,
              arwr.level_name,
              CAST(arwr.record AS FLOAT) AS record,
              arwr.screenshot,
              arwr.video,
              arwr.tournament,
              arwr.verified,
              arwr.map_code,
              arwr.map_name,
              arwr.rank_num,
              STRING_AGG(COALESCE(a.alias, u.nickname), ', ') AS creator_name
            FROM all_records_with_rank AS arwr
            LEFT JOIN map_creators AS mc ON arwr.map_code = mc.map_code
            LEFT JOIN alias AS a ON mc.user_id = a.user_id AND a."primary" = TRUE
            LEFT JOIN users AS u ON mc.user_id = u.user_id
            WHERE
              (CAST(:video_only AS BOOLEAN) IS FALSE OR arwr.video IS NOT NULL)
              AND (
                CAST(:has_level_name AS BOOLEAN) IS NOT FALSE
                OR arwr.rank_num = 1
              )
            GROUP BY
              arwr.alias,
              arwr.level_name,
              arwr.record,
              arwr.screenshot,
              arwr.video,
              arwr.tournament,
              arwr.verified,
              arwr.map_code,
              arwr.map_name,
              arwr.rank_num
            ORDER BY arwr.map_code, arwr.level_name, arwr.record;
        """
        return await self._db.select(
            query,
            map_code=map_code,
            has_level_name=level_name is not None,
            level_name=level_name,
            video_only=video_only,
            schema_type=LeaderboardRecord,
        )

    async def fetch_personal_records(
        self, user_id: int, wr_only: bool
    ) -> list[PersonalRecord]:
        query = """--sql
            WITH base_personal_records AS (
              SELECT
                COALESCE(a.alias, u.nickname) AS nickname,
                r.user_id,
                r.level_name,
                r.record,
                r.screenshot,
                r.video,
                r.verified,
                r.map_code,
                RANK() OVER (
                  PARTITION BY r.map_code, r.level_name, r.user_id
                  ORDER BY r.inserted_at DESC
                ) AS latest,
                RANK() OVER (
                  PARTITION BY r.map_code, r.level_name
                  ORDER BY r.record
                ) AS rank_num
              FROM records AS r
              LEFT JOIN alias AS a ON r.user_id = a.user_id AND a."primary" = TRUE
              LEFT JOIN users AS u ON r.user_id = u.user_id
              WHERE r.verified = TRUE
            )
            
            SELECT
              bpr.nickname,
              bpr.level_name,
              CAST(bpr.record AS FLOAT) AS record,
              bpr.screenshot,
              bpr.video,
              bpr.verified,
              bpr.map_code,
              m.map_name,
              bpr.rank_num,
              STRING_AGG(COALESCE(a.alias, u.nickname), ', ') AS creators
            FROM base_personal_records AS bpr
            LEFT JOIN maps AS m ON bpr.map_code = m.map_code
            LEFT JOIN map_creators AS mc ON bpr.map_code = mc.map_code
            LEFT JOIN alias AS a ON mc.user_id = a.user_id AND a."primary" = TRUE
            LEFT JOIN users AS u ON mc.user_id = u.user_id
            WHERE
              bpr.latest = 1
              AND bpr.user_id = :user_id
              AND (:wr_only IS FALSE OR bpr.rank_num = 1)
            GROUP BY
              bpr.nickname,
              bpr.level_name,
              bpr.record,
              bpr.screenshot,
              bpr.video,
              bpr.verified,
              bpr.map_code,
              m.map_name,
              bpr.rank_num
            ORDER BY
              bpr.map_code,
              SUBSTR(bpr.level_name, 1, 5) != 'Level',
              bpr.level_name;
        """
        return await self._db.select(
            query, user_id=user_id, wr_only=wr_only, schema_type=PersonalRecord
        )

    async def fetch_verification_count(self, user_id: int) -> VerificationCount | None:
        query = """--sql
            SELECT
              v.user_id,
              v.amount,
              u.nickname
            FROM verification_counts AS v
            LEFT JOIN users AS u ON v.user_id = u.user_id
            WHERE v.user_id = :user_id;
        """
        return await self._db.select_one_or_none(
            query, user_id=user_id, schema_type=VerificationCount
        )

    async def fetch_verification_leaderboard(self) -> list[VerificationCountEntry]:
        query = """--sql
            SELECT
              v.user_id,
              v.amount,
              u.nickname,
              RANK() OVER (ORDER BY v.amount DESC) AS rank
            FROM verification_counts AS v
            LEFT JOIN users AS u ON v.user_id = u.user_id
            ORDER BY v.amount DESC;
        """
        return await self._db.select(query, schema_type=VerificationCountEntry)

    async def fetch_latest_record(
        self, user_id: int, map_code: str, level_name: str
    ) -> LatestUserRecord | None:
        query = """--sql
            WITH all_user_records AS (
              SELECT
                r.user_id,
                r.map_code,
                r.level_name,
                r.record,
                u.nickname,
                RANK() OVER (ORDER BY r.inserted_at DESC) AS latest
              FROM records AS r
              LEFT JOIN users AS u ON r.user_id = u.user_id
              WHERE
                r.user_id = :user_id
                AND r.map_code = :map_code
                AND r.level_name = :level_name
            )
            
            SELECT
              user_id,
              map_code,
              level_name,
              CAST(record AS FLOAT) AS record,
              nickname
            FROM all_user_records
            WHERE latest = 1;
        """
        return await self._db.select_one_or_none(
            query,
            user_id=user_id,
            map_code=map_code,
            level_name=level_name,
            schema_type=LatestUserRecord,
        )

    async def delete_latest_record(
        self, user_id: int, map_code: str, level_name: str
    ) -> None:
        query = """--sql
            DELETE FROM records
            WHERE
              user_id = :user_id
              AND map_code = :map_code
              AND level_name = :level_name
              AND inserted_at = (
                SELECT MAX(inserted_at)
                FROM records
                WHERE
                  user_id = :user_id
                  AND map_code = :map_code
                  AND level_name = :level_name
              );
        """
        await self._db.execute(
            query, user_id=user_id, map_code=map_code, level_name=level_name
        )

    async def fetch_pending_record(self, hidden_id: int) -> PendingRecord | None:
        query = """--sql
            SELECT
              user_id,
              map_code,
              level_name,
              CAST(record AS FLOAT) AS record,
              video,
              message_id,
              channel_id
            FROM records
            WHERE hidden_id = :hidden_id;
        """
        return await self._db.select_one_or_none(
            query, hidden_id=hidden_id, schema_type=PendingRecord
        )

    async def verify_record(self, hidden_id: int) -> None:
        query = """--sql
            UPDATE records
            SET
              verified = TRUE,
              hidden_id = NULL
            WHERE hidden_id = :hidden_id;
        """
        await self._db.execute(query, hidden_id=hidden_id)

    async def delete_records(
        self, user_id: int, map_code: str, level_name: str
    ) -> None:
        query = """--sql
            DELETE FROM records
            WHERE
              user_id = :user_id
              AND map_code = :map_code
              AND level_name = :level_name;
        """
        await self._db.execute(
            query, user_id=user_id, map_code=map_code, level_name=level_name
        )

    async def increment_verification_count(self, user_id: int) -> None:
        query = """--sql
            INSERT INTO verification_counts (user_id, amount)
            VALUES (:user_id, 1)
            ON CONFLICT (user_id) DO UPDATE
              SET amount = verification_counts.amount + 1;
        """
        await self._db.execute(query, user_id=user_id)

    async def fetch_pending_hidden_ids(self) -> list[int]:
        query = """--sql
            SELECT hidden_id
            FROM records
            WHERE hidden_id IS NOT NULL;
        """
        rows = await self._db.select(query)
        return [row["hidden_id"] for row in rows]

    async def fetch_record_card_data(self, message_id: int) -> RecordCardData | None:
        query = """--sql
            SELECT
              r.user_id,
              r.map_code,
              r.level_name,
              CAST(r.record AS FLOAT) AS record,
              r.video,
              r.verified,
              COALESCE(a.alias, u.nickname) AS nickname
            FROM records AS r
            LEFT JOIN alias AS a ON r.user_id = a.user_id AND a."primary" = TRUE
            LEFT JOIN users AS u ON r.user_id = u.user_id
            WHERE r.message_id = :message_id;
        """
        return await self._db.select_one_or_none(
            query, message_id=message_id, schema_type=RecordCardData
        )

    async def add_top_record_vote(
        self, user_id: int, original_message_id: int, channel_id: int
    ) -> bool:
        """Record a star vote. Returns False if the user already voted."""
        query = """--sql
            INSERT INTO top_records (user_id, original_message_id, channel_id)
            VALUES (:user_id, :original_message_id, :channel_id)
            ON CONFLICT (user_id, original_message_id, channel_id) DO NOTHING
            RETURNING user_id;
        """
        row = await self._db.select_value_or_none(
            query,
            user_id=user_id,
            original_message_id=original_message_id,
            channel_id=channel_id,
        )
        return row is not None

    async def fetch_top_record_vote_count(
        self, original_message_id: int, channel_id: int
    ) -> int:
        query = """--sql
            SELECT COUNT(*)
            FROM top_records
            WHERE
              original_message_id = :original_message_id
              AND channel_id = :channel_id;
        """
        return await self._db.select_value(
            query,
            original_message_id=original_message_id,
            channel_id=channel_id,
        )
