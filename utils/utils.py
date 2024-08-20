from __future__ import annotations

import asyncio
import datetime
import logging
import operator
import re
import typing

import discord
from discord import app_commands
from discord.ext import tasks
from thefuzz import fuzz

import utils
from cogs.tournament.utils.data import TournamentData, end_embed
from cogs.tournament.utils.end_tournament import ExperienceCalculator, SpreadsheetCreator
from cogs.tournament.utils.utils import ANNOUNCEMENTS
from utils import HALL_OF_FAME_ID, TOURNAMENT_SUBMISSIONS

if typing.TYPE_CHECKING:
    from core import DoomItx

CODE_VERIFICATION = re.compile(r"^[A-Z0-9]{4,6}$")

log = logging.getLogger(__name__)


async def delete_interaction(itx: DoomItx, *, minutes: int | float):
    """Delete an itx message after x minutes. Fails silently.
    Args:
        itx (discord.Interaction): Interaction to find original message.
        minutes (int): Minutes (use 0 for no delay)
    """
    if minutes < 0:
        raise ValueError("Time cannot be negative.")
    await asyncio.sleep(60 * minutes)
    try:
        await itx.delete_original_response()
    except (discord.HTTPException, discord.NotFound, discord.Forbidden):
        ...


def fuzz_(string: str, iterable: typing.Iterable[str]) -> str:
    """Fuzz a value."""
    values = [(val, fuzz.partial_ratio(string, val)) for val in iterable]
    return str(max(values, key=operator.itemgetter(1))[0])


def fuzz_multiple(string: str, iterable: typing.Iterable[str]) -> list[str]:
    """Fuzz a value."""
    values = [(val, fuzz.partial_ratio(string, val)) for val in iterable]
    values = sorted(values, key=operator.itemgetter(1), reverse=True)[:10]
    values = list(map(lambda x: x[0], values))
    return values


class MapCacheData(typing.TypedDict):
    levels: list[str]
    user_ids: list[int]
    choices: list[app_commands.Choice]


class UserCacheData(typing.TypedDict):
    nickname: str
    alertable: bool


NUMBER_EMOJI = {
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
    9: "9️⃣",
    10: "🔟",
}


def split_nth_conditional(cur_i: int, n: int, collection: typing.Sequence) -> bool:
    return (cur_i != 0 and cur_i % n == 0) or (cur_i == 0 and len(collection) == 1) or cur_i == len(collection) - 1


async def tournament_task(
    data: TournamentData,
    start: bool,
    func: typing.Callable[[TournamentData], typing.Awaitable[None]],
):
    time = "start" if start else "end"

    await func(data)


@tasks.loop()
async def start_tournament_task(data: TournamentData):
    current_date = datetime.datetime.utcnow().date()
    start_date = data.start.date()

    if current_date == start_date:
        await start_tournament(data)


@tasks.loop()
async def end_tournament_task(data: TournamentData):
    current_date = datetime.datetime.utcnow().date()
    end_date = data.end.date()

    if current_date == end_date:
        await end_tournament(data)


async def start_tournament(data: TournamentData):
    # Post announcement
    mentions = [data.client.get_guild(utils.GUILD_ID).get_role(_id).mention for _id in data.mention_ids]

    await data.client.get_guild(utils.GUILD_ID).get_channel(ANNOUNCEMENTS).send("".join(mentions), embed=data.start_embed())
    # Open submissions channel
    guild = data.client.get_guild(utils.GUILD_ID)
    add_perms = guild.get_channel(TOURNAMENT_SUBMISSIONS).overwrites_for(guild.default_role)
    add_perms.update(send_messages=True)
    await guild.get_channel(TOURNAMENT_SUBMISSIONS).set_permissions(
        guild.default_role,
        overwrite=add_perms,
        reason="Tournament Ended.",
    )
    query = "UPDATE tournament SET active=TRUE WHERE id=$1;"
    await data.client.database.execute(query, data.id)


async def end_tournament(data: TournamentData):
    guild = data.client.get_guild(utils.GUILD_ID)
    query = "UPDATE tournament SET active=FALSE WHERE id=$1;"
    await data.client.database.execute(query, data.id)
    remove_perms = guild.get_channel(TOURNAMENT_SUBMISSIONS).overwrites_for(guild.default_role)
    remove_perms.update(send_messages=False)
    await guild.get_channel(TOURNAMENT_SUBMISSIONS).set_permissions(
        guild.default_role,
        overwrite=remove_perms,
        reason="Tournament Ended.",
    )

    xp = await ExperienceCalculator(data).compute_xp()
    users_xp = [(k, v["Total XP"], data.client.current_season) for k, v in xp.items()]
    query = """
        INSERT INTO user_xp (user_id, xp, season) 
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id, season) DO UPDATE 
        SET xp = user_xp.xp + EXCLUDED.xp
        RETURNING user_xp.xp
    """
    await data.client.database.executemany(query, users_xp)

    await SpreadsheetCreator(data, xp).create()

    mentions = [
        data.client.get_guild(utils.GUILD_ID).get_role(_id).mention for _id in data.client.current_tournament.mention_ids
    ]

    await guild.get_channel(ANNOUNCEMENTS).send(
        "".join(mentions),
        embed=end_embed(),
    )

    hof_embed, lb_embeds = await data.hall_of_fame()
    hof_msg = await guild.get_channel(HALL_OF_FAME_ID).send(embed=hof_embed)
    hof_thread = await hof_msg.create_thread(name="Records Archive")
    file = discord.File(
        fp=r"DPK_Tournament.xlsx",
        filename=f"DPK_Tournament_{datetime.datetime.now().strftime('%d-%m-%Y')}.xlsx",
    )
    try:
        await hof_thread.send(embeds=lb_embeds, file=file)
    except discord.errors.HTTPException:
        log_embed_data(lb_embeds)
        await hof_thread.send(file=file)

    data.client.current_tournament = None


def log_embed_data(embeds: list[discord.Embed]):
    for embed in embeds:
        log.info(embed.description)
        if embed.description:
            log.info(len(embed.description))
