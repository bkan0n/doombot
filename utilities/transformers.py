from __future__ import annotations

import re
from typing import TYPE_CHECKING

import aiohttp
from discord import app_commands
from discord.app_commands import Choice

from .errors import UserFacingError

if TYPE_CHECKING:
    from core import AkandeItx

__all__ = (
    "CodeSubmissionTransformer",
    "CodeTransformer",
    "MapLevelTransformer",
    "MapNameTransformer",
    "MapTypeTransformer",
    "RecordTransformer",
    "URLTransformer",
    "UserTransformer",
)

CODE_VERIFICATION = re.compile(r"^[A-Z0-9]{4,6}$")


class _CodeBaseTransformer(app_commands.Transformer):
    @staticmethod
    def _clean_code(map_code: str) -> str:
        return map_code.upper().replace("O", "0").strip()


class CodeSubmissionTransformer(_CodeBaseTransformer):
    """A brand new map code. Must be well-formed and not already in use."""

    async def transform(self, itx: AkandeItx, value: str) -> str:
        value = self._clean_code(value)
        if not CODE_VERIFICATION.match(value):
            raise UserFacingError("Code has an invalid format.")
        async with itx.client.acquire() as svc:
            if await svc.maps.map_code_exists(value):
                raise UserFacingError("Code already exists.")
        return value


class CodeTransformer(_CodeBaseTransformer):
    """An existing map code. Autocompletes against the maps table."""

    async def transform(self, itx: AkandeItx, value: str) -> str:
        value = self._clean_code(value)
        if not CODE_VERIFICATION.match(value):
            raise UserFacingError("Code has an invalid format.")
        async with itx.client.acquire() as svc:
            if not await svc.maps.map_code_exists(value):
                raise UserFacingError("No maps found.")
        return value

    async def autocomplete(
        self, itx: AkandeItx, current: str
    ) -> list[Choice[str | int | float]]:
        async with itx.client.acquire() as svc:
            codes = await svc.maps.autocomplete_map_codes(current)
        return [app_commands.Choice(name=code, value=code) for code in codes]


class MapNameTransformer(app_commands.Transformer):
    async def transform(self, itx: AkandeItx, value: str) -> str:
        async with itx.client.acquire() as svc:
            name = await svc.maps.transform_map_name(value)
        if name is None:
            raise UserFacingError("No matching map name found.")
        return name

    async def autocomplete(
        self, itx: AkandeItx, current: str
    ) -> list[Choice[str | int | float]]:
        async with itx.client.acquire() as svc:
            names = await svc.maps.autocomplete_map_names(current)
        return [app_commands.Choice(name=name, value=name) for name in names]


class MapTypeTransformer(app_commands.Transformer):
    async def transform(self, itx: AkandeItx, value: str) -> str:
        async with itx.client.acquire() as svc:
            map_type = await svc.maps.transform_map_type(value)
        if map_type is None:
            raise UserFacingError("No matching map type found.")
        return map_type

    async def autocomplete(
        self, itx: AkandeItx, current: str
    ) -> list[Choice[str | int | float]]:
        async with itx.client.acquire() as svc:
            types = await svc.maps.autocomplete_map_types(current)
        return [app_commands.Choice(name=t, value=t) for t in types]


class MapLevelTransformer(app_commands.Transformer):
    """A level name scoped to the map_code parameter of the same command."""

    @staticmethod
    def _map_code(itx: AkandeItx) -> str | None:
        map_code: str | None = getattr(itx.namespace, "map_code", None)
        if not map_code:
            return None
        return _CodeBaseTransformer._clean_code(map_code)

    async def transform(self, itx: AkandeItx, value: str) -> str:
        map_code = self._map_code(itx)
        if map_code is None:
            raise UserFacingError("A map code is required to find a level.")
        async with itx.client.acquire() as svc:
            level = await svc.maps.transform_map_level(map_code, value)
        if level is None:
            raise UserFacingError("No matching level found.")
        return level

    async def autocomplete(
        self, itx: AkandeItx, current: str
    ) -> list[Choice[str | int | float]]:
        map_code = self._map_code(itx)
        if map_code is None:
            return []
        async with itx.client.acquire() as svc:
            levels = await svc.maps.autocomplete_map_levels(map_code, current)
        return [app_commands.Choice(name=level[:100], value=level) for level in levels]


class UserTransformer(app_commands.Transformer):
    async def transform(self, itx: AkandeItx, value: str) -> int:
        async with itx.client.acquire() as svc:
            if value.isdigit():
                if not await svc.users.user_exists(int(value)):
                    raise UserFacingError("User not found.")
                return int(value)
            users = await svc.users.autocomplete_users(value, limit=1)
        if not users:
            raise UserFacingError("User not found.")
        return users[0].user_id

    async def autocomplete(
        self, itx: AkandeItx, current: str
    ) -> list[Choice[str | int | float]]:
        async with itx.client.acquire() as svc:
            users = await svc.users.autocomplete_users(current)
        return [
            app_commands.Choice(name=user.nickname[:100], value=str(user.user_id))
            for user in users
        ]


def time_convert(time_str: str) -> float:
    """Convert an [HH:][MM:]SS.ss string into seconds (float)."""
    sign = -1.0 if time_str.startswith("-") else 1.0
    parts = time_str.removeprefix("-").split(":")
    if len(parts) > 3:
        raise ValueError(f"Invalid time format: {time_str!r}")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return sign * total


class RecordTransformer(app_commands.Transformer):
    async def transform(self, itx: AkandeItx, value: str) -> float:
        try:
            return time_convert(value)
        except ValueError:
            raise UserFacingError("Record is in an incorrect format.") from None


class URLTransformer(app_commands.Transformer):
    async def transform(self, itx: AkandeItx, value: str) -> str:
        value = value.strip()
        if not value.startswith(("http://", "https://")):
            value = "https://" + value
        try:
            async with itx.client.session.get(value) as resp:
                if resp.status != 200:
                    raise UserFacingError("URL is invalid.")
                return str(resp.url)
        except aiohttp.ClientError:
            raise UserFacingError("URL is invalid.") from None
