from __future__ import annotations

import datetime
import io
import re
import traceback
import typing

import discord
from discord import app_commands

import utils

if typing.TYPE_CHECKING:
    from core import DoomItx


class BaseParkourException(Exception):
    def __init__(self):
        super().__init__(self.__doc__)


class DatabaseConnectionError(Exception):
    """Connection failed. This will be logged. Try again later."""


class IncorrectRecordFormatError(BaseParkourException, app_commands.errors.AppCommandError):
    """Record must be in HH:MM:SS.ss format."""


class IncorrectCodeFormatError(BaseParkourException, app_commands.errors.AppCommandError):
    """Map code must be a valid Overwatch share code."""


class IncorrectURLFormatError(BaseParkourException, app_commands.errors.AppCommandError):
    """The given URL is invalid."""


class InvalidFiltersError(BaseParkourException):
    """
    You must choose _at least_ **one** filter
    (map name, map type, or creator, mechanics, official, difficulty)
    """


class InvalidMapNameError(BaseParkourException, app_commands.errors.AppCommandError):
    """Invalid map name given. Please make sure to use the autocompleted map names."""


class InvalidMapCodeError(BaseParkourException, app_commands.errors.AppCommandError):
    """Invalid map code given. Please make sure to use the autocompleted map codes."""


class InvalidMapLevelError(BaseParkourException, app_commands.errors.AppCommandError):
    """Invalid map level given. Please make sure to use the autocompleted map levels."""


class InvalidMapTypeError(BaseParkourException, app_commands.errors.AppCommandError):
    """Invalid map name given. Please make sure to use the autocompleted map types."""


class RecordNotFasterError(BaseParkourException):
    """Record must be faster than your previous submission."""


class NoMapsFoundError(BaseParkourException):
    """No maps have been found with the given filters."""


class NoRecordsFoundError(BaseParkourException):
    """No records have been found."""


class NoPermissionsError(BaseParkourException):
    """You do not have permission to do this action."""


class CreatorAlreadyExists(BaseParkourException):
    """Creator already associated with this map."""


class CreatorDoesntExist(BaseParkourException):
    """Creator is not associated with this map."""


class LevelExistsError(BaseParkourException):
    """This level already exists!"""


class NoGuidesExistError(BaseParkourException):
    """No guides exist for this map code."""


class GuideExistsError(BaseParkourException):
    """This guide has already been submitted."""


class OutOfRangeError(BaseParkourException):
    """Choice is out of range."""


class InvalidInteger(BaseParkourException):
    """Choice must be a valid integer."""


class UserNotFoundError(BaseParkourException, app_commands.errors.AppCommandError):
    """User does not exist."""


class NoExercisesFound(BaseParkourException, app_commands.errors.AppCommandError):
    """No exercises match the given filters."""


class NoDataOnCurrentSeason(BaseParkourException):
    """No data found for this user during the selected season."""


async def on_app_command_error(interaction: DoomItx, error: app_commands.errors.AppCommandError):
    exception = getattr(error, "original", error)
    if isinstance(exception, utils.BaseParkourException):
        embed = utils.ErrorEmbed(description=str(exception))
        await _respond(embed, interaction)
    elif isinstance(exception, app_commands.CommandOnCooldown):
        now = discord.utils.utcnow()
        search = re.search(r"(\d+\.\d{2})s", str(exception))
        if not search:
            return
        seconds = float(search.group(1))
        end = now + datetime.timedelta(seconds=seconds)
        embed = utils.ErrorEmbed(
            description=(
                "Command is on cooldown. Cooldown ends "
                f"{discord.utils.format_dt(end, style='R')}.\n"
                "This message will be deleted at the same time."
            )
        )
        await _respond(embed, interaction)
        await utils.delete_interaction(interaction, minutes=seconds / 60)
    else:
        edit = interaction.edit_original_response if interaction.response.is_done() else interaction.response.send_message

        embed = utils.ErrorEmbed(
            description=("Unknown.\n" "It has been logged and sent to <@141372217677053952>.\n" "Please try again later."),
            unknown=True,
        )
        await edit(
            embed=embed,
        )

        channel = interaction.client.get_channel(1246119507689214093)
        assert interaction.command
        command_name = f"**Command:** `{interaction.command.name}`\n"
        channel_name = f"**Channel:** `{interaction.channel}`\n"
        user_name = f"**User:** `{interaction.user}`"
        args = [f"┣ **{k}:** `{v}`\n" for k, v in interaction.namespace.__dict__.items()]
        if args:
            args[-1] = "┗" + args[-1][1:]
        args_name = "**Args:**\n" + "".join(args)
        formatted_tb = "".join(traceback.format_exception(None, exception, exception.__traceback__))
        assert isinstance(channel, discord.TextChannel)
        if len(formatted_tb) < 1850:
            await channel.send(f"{command_name}{args_name}{channel_name}{user_name}\n```py\n" + formatted_tb + "\n```")
        else:
            await channel.send(
                f"{command_name} {args_name} {channel_name} {user_name}",
                file=discord.File(
                    fp=io.BytesIO(
                        bytearray(
                            str(exception) + formatted_tb,
                            "utf-8",
                        )
                    ),
                    filename="error.log",
                ),
            )
    await utils.delete_interaction(interaction, minutes=15)


async def _respond(embed: discord.Embed | utils.DoomEmbed | utils.ErrorEmbed, itx: DoomItx):
    if itx.response.is_done():
        await itx.edit_original_response(
            embed=embed,
        )
    else:
        await itx.response.send_message(
            embed=embed,
            ephemeral=True,
        )
