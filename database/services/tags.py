from datetime import datetime

import msgspec

from ._base import Service


class Tag(msgspec.Struct, frozen=True):
    name: str
    content: str


class TagListEntry(msgspec.Struct, frozen=True):
    name: str
    id: int


class TagDumpEntry(msgspec.Struct, frozen=True):
    id: int
    name: str
    owner_id: int
    uses: int
    can_delete: bool
    is_alias: bool


class TagInfo(msgspec.Struct, frozen=True):
    is_alias: bool
    lookup_name: str
    lookup_created_at: datetime
    lookup_owner_id: int
    id: int
    name: str
    owner_id: int
    uses: int
    created_at: datetime


class TagOwner(msgspec.Struct, frozen=True):
    id: int
    owner_id: int


class TagLookupOwner(msgspec.Struct, frozen=True):
    tag_id: int
    owner_id: int


class TagService(Service):
    """Guild tags and aliases (tags2/tag_lookup system)."""

    async def fetch_guild_tags(self, location_id: int) -> list[Tag]:
        query = """--sql
            SELECT
              name,
              content
            FROM tags2
            WHERE location_id = :location_id;
        """
        return await self._db.select(query, location_id=location_id, schema_type=Tag)

    async def fetch_random_tag(self, location_id: int) -> Tag | None:
        query = """--sql
            SELECT
              name,
              content
            FROM tags2
            WHERE location_id = :location_id
            LIMIT
              1
              OFFSET FLOOR(
                RANDOM()
                * (
                  SELECT COUNT(*)
                  FROM tags2 AS t
                  WHERE t.location_id = :location_id
                )
              );
        """
        return await self._db.select_one_or_none(
            query, location_id=location_id, schema_type=Tag
        )

    async def fetch_tag(self, location_id: int, name: str) -> Tag | None:
        query = """--sql
            SELECT
              tags2.name,
              tags2.content
            FROM tag_lookup
            INNER JOIN tags2 ON tag_lookup.tag_id = tags2.id
            WHERE
              tag_lookup.location_id = :location_id
              AND LOWER(tag_lookup.name) = :name;
        """
        return await self._db.select_one_or_none(
            query, location_id=location_id, name=name, schema_type=Tag
        )

    async def search_similar_tag_names(self, location_id: int, name: str) -> list[str]:
        query = """--sql
            SELECT tag_lookup.name
            FROM tag_lookup
            WHERE tag_lookup.location_id = :location_id AND tag_lookup.name % :name
            ORDER BY SIMILARITY(tag_lookup.name, :name) DESC
            LIMIT 3;
        """
        rows = await self._db.select(query, location_id=location_id, name=name)
        return [row["name"] for row in rows]

    async def create_tag(
        self, name: str, content: str, owner_id: int, location_id: int
    ) -> None:
        query = """--sql
            WITH tag_insert AS (
              INSERT INTO tags2 (name, content, owner_id, location_id)
              VALUES (:name, :content, :owner_id, :location_id)
              RETURNING id
            )
            
            INSERT INTO tag_lookup (name, owner_id, location_id, tag_id)
            VALUES (:name, :owner_id, :location_id, (SELECT id FROM tag_insert));
        """
        await self._db.execute(
            query,
            name=name,
            content=content,
            owner_id=owner_id,
            location_id=location_id,
        )

    async def autocomplete_tags(self, location_id: int, name: str) -> list[str]:
        query = """--sql
            SELECT name
            FROM tags2
            WHERE location_id = :location_id AND LOWER(name) % :name
            LIMIT 12;
        """
        rows = await self._db.select(query, location_id=location_id, name=name)
        return [row["name"] for row in rows]

    async def autocomplete_tags_with_aliases(
        self, location_id: int, name: str
    ) -> list[str]:
        query = """--sql
            SELECT name
            FROM tag_lookup
            WHERE location_id = :location_id AND LOWER(name) % :name
            LIMIT 12;
        """
        rows = await self._db.select(query, location_id=location_id, name=name)
        return [row["name"] for row in rows]

    async def autocomplete_owned_tags(
        self, location_id: int, owner_id: int, name: str
    ) -> list[str]:
        query = """--sql
            SELECT name
            FROM tags2
            WHERE
              location_id = :location_id
              AND owner_id = :owner_id
              AND name % :name
            ORDER BY SIMILARITY(name, :name) DESC
            LIMIT 12;
        """
        rows = await self._db.select(
            query, location_id=location_id, owner_id=owner_id, name=name
        )
        return [row["name"] for row in rows]

    async def autocomplete_owned_tags_with_aliases(
        self, location_id: int, owner_id: int, name: str
    ) -> list[str]:
        query = """--sql
            SELECT name
            FROM tag_lookup
            WHERE
              location_id = :location_id
              AND owner_id = :owner_id
              AND name % :name
            ORDER BY SIMILARITY(name, :name) DESC
            LIMIT 12;
        """
        rows = await self._db.select(
            query, location_id=location_id, owner_id=owner_id, name=name
        )
        return [row["name"] for row in rows]

    async def increment_tag_uses(self, name: str, location_id: int) -> None:
        query = """--sql
            UPDATE tags2
            SET uses = uses + 1
            WHERE name = :name AND location_id = :location_id;
        """
        await self._db.execute(query, name=name, location_id=location_id)

    async def create_tag_alias(
        self, new_name: str, old_name: str, location_id: int, owner_id: int
    ) -> int:
        query = """--sql
            INSERT INTO tag_lookup (name, owner_id, location_id, tag_id)
            SELECT
              :new_name,
              :owner_id,
              tag_lookup.location_id,
              tag_lookup.tag_id
            FROM tag_lookup
            WHERE
              tag_lookup.location_id = :location_id
              AND LOWER(tag_lookup.name) = :old_name;
        """
        result = await self._db.execute(
            query,
            new_name=new_name,
            old_name=old_name,
            location_id=location_id,
            owner_id=owner_id,
        )
        return result.rows_affected

    async def tag_exists(self, location_id: int, name: str) -> bool:
        query = """--sql
            SELECT 1
            FROM tags2
            WHERE location_id = :location_id AND LOWER(name) = :name;
        """
        row = await self._db.select_value_or_none(
            query, location_id=location_id, name=name
        )
        return row is not None

    async def fetch_owned_tag_content(
        self, name: str, location_id: int, owner_id: int
    ) -> str | None:
        query = """--sql
            SELECT content
            FROM tags2
            WHERE
              LOWER(name) = :name
              AND location_id = :location_id
              AND owner_id = :owner_id;
        """
        return await self._db.select_value_or_none(
            query, name=name, location_id=location_id, owner_id=owner_id
        )

    async def update_tag_content(
        self, content: str, name: str, location_id: int, owner_id: int
    ) -> int:
        query = """--sql
            UPDATE tags2
            SET content = :content
            WHERE
              LOWER(name) = :name
              AND location_id = :location_id
              AND owner_id = :owner_id;
        """
        result = await self._db.execute(
            query,
            content=content,
            name=name,
            location_id=location_id,
            owner_id=owner_id,
        )
        return result.rows_affected

    async def delete_tag_lookup(self, name: str, location_id: int) -> int | None:
        query = """--sql
            DELETE FROM tag_lookup
            WHERE LOWER(name) = :name AND location_id = :location_id
            RETURNING tag_id;
        """
        return await self._db.select_value_or_none(
            query, name=name, location_id=location_id
        )

    async def delete_tag_lookup_owned(
        self, name: str, location_id: int, owner_id: int
    ) -> int | None:
        query = """--sql
            DELETE FROM tag_lookup
            WHERE
              LOWER(name) = :name
              AND location_id = :location_id
              AND owner_id = :owner_id
            RETURNING tag_id;
        """
        return await self._db.select_value_or_none(
            query, name=name, location_id=location_id, owner_id=owner_id
        )

    async def delete_tag(self, tag_id: int, name: str, location_id: int) -> int:
        query = """--sql
            DELETE FROM tags2
            WHERE
              id = :tag_id
              AND LOWER(name) = :name
              AND location_id = :location_id;
        """
        result = await self._db.execute(
            query, tag_id=tag_id, name=name, location_id=location_id
        )
        return result.rows_affected

    async def delete_tag_owned(
        self, tag_id: int, name: str, location_id: int, owner_id: int
    ) -> int:
        query = """--sql
            DELETE FROM tags2
            WHERE
              id = :tag_id
              AND LOWER(name) = :name
              AND location_id = :location_id
              AND owner_id = :owner_id;
        """
        result = await self._db.execute(
            query,
            tag_id=tag_id,
            name=name,
            location_id=location_id,
            owner_id=owner_id,
        )
        return result.rows_affected

    async def delete_tag_lookup_by_id(
        self, lookup_id: int, location_id: int
    ) -> int | None:
        query = """--sql
            DELETE FROM tag_lookup
            WHERE id = :lookup_id AND location_id = :location_id
            RETURNING tag_id;
        """
        return await self._db.select_value_or_none(
            query, lookup_id=lookup_id, location_id=location_id
        )

    async def delete_tag_lookup_by_id_owned(
        self, lookup_id: int, location_id: int, owner_id: int
    ) -> int | None:
        query = """--sql
            DELETE FROM tag_lookup
            WHERE
              id = :lookup_id
              AND location_id = :location_id
              AND owner_id = :owner_id
            RETURNING tag_id;
        """
        return await self._db.select_value_or_none(
            query, lookup_id=lookup_id, location_id=location_id, owner_id=owner_id
        )

    async def delete_tag_by_id(self, tag_id: int, location_id: int) -> int:
        query = """--sql
            DELETE FROM tags2
            WHERE id = :tag_id AND location_id = :location_id;
        """
        result = await self._db.execute(query, tag_id=tag_id, location_id=location_id)
        return result.rows_affected

    async def delete_tag_by_id_owned(
        self, tag_id: int, location_id: int, owner_id: int
    ) -> int:
        query = """--sql
            DELETE FROM tags2
            WHERE
              id = :tag_id
              AND location_id = :location_id
              AND owner_id = :owner_id;
        """
        result = await self._db.execute(
            query, tag_id=tag_id, location_id=location_id, owner_id=owner_id
        )
        return result.rows_affected

    async def fetch_tag_rank(self, tag_id: int) -> int | None:
        query = """--sql
            SELECT
              (
                SELECT COUNT(*)
                FROM tags2 AS second
                WHERE
                  (second.uses, second.id) >= (first.uses, first.id)
                  AND second.location_id = first.location_id
              ) AS rank
            FROM tags2 AS first
            WHERE first.id = :tag_id;
        """
        return await self._db.select_value_or_none(query, tag_id=tag_id)

    async def fetch_tag_info(self, name: str, location_id: int) -> TagInfo | None:
        query = """--sql
            SELECT
              tag_lookup.name != tags2.name AS is_alias,
              tag_lookup.name AS lookup_name,
              tag_lookup.created_at AS lookup_created_at,
              tag_lookup.owner_id AS lookup_owner_id,
              tags2.id,
              tags2.name,
              tags2.owner_id,
              tags2.uses,
              tags2.created_at
            FROM tag_lookup
            INNER JOIN tags2 ON tag_lookup.tag_id = tags2.id
            WHERE
              LOWER(tag_lookup.name) = :name
              AND tag_lookup.location_id = :location_id;
        """
        return await self._db.select_one_or_none(
            query, name=name, location_id=location_id, schema_type=TagInfo
        )

    async def fetch_owned_tag_list(
        self, location_id: int, owner_id: int
    ) -> list[TagListEntry]:
        query = """--sql
            SELECT
              name,
              id
            FROM tag_lookup
            WHERE location_id = :location_id AND owner_id = :owner_id
            ORDER BY name;
        """
        return await self._db.select(
            query,
            location_id=location_id,
            owner_id=owner_id,
            schema_type=TagListEntry,
        )

    async def fetch_all_tags_dump(
        self, location_id: int, bypass_owner_check: bool, author_id: int
    ) -> list[TagDumpEntry]:
        query = """--sql
            SELECT
              tag_lookup.id,
              tag_lookup.name,
              tag_lookup.owner_id,
              tags2.uses,
              (
                :bypass_owner_check OR tag_lookup.owner_id = :author_id
              ) AS can_delete,
              LOWER(tag_lookup.name) != LOWER(tags2.name) AS is_alias
            FROM tag_lookup
            INNER JOIN tags2 ON tag_lookup.tag_id = tags2.id
            WHERE tag_lookup.location_id = :location_id
            ORDER BY tags2.uses DESC;
        """
        return await self._db.select(
            query,
            location_id=location_id,
            bypass_owner_check=bypass_owner_check,
            author_id=author_id,
            schema_type=TagDumpEntry,
        )

    async def fetch_tag_list(self, location_id: int) -> list[TagListEntry]:
        query = """--sql
            SELECT
              name,
              id
            FROM tag_lookup
            WHERE location_id = :location_id
            ORDER BY name;
        """
        return await self._db.select(
            query, location_id=location_id, schema_type=TagListEntry
        )

    async def count_owned_tags(self, location_id: int, owner_id: int) -> int:
        query = """--sql
            SELECT COUNT(*)
            FROM tags2
            WHERE location_id = :location_id AND owner_id = :owner_id;
        """
        return await self._db.select_value(
            query, location_id=location_id, owner_id=owner_id
        )

    async def purge_owned_tags(self, location_id: int, owner_id: int) -> None:
        query = """--sql
            DELETE FROM tags2
            WHERE location_id = :location_id AND owner_id = :owner_id;
        """
        await self._db.execute(query, location_id=location_id, owner_id=owner_id)

    async def search_tags(self, location_id: int, term: str) -> list[TagListEntry]:
        query = """--sql
            SELECT
              name,
              id
            FROM tag_lookup
            WHERE location_id = :location_id AND name % :term
            ORDER BY SIMILARITY(name, :term) DESC
            LIMIT 100;
        """
        return await self._db.select(
            query, location_id=location_id, term=term, schema_type=TagListEntry
        )

    async def fetch_tag_owner(self, location_id: int, name: str) -> TagOwner | None:
        query = """--sql
            SELECT
              id,
              owner_id
            FROM tags2
            WHERE location_id = :location_id AND LOWER(name) = :name;
        """
        return await self._db.select_one_or_none(
            query, location_id=location_id, name=name, schema_type=TagOwner
        )

    async def fetch_tag_lookup_owner(
        self, location_id: int, name: str
    ) -> TagLookupOwner | None:
        query = """--sql
            SELECT
              tag_id,
              owner_id
            FROM tag_lookup
            WHERE location_id = :location_id AND LOWER(name) = :name;
        """
        return await self._db.select_one_or_none(
            query, location_id=location_id, name=name, schema_type=TagLookupOwner
        )

    async def set_tag_owner(self, tag_id: int, owner_id: int) -> None:
        query = """--sql
            UPDATE tags2
            SET owner_id = :owner_id
            WHERE id = :tag_id;
        """
        await self._db.execute(query, tag_id=tag_id, owner_id=owner_id)

    async def set_tag_lookup_owner(self, tag_id: int, owner_id: int) -> None:
        query = """--sql
            UPDATE tag_lookup
            SET owner_id = :owner_id
            WHERE tag_id = :tag_id;
        """
        await self._db.execute(query, tag_id=tag_id, owner_id=owner_id)
