import msgspec

from ._base import Service


class UserProfile(msgspec.Struct, frozen=True):
    user_id: int
    nickname: str
    alertable: bool
    flags: int | None = None


class UserAlias(msgspec.Struct, frozen=True):
    user_id: int
    alias: str
    primary: bool


class UserService(Service):
    """Users, notification flags, and Overwatch aliases."""

    async def user_exists(self, user_id: int) -> bool:
        query = """--sql
            SELECT
              EXISTS(
                SELECT 1
                FROM users
                WHERE user_id = :user_id
              ) AS exists;
        """
        return await self._db.select_value(query, user_id=user_id)

    async def autocomplete_users(
        self, search: str, *, limit: int = 25
    ) -> list[UserProfile]:
        query = """--sql
            SELECT
              user_id,
              nickname,
              alertable,
              flags
            FROM users
            ORDER BY SIMILARITY(nickname, :search) DESC, nickname
            LIMIT :limit;
        """
        return await self._db.select(
            query,
            search=search,
            limit=limit,
            schema_type=UserProfile,
        )

    async def fetch_flags(self, user_id: int) -> int | None:
        query = """--sql
            SELECT flags
            FROM users
            WHERE user_id = :user_id;
        """
        return await self._db.select_value_or_none(query, user_id=user_id)

    async def set_flags(self, user_id: int, flags: int) -> None:
        query = """--sql
            UPDATE users
            SET flags = :flags
            WHERE user_id = :user_id;
        """
        await self._db.execute(query, user_id=user_id, flags=flags)

    async def create_if_missing(self, user_id: int, nickname: str) -> None:
        query = """--sql
            INSERT INTO users (user_id, nickname, alertable)
            VALUES (:user_id, :nickname, TRUE)
            ON CONFLICT (user_id) DO NOTHING;
        """
        await self._db.execute(query, user_id=user_id, nickname=nickname[:25])

    async def set_nickname(self, user_id: int, nickname: str) -> None:
        query = """--sql
            UPDATE users
            SET nickname = :nickname
            WHERE user_id = :user_id;
        """
        await self._db.execute(query, user_id=user_id, nickname=nickname)

    async def fetch_all(self) -> list[UserProfile]:
        query = """--sql
            SELECT
              user_id,
              nickname,
              alertable,
              flags
            FROM users;
        """
        return await self._db.select(query, schema_type=UserProfile)

    async def fetch_aliases(self, user_id: int) -> list[UserAlias]:
        query = """--sql
            SELECT
              user_id,
              alias,
              "primary"
            FROM alias
            WHERE user_id = :user_id;
        """
        return await self._db.select(query, user_id=user_id, schema_type=UserAlias)

    async def add_alias(self, user_id: int, alias: str, *, primary: bool) -> None:
        query = """--sql
            INSERT INTO alias (user_id, alias, "primary")
            VALUES (:user_id, :alias, :primary);
        """
        await self._db.execute(query, user_id=user_id, alias=alias, primary=primary)

    async def remove_alias(self, user_id: int, alias: str) -> None:
        query = """--sql
            DELETE FROM alias
            WHERE user_id = :user_id AND alias = :alias;
        """
        await self._db.execute(query, user_id=user_id, alias=alias)

    async def set_primary_alias(self, user_id: int, alias: str) -> None:
        query = """--sql
            UPDATE alias
            SET "primary" = (alias = :alias)
            WHERE user_id = :user_id;
        """
        await self._db.execute(query, user_id=user_id, alias=alias)

    async def fetch_nickname(self, user_id: int) -> str | None:
        query = """--sql
            SELECT nickname
            FROM users
            WHERE user_id = :user_id;
        """
        return await self._db.select_value_or_none(query, user_id=user_id)

    async def backfill_flags_from_alertable(self) -> int:
        # 7 = Notification.VERIFIED | DENIED | SPECTACULAR (utilities/flags.py).
        query = """--sql
            UPDATE users
            SET flags = CASE WHEN alertable THEN 7 ELSE 0 END
            WHERE flags IS NULL;
        """
        result = await self._db.execute(query)
        return result.rows_affected
