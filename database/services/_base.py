from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlspec import AsyncDriverAdapterBase


class Service:
    """Base for database services. Binds to an active SQLSpec session."""

    __slots__ = ("_db",)

    def __init__(self, db: AsyncDriverAdapterBase) -> None:
        self._db = db


@asynccontextmanager
async def transaction(db: AsyncDriverAdapterBase) -> AsyncIterator[None]:
    await db.begin()
    try:
        yield
    except BaseException:
        await db.rollback()
        raise
    else:
        await db.commit()
