import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger
from sqlspec import AsyncDriverAdapterBase

import extensions
from database import Services
from utilities import views
from utilities.config import Config, decode
from utilities.errors import UserFacingError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from contextlib import AbstractAsyncContextManager

    from aiohttp import ClientSession
    from sqlspec import AsyncDatabaseConfig, SQLSpec


def _generate_intents() -> discord.Intents:
    intents = discord.Intents(
        guild_messages=True,
        guilds=True,
        integrations=True,
        dm_messages=True,
        webhooks=True,
        members=True,
        message_content=True,
        guild_reactions=True,
        # invites=True,
        # emojis=True,
        # bans=True,
        # presences=True,
        # dm_typing=True,
        # voice_states=True,
        # dm_reactions=True,
        # guild_typing=True,
    )
    return intents

class Akande(commands.Bot):
    session: ClientSession
    config: Config

    def __init__(self, spec: SQLSpec, db_config: AsyncDatabaseConfig) -> None:
        env = "prod" if os.getenv("APP_ENVIRONMENT") == "production" else "dev"
        super().__init__(command_prefix="?" if env == "prod" else "$", intents=_generate_intents())
        self._spec = spec
        self._db_config = db_config
        with open(f"configs/{env}.toml", "rb") as f:
            self.config = decode(f.read())

    def db_session(self) -> AbstractAsyncContextManager[AsyncDriverAdapterBase]:
        return self._spec.provide_session(self._db_config)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Services]:
        async with self._spec.provide_session(self._db_config) as db:
            yield Services(db)

    async def on_ready(self) -> None:
        logger.info(f"Bot ({self.application_id}) is now ready.")

    async def setup_hook(self) -> None:
        self.tree.error(self._on_app_command_error)
        for ext in extensions.EXTENSIONS + ["jishaku"]:
            logger.info(f"Loading {ext}...")
            await self.load_extension(ext)

    async def _on_app_command_error(
        self, itx: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, UserFacingError):
            await views.send_error(itx, str(error))
            return
        if isinstance(error, app_commands.CommandOnCooldown):
            await views.send_error(
                itx, f"You're on cooldown. Try again in {error.retry_after:.0f}s."
            )
            return
        logger.opt(exception=error).error("Unhandled application command error")
