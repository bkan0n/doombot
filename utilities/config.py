from __future__ import annotations

import msgspec

__all__ = ("Config", "decode")


class Base(msgspec.Struct, forbid_unknown_fields=True): ...


class Roles(Base):
    staff: int


class Submission(Base):
    new_maps: int
    verification_queue: int


class Records(Base):
    spr_records: int
    records: int
    top_records: int
    hall_of_fame: int


class Tournament(Base):
    submissions: int


class Channels(Base):
    submission: Submission
    records: Records
    tournament: Tournament


class Config(Base):
    guild: int
    roles: Roles
    channels: Channels


def decode(data: bytes | str) -> Config:
    """Decode a config.toml file."""
    return msgspec.toml.decode(data, type=Config)
