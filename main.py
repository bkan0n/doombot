import asyncio
import logging
import os
import signal

import aiohttp
from discord.utils import setup_logging
from loguru import logger
from sqlspec import SQLSpec
from sqlspec.adapters.asyncpg import AsyncpgConfig

import core

spec = SQLSpec()
config = spec.add_config(
    AsyncpgConfig(
        connection_config={"dsn": os.environ["DSN"]},
        pool_config={"min_size": 1, "max_size": 5},
    )
)


class InterceptHandler(logging.Handler):
    """Forwards stdlib logging records to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


async def main() -> None:
    setup_logging(handler=InterceptHandler())
    logging.getLogger("discord.gateway").setLevel("WARNING")

    task = asyncio.current_task()
    assert task is not None
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)

    await config.create_pool()
    try:
        async with (
            aiohttp.ClientSession() as http,
            core.Akande(spec=spec, db_config=config) as bot,
        ):
            bot.session = http
            await bot.start(os.environ["BOT_TOKEN"])
    finally:
        await spec.close_all_pools()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
