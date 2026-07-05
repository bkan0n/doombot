import msgspec

from ._base import Service


class Quote(msgspec.Struct, frozen=True):
    id: int
    username: str
    content: str


class AutoJoinThread(msgspec.Struct, frozen=True):
    channel_id: int
    thread_id: int


class ColorRole(msgspec.Struct, frozen=True):
    label: str
    role_id: int
    emoji: str | None
    sort_order: int


class MiscService(Service):
    """Quotes, insults, keep-alive threads, auto-join threads, color roles."""

    async def fetch_random_quote(self) -> Quote | None:
        query = """--sql
            SELECT
              id,
              username,
              content
            FROM quotes
            ORDER BY RANDOM()
            LIMIT 1;
        """
        return await self._db.select_one_or_none(query, schema_type=Quote)

    async def fetch_quote(self, quote_id: int) -> Quote | None:
        query = """--sql
            SELECT
              id,
              username,
              content
            FROM quotes
            WHERE id = :quote_id;
        """
        return await self._db.select_one_or_none(
            query, quote_id=quote_id, schema_type=Quote
        )

    async def fetch_quotes(self) -> list[Quote]:
        query = """--sql
            SELECT
              id,
              username,
              content
            FROM quotes
            ORDER BY id;
        """
        return await self._db.select(query, schema_type=Quote)

    async def add_quote(self, username: str, content: str) -> int:
        query = """--sql
            INSERT INTO quotes (username, content)
            VALUES (:username, :content)
            RETURNING id;
        """
        return await self._db.select_value(query, username=username, content=content)

    async def add_insult(self, value: str) -> None:
        query = """--sql
            INSERT INTO insults (value)
            VALUES (:value);
        """
        await self._db.execute(query, value=value)

    async def fetch_random_insult(self) -> str | None:
        query = """--sql
            SELECT value
            FROM insults
            ORDER BY RANDOM()
            LIMIT 1;
        """
        return await self._db.select_value_or_none(query)

    async def add_keep_alive(self, thread_id: int) -> None:
        query = """--sql
            INSERT INTO keep_alives (thread_id)
            VALUES (:thread_id);
        """
        await self._db.execute(query, thread_id=thread_id)

    async def remove_keep_alive(self, thread_id: int) -> None:
        query = """--sql
            DELETE FROM keep_alives
            WHERE thread_id = :thread_id;
        """
        await self._db.execute(query, thread_id=thread_id)

    async def fetch_keep_alives(self) -> list[int]:
        query = """--sql
            SELECT thread_id
            FROM keep_alives;
        """
        rows = await self._db.select(query)
        return [row["thread_id"] for row in rows]

    async def fetch_auto_join_threads(self) -> list[AutoJoinThread]:
        query = """--sql
            SELECT
              channel_id,
              thread_id
            FROM auto_join_thread;
        """
        return await self._db.select(query, schema_type=AutoJoinThread)

    async def fetch_color_roles(self) -> list[ColorRole]:
        query = """--sql
            SELECT
              label,
              role_id,
              emoji,
              sort_order
            FROM colors
            ORDER BY sort_order;
        """
        return await self._db.select(query, schema_type=ColorRole)
