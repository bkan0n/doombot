import msgspec

from ._base import Service


class RankCard(msgspec.Struct, frozen=True):
    user_id: int
    nickname: str
    xp: int
    pos: int
    time_attack: str
    mildcore: str
    hardcore: str
    bonus: str
    wins: int
    losses: int


class XPLeaderboardEntry(msgspec.Struct, frozen=True):
    nickname: str
    xp: int
    rank: int


class XPService(Service):
    """User XP totals, seasonal XP leaderboards, and per-category ranks."""

    async def fetch_rank_card_data(self, user_id: int, season: int) -> RankCard | None:
        query = """--sql
            WITH all_users AS (
              SELECT
                u.user_id,
                u.nickname,
                COALESCE(ux.xp, 0) AS xp
              FROM users AS u
              LEFT JOIN user_xp AS ux ON u.user_id = ux.user_id
              WHERE ux.season = :season
            ),
            
            all_positions AS (
              SELECT
                user_id,
                nickname,
                xp,
                RANK() OVER (ORDER BY xp DESC) AS pos
              FROM all_users
            ),
            
            ranks AS (
              SELECT
                u.user_id,
                COALESCE(
                  (
                    SELECT value FROM user_ranks
                    WHERE category = 'Time Attack' AND user_id = :user_id
                  ),
                  'Unranked'
                ) AS time_attack,
                COALESCE(
                  (
                    SELECT value FROM user_ranks
                    WHERE category = 'Mildcore' AND user_id = :user_id
                  ),
                  'Unranked'
                ) AS mildcore,
                COALESCE(
                  (
                    SELECT value FROM user_ranks
                    WHERE category = 'Hardcore' AND user_id = :user_id
                  ),
                  'Unranked'
                ) AS hardcore,
                COALESCE(
                  (
                    SELECT value FROM user_ranks
                    WHERE category = 'Bonus' AND user_id = :user_id
                  ),
                  'Unranked'
                ) AS bonus
              FROM users AS u
              LEFT JOIN user_ranks AS ur ON u.user_id = ur.user_id
            )
            
            SELECT
              all_positions.user_id,
              all_positions.nickname,
              all_positions.xp,
              all_positions.pos,
              ranks.time_attack,
              ranks.mildcore,
              ranks.hardcore,
              ranks.bonus,
              COALESCE(user_duels.wins, 0) AS wins,
              COALESCE(user_duels.losses, 0) AS losses
            FROM ranks
            LEFT JOIN all_positions ON ranks.user_id = all_positions.user_id
            LEFT JOIN user_duels ON all_positions.user_id = user_duels.user_id
            WHERE all_positions.user_id = :user_id
            GROUP BY
              all_positions.user_id,
              all_positions.nickname,
              all_positions.xp,
              all_positions.pos,
              ranks.time_attack,
              ranks.mildcore,
              ranks.hardcore,
              ranks.bonus,
              user_duels.wins,
              user_duels.losses;
        """
        return await self._db.select_one_or_none(
            query, user_id=user_id, season=season, schema_type=RankCard
        )

    async def fetch_xp_leaderboard(self, season: int) -> list[XPLeaderboardEntry]:
        query = """--sql
            SELECT
              u.nickname,
              user_xp.xp,
              RANK() OVER (ORDER BY user_xp.xp DESC) AS rank
            FROM user_xp
            LEFT JOIN users AS u ON user_xp.user_id = u.user_id
            WHERE user_xp.season = :season
            ORDER BY user_xp.xp DESC;
        """
        return await self._db.select(
            query, season=season, schema_type=XPLeaderboardEntry
        )

    async def set_rank(self, user_id: int, category: str, value: str) -> None:
        query = """--sql
            INSERT INTO user_ranks (user_id, category, value)
            VALUES (:user_id, :category, :value)
            ON CONFLICT (user_id, category) DO UPDATE
              SET value = excluded.value;
        """
        await self._db.execute(query, user_id=user_id, category=category, value=value)

    async def add_xp(self, user_id: int, xp: int, season: int) -> int:
        query = """--sql
            INSERT INTO user_xp (user_id, xp, season)
            VALUES (:user_id, :xp, :season)
            ON CONFLICT (user_id, season) DO UPDATE
              SET xp = user_xp.xp + excluded.xp
            RETURNING user_xp.xp;
        """
        return await self._db.select_value(query, user_id=user_id, xp=xp, season=season)

    async def add_xp_bulk(self, rows: list[tuple[int, int, int]]) -> None:
        query = """--sql
            INSERT INTO user_xp (user_id, xp, season)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, season) DO UPDATE
              SET xp = user_xp.xp + excluded.xp;
        """
        await self._db.execute_many(query, rows)
