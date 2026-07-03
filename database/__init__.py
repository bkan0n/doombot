from typing import TYPE_CHECKING

from .services import (
    DuelService,
    GymService,
    MapService,
    MiscService,
    RecordService,
    TagService,
    TournamentService,
    UserService,
    XPService,
)

if TYPE_CHECKING:
    from sqlspec import AsyncDriverAdapterBase

__all__ = [
    "Services",
]


class Services:
    """All DB services bound to one active session."""

    __slots__ = (
        "db",
        "duels",
        "gym",
        "maps",
        "misc",
        "records",
        "tags",
        "tournament",
        "users",
        "xp",
    )

    def __init__(self, db: AsyncDriverAdapterBase) -> None:
        self.db = db
        self.duels = DuelService(db)
        self.gym = GymService(db)
        self.maps = MapService(db)
        self.misc = MiscService(db)
        self.records = RecordService(db)
        self.tags = TagService(db)
        self.tournament = TournamentService(db)
        self.users = UserService(db)
        self.xp = XPService(db)
