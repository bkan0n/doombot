import typing

import msgspec

from ._base import Service


class MapSearchResult(msgspec.Struct, frozen=True):
    map_code: str
    map_type: str
    map_name: str
    desc: str | None
    official: bool
    image: str | None
    creators: str
    creators_ids: list[int]
    levels: list[str]
    rating: float


class RandomMapResult(msgspec.Struct, frozen=True):
    map_code: str
    map_type: str
    map_name: str
    desc: str | None
    official: bool
    image: str | None
    creators: str
    creators_ids: list[int]
    level: str | None
    avg_rating: float | None
    rating: float | None


class MapCacheEntry(msgspec.Struct, frozen=True):
    map_code: str
    levels: list[str | None]
    user_ids: list[int | None]


class MapService(Service):
    """Maps, levels, creators, guides, search, and autocomplete caches."""

    async def set_map_code(self, old_map_code: str, new_map_code: str) -> None:
        query = """--sql
            UPDATE maps
            SET map_code = :new_map_code
            WHERE map_code = :old_map_code;
        """
        await self._db.execute(
            query, old_map_code=old_map_code, new_map_code=new_map_code
        )

    async def add_creator(self, map_code: str, user_id: int) -> None:
        query = """--sql
            INSERT INTO map_creators (map_code, user_id)
            VALUES (:map_code, :user_id);
        """
        await self._db.execute(query, map_code=map_code, user_id=user_id)

    async def remove_creator(self, map_code: str, user_id: int) -> None:
        query = """--sql
            DELETE FROM map_creators
            WHERE map_code = :map_code AND user_id = :user_id;
        """
        await self._db.execute(query, map_code=map_code, user_id=user_id)

    async def add_levels(self, map_code: str, levels: list[str]) -> None:
        query = """--sql
            INSERT INTO map_levels (map_code, level)
            SELECT
              :map_code,
              UNNEST(CAST(:levels AS TEXT [])) AS level;
        """
        await self._db.execute(query, map_code=map_code, levels=levels)

    async def delete_level(self, map_code: str, level: str) -> None:
        query = """--sql
            DELETE FROM map_levels
            WHERE map_code = :map_code AND level = :level;
        """
        await self._db.execute(query, map_code=map_code, level=level)

    async def rename_level(self, map_code: str, level: str, new_level: str) -> None:
        query = """--sql
            UPDATE map_levels
            SET level = :new_level
            WHERE map_code = :map_code AND level = :level;
        """
        await self._db.execute(
            query, map_code=map_code, level=level, new_level=new_level
        )

    async def create_map(
        self,
        map_name: str,
        map_type: list[str],
        map_code: str,
        description: str | None,
        image: str | None,
    ) -> None:
        query = """--sql
            INSERT INTO maps (map_name, map_type, map_code, "desc", image)
            VALUES (:map_name, :map_type, :map_code, :description, :image);
        """
        await self._db.execute(
            query,
            map_name=map_name,
            map_type=map_type,
            map_code=map_code,
            description=description,
            image=image,
        )

    async def set_map_image(self, map_code: str, image: str) -> None:
        query = """--sql
            UPDATE maps
            SET image = :image
            WHERE map_code = :map_code;
        """
        await self._db.execute(query, map_code=map_code, image=image)

    @typing.overload
    async def fetch_map(
        self,
        *,
        map_code: str,
        map_type: str | None = None,
        map_name: str | None = None,
        creator: int | None = None,
    ) -> MapSearchResult | None: ...

    @typing.overload
    async def fetch_map(
        self,
        *,
        map_type: str | None = None,
        map_name: str | None = None,
        creator: int | None = None,
    ) -> list[MapSearchResult]: ...

    async def fetch_map(
        self,
        *,
        map_type: str | None = None,
        map_name: str | None = None,
        map_code: str | None = None,
        creator: int | None = None,
    ) -> MapSearchResult | None | list[MapSearchResult]:
        query = """--sql
            WITH map_creator_info AS (
              SELECT
                mc.map_code,
                STRING_AGG(DISTINCT u.nickname, ', ') AS creators,
                ARRAY_AGG(DISTINCT mc.user_id) AS creators_ids
              FROM map_creators AS mc
              INNER JOIN users AS u ON mc.user_id = u.user_id
              GROUP BY mc.map_code
            ),
            
            map_level_info AS (
              SELECT
                map_code,
                ARRAY_AGG(level ORDER BY level) AS levels
              FROM map_levels
              GROUP BY map_code
            ),
            
            map_rating_info AS (
              SELECT
                map_code,
                CAST(AVG(rating) AS FLOAT) AS rating
              FROM map_level_ratings
              GROUP BY map_code
            )
            
            SELECT
              m.map_code,
              ARRAY_TO_STRING(m.map_type, ', ') AS map_type,
              m.map_name,
              m."desc",
              m.official,
              m.image,
              mci.creators,
              mci.creators_ids,
              COALESCE(mli.levels, CAST('{}' AS TEXT [])) AS levels,
              COALESCE(mri.rating, 0) AS rating
            FROM maps AS m
            INNER JOIN map_creator_info AS mci ON m.map_code = mci.map_code
            LEFT JOIN map_level_info AS mli ON m.map_code = mli.map_code
            LEFT JOIN map_rating_info AS mri ON m.map_code = mri.map_code
            WHERE
              (
                CAST(:map_type AS TEXT) IS NULL
                OR :map_type = ANY(m.map_type)
              )
              AND (CAST(:map_name AS TEXT) IS NULL OR m.map_name = :map_name)
              AND (CAST(:map_code AS TEXT) IS NULL OR m.map_code = :map_code)
              AND (
                CAST(:creator AS BIGINT) IS NULL
                OR :creator = ANY(mci.creators_ids)
              )
            ORDER BY m.map_code;
        """
        if map_code is not None:
            return await self._db.select_one_or_none(
                query,
                map_type=None,
                map_name=None,
                map_code=map_code,
                creator=None,
                schema_type=MapSearchResult,
            )
        return await self._db.select(
            query,
            map_type=map_type,
            map_name=map_name,
            map_code=map_code,
            creator=creator,
            schema_type=MapSearchResult,
        )

    async def fetch_random_map(self) -> RandomMapResult | None:
        query = """--sql
            WITH valid_ratings AS (
              SELECT
                m.map_code,
                ml.level,
                mr.rating,
                mr.user_id
              FROM maps AS m
              LEFT JOIN map_levels AS ml ON m.map_code = ml.map_code
              LEFT JOIN map_level_ratings AS mr
                ON m.map_code = mr.map_code AND ml.level = mr.level
              LEFT JOIN records AS r -- noqa: ST11
                ON
                  mr.user_id = r.user_id
                  AND ml.level = r.level_name
                  AND mr.map_code = r.map_code
            ),
            
            levels_with_ratings AS (
              SELECT
                map_code,
                level,
                CAST(AVG(rating) AS FLOAT) AS avg_rating
              FROM valid_ratings
              GROUP BY map_code, level
            ),
            
            random_map_level AS (
              SELECT
                map_code,
                level,
                avg_rating
              FROM levels_with_ratings
              LIMIT
                1
                OFFSET
                RANDOM()
                * (SELECT COUNT(lwr.map_code) FROM levels_with_ratings AS lwr)
            )
            
            SELECT
              map_code,
              map_type,
              map_name,
              "desc",
              official,
              image,
              creators,
              creators_ids,
              level,
              avg_rating,
              CAST(AVG(rating) AS FLOAT) AS rating
            FROM (
              SELECT
                mc.map_code,
                ARRAY_TO_STRING(maps.map_type, ', ') AS map_type,
                maps.map_name,
                maps."desc",
                maps.official,
                maps.image,
                rml.level,
                rml.avg_rating,
                STRING_AGG(DISTINCT u.nickname, ', ') AS creators,
                ARRAY_AGG(DISTINCT mc.user_id) AS creators_ids,
                AVG(vr.rating) AS rating
              FROM maps
              INNER JOIN map_creators AS mc ON maps.map_code = mc.map_code
              INNER JOIN users AS u ON mc.user_id = u.user_id
              LEFT JOIN random_map_level AS rml ON maps.map_code = rml.map_code
              LEFT JOIN valid_ratings AS vr ON maps.map_code = vr.map_code
              WHERE maps.map_code = rml.map_code
              GROUP BY
                maps.map_type,
                mc.map_code,
                maps.map_name,
                maps."desc",
                maps.official,
                maps.image,
                rml.level,
                rml.avg_rating
              ORDER BY mc.map_code
            ) AS layer0
            GROUP BY
              map_code,
              map_type,
              map_name,
              "desc",
              official,
              image,
              creators,
              creators_ids,
              level,
              avg_rating;
        """
        return await self._db.select_one_or_none(query, schema_type=RandomMapResult)

    async def add_guide(self, map_code: str, url: str) -> None:
        query = """--sql
            INSERT INTO guides (map_code, url)
            VALUES (:map_code, :url);
        """
        await self._db.execute(query, map_code=map_code, url=url)

    async def fetch_guides(self, map_code: str) -> list[str]:
        query = """--sql
            SELECT url
            FROM guides
            WHERE map_code = :map_code;
        """
        rows = await self._db.select(query, map_code=map_code)
        return [row["url"] for row in rows]

    async def fetch_map_codes(self) -> list[str]:
        query = """--sql
            SELECT map_code
            FROM maps
            ORDER BY map_code;
        """
        rows = await self._db.select(query)
        return [row["map_code"] for row in rows]

    async def fetch_map_names(self) -> list[str]:
        query = """--sql
            SELECT name
            FROM all_map_names
            ORDER BY name;
        """
        rows = await self._db.select(query)
        return [row["name"] for row in rows]

    async def insert_map_name(self, name: str, color: str = "000000") -> bool:
        query = """--sql
            INSERT INTO all_map_names (name, color)
            SELECT
              :name,
              :color
            WHERE
              NOT EXISTS (
                SELECT 1
                FROM all_map_names
                WHERE LOWER(name) = LOWER(:name)
              );
        """
        result = await self._db.execute(query, name=name, color=color)
        return bool(result.rows_affected)

    async def fetch_map_types(self) -> list[str]:
        query = """--sql
            SELECT name
            FROM all_map_types
            ORDER BY name;
        """
        rows = await self._db.select(query)
        return [row["name"] for row in rows]

    async def map_code_exists(self, map_code: str) -> bool:
        query = """--sql
            SELECT
              EXISTS(
                SELECT 1
                FROM maps
                WHERE map_code = :map_code
              ) AS exists;
        """
        return await self._db.select_value(query, map_code=map_code)

    async def autocomplete_map_codes(
        self, search: str, *, limit: int = 25
    ) -> list[str]:
        query = """--sql
            SELECT map_code
            FROM maps
            ORDER BY
              CASE
                WHEN map_code = :search THEN 3
                WHEN map_code ILIKE :search || '%' THEN 2
                ELSE SIMILARITY(map_code, :search)
              END DESC,
              map_code
            LIMIT :limit;
        """
        rows = await self._db.select(query, search=search, limit=limit)
        return [row["map_code"] for row in rows]

    async def transform_map_name(self, search: str) -> str | None:
        query = """--sql
            SELECT name
            FROM all_map_names
            ORDER BY SIMILARITY(name, :search) DESC
            LIMIT 1;
        """
        return await self._db.select_value_or_none(query, search=search)

    async def autocomplete_map_names(
        self, search: str, *, limit: int = 25
    ) -> list[str]:
        query = """--sql
            SELECT name
            FROM all_map_names
            ORDER BY SIMILARITY(name, :search) DESC, name
            LIMIT :limit;
        """
        rows = await self._db.select(query, search=search, limit=limit)
        return [row["name"] for row in rows]

    async def transform_map_type(self, search: str) -> str | None:
        query = """--sql
            SELECT name
            FROM all_map_types
            ORDER BY SIMILARITY(name, :search) DESC
            LIMIT 1;
        """
        return await self._db.select_value_or_none(query, search=search)

    async def autocomplete_map_types(
        self, search: str, *, limit: int = 25
    ) -> list[str]:
        query = """--sql
            SELECT name
            FROM all_map_types
            ORDER BY SIMILARITY(name, :search) DESC, name
            LIMIT :limit;
        """
        rows = await self._db.select(query, search=search, limit=limit)
        return [row["name"] for row in rows]

    async def transform_map_level(self, map_code: str, search: str) -> str | None:
        query = """--sql
            SELECT level
            FROM map_levels
            WHERE map_code = :map_code
            -- pg_trgm strips punctuation, so "Advanced" and "Advanced+" tie at
            -- similarity 1.0; prefer the exact match and break ties by name.
            ORDER BY
              LOWER(level) = LOWER(:search) DESC,
              SIMILARITY(level, :search) DESC,
              level
            LIMIT 1;
        """
        return await self._db.select_value_or_none(
            query, map_code=map_code, search=search
        )

    async def autocomplete_map_levels(
        self, map_code: str, search: str, *, limit: int = 25
    ) -> list[str]:
        query = """--sql
            SELECT level
            FROM map_levels
            WHERE map_code = :map_code
            ORDER BY
              LOWER(level) = LOWER(:search) DESC,
              SIMILARITY(level, :search) DESC,
              level
            LIMIT :limit;
        """
        rows = await self._db.select(
            query, map_code=map_code, search=search, limit=limit
        )
        return [row["level"] for row in rows]

    async def fetch_map_cache_entries(self) -> list[MapCacheEntry]:
        query = """--sql
            SELECT
              m.map_code,
              ARRAY_AGG(DISTINCT ml.level) AS levels,
              ARRAY_AGG(DISTINCT mc.user_id) AS user_ids
            FROM maps AS m
            LEFT JOIN map_levels AS ml ON m.map_code = ml.map_code
            LEFT JOIN map_creators AS mc ON m.map_code = mc.map_code
            GROUP BY m.map_code
            ORDER BY levels;
        """
        return await self._db.select(query, schema_type=MapCacheEntry)
