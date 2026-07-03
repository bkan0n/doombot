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

    async def set_alertable(self, user_id: int, alertable: bool) -> None:
        query = """--sql
            UPDATE users
            SET alertable = :alertable
            WHERE user_id = :user_id;
        """
        await self._db.execute(query, user_id=user_id, alertable=alertable)

    async def is_alertable(self, user_id: int) -> bool | None:
        query = """--sql
            SELECT alertable
            FROM users
            WHERE user_id = :user_id;
        """
        return await self._db.select_value_or_none(query, user_id=user_id)

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

    async def add_aliases(self, rows: list[tuple[int, str, bool]]) -> None:
        query = """--sql
            INSERT INTO alias (user_id, alias, "primary")
            VALUES ($1, $2, $3);
        """
        await self._db.execute_many(query, rows)

    async def add_primary_alias(self, user_id: int, alias: str) -> None:
        query = """--sql
            INSERT INTO alias (user_id, alias, "primary")
            VALUES (:user_id, :alias, TRUE);
        """
        await self._db.execute(query, user_id=user_id, alias=alias)
