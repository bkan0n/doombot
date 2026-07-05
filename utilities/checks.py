from __future__ import annotations

import typing

import discord
from discord import app_commands

from .errors import UserFacingError

if typing.TYPE_CHECKING:
    from core import AkandeItx

__all__ = ("ensure_staff", "is_staff")


def ensure_staff(itx: AkandeItx) -> bool:
    """True if the invoker has the configured staff role, else UserFacingError."""
    assert isinstance(itx.user, discord.Member)
    staff_role = itx.client.config.roles.staff
    if not any(role.id == staff_role for role in itx.user.roles):
        raise UserFacingError("This command is for staff only.")
    return True


def is_staff() -> typing.Any:
    return app_commands.check(ensure_staff)
