import asyncio
import logging
import os

import aiohttp
import discord.utils

import core
import database


async def main() -> None:
    """
    The main function is the entry point of the program.
    It creates a bot instance and runs it.
    """
    discord.utils.setup_logging()
    # logging.getLogger("discord.gateway").setLevel(30)
    async with aiohttp.ClientSession() as session:
        async with database.DatabaseConnection(
            f"postgres://{os.environ['PSQL_USER']}:{os.environ['PSQL_PASSWORD']}@db/doom3"
        ) as pool:
            assert pool is not None
            async with core.Doom() as bot:
                bot.session = session
                bot.pool = pool
                bot.database = database.Database(pool)
                await bot.start(os.environ["TOKEN"])


if __name__ == "__main__":
    asyncio.run(main())
