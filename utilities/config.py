from __future__ import annotations

import msgspec

__all__ = ("Config", "decode")


class Base(msgspec.Struct, forbid_unknown_fields=True): ...


class TournamentRoles(Base):
    time_attack: int
    mildcore: int
    hardcore: int
    bonus: int
    trifecta: int
    organizer: int


class PronounRoles(Base):
    they_them: int
    she_her: int
    he_him: int


class PingRoles(Base):
    announcements: int
    eu_sleep: int
    na_sleep: int
    asia_sleep: int
    oce_sleep: int
    movie_night: int
    game_night: int


class Roles(Base):
    staff: int
    tournament: TournamentRoles
    pronouns: PronounRoles
    pings: PingRoles


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
    announcements: int
    chat: int
    org_chat: int
    hall_of_fame: int


class Channels(Base):
    submission: Submission
    records: Records
    tournament: Tournament
    gym: int
    duels: int


class Config(Base):
    guild: int
    roles: Roles
    channels: Channels


def decode(data: bytes | str) -> Config:
    """Decode a config.toml file."""
    return msgspec.toml.decode(data, type=Config)
