from __future__ import annotations

import datetime
import math
import typing
from typing import Literal

import discord.utils

from utils import make_ordinal, pretty_record

if typing.TYPE_CHECKING:
    import core

import utils
from cogs.tournament.utils import Categories, Category, CategoryData, Rank
from cogs.tournament.utils.utils import role_map

EMBED_LIMIT = 3

rank_display = {
    Rank.GOLD: "<:gold:931317421862699118>",
    Rank.DIAMOND: "<:diamond:931317455639445524>",
    Rank.GRANDMASTER: "<:grandmaster:931317469396729876>",
    Rank.UNRANKED: "",
}

category_color = {
    Category.TIME_ATTACK: "#CAFFD0",
    Category.MILDCORE: "#EE6C4D",
    Category.HARDCORE: "#DB2B39",
    Category.BONUS: "#AD1457",
}


class SeasonData(typing.TypedDict):
    name: str
    active: bool


Seasons: typing.TypeAlias = dict[int, SeasonData]


def base_embed(
    description: str,
    embed_type: Literal["start", "end", "announcement", "leaderboard", "hall_of_fame", "missions"],
) -> discord.Embed:
    embed = utils.DoomEmbed(
        title="Doomfist Parkour Tournament",
        description=description,
        thumbnail="https://bkan0n.com/assets/images/icons/gold_cup.png",
        image=f"https://bkan0n.com/assets/images/icons/tournament_{embed_type}_banner.png",
        color=discord.Color.gold(),
    )
    return embed


def leaderboard_embed(description: str, category: Categories, rank: Rank | None):
    embed = base_embed(description=description, embed_type="leaderboard")
    if rank:
        embed.set_thumbnail(url=f"https://bkan0n.com/assets/images/icons/{rank.lower()}.png")
    embed.set_image(url=f"https://bkan0n.com/assets/images/tournament/{category.lower().replace(' ', '_')}.png")

    embed.colour = discord.Color.from_str(category_color[category])
    return embed


def announcement_embed(announcement: str):
    return base_embed(announcement, "announcement")


def missions_embed(announcement: str):
    return base_embed(announcement, "missions")


def end_embed():
    description = "**The round has ended!**\n" "Stay tuned for the next announcement!\n\n"
    return base_embed(description, "end")


class TournamentData:
    def __init__(
        self,
        *,
        client: core.Doom,
        title: str,
        start: datetime.datetime,
        end: datetime.datetime,
        data: dict[Category, CategoryData],
        bracket: bool,
        id_: int | None = None,
    ):
        self.client = client
        self.title = title
        self.start = start
        self.end = end
        self.map_data = data
        self.bracket = bracket
        self.id = id_

    def __repr__(self):
        return (
            f"Tournament<{self.id}>: \n"
            f" - Title: {self.title}\n"
            f" - Start: {self.start}\n"
            f" - End: {self.start}\n"
            f" - Bracket: {self.bracket}"
        )

    @property
    def categories(self) -> list[Category]:
        return [cat for cat in Category.all() if cat in self.map_data]

    @property
    def ta_data(self) -> CategoryData | None:
        return self.map_data.get(Category.TIME_ATTACK, None)

    @property
    def mc_data(self) -> CategoryData | None:
        return self.map_data.get(Category.MILDCORE, None)

    @property
    def hc_data(self) -> CategoryData | None:
        return self.map_data.get(Category.HARDCORE, None)

    @property
    def bo_data(self) -> CategoryData | None:
        return self.map_data.get(Category.BONUS, None)

    @property
    def start_formatted(self) -> str:
        return discord.utils.format_dt(self.start, style="R") + "\n" + discord.utils.format_dt(self.start, style="F")

    @property
    def end_formatted(self) -> str:
        return discord.utils.format_dt(self.end, style="R") + "\n" + discord.utils.format_dt(self.end, style="F")

    @property
    def dates(self):
        return f"**Start:**\n{self.start_formatted}\n" f"**End:**\n{self.end_formatted}"

    @property
    def mention_ids(self) -> list[int]:
        trifecta = [role_map["Trifecta"]]
        base = [role_map[cat] for cat in Category.all() if cat in self.map_data]
        return base + trifecta

    def embed_description(self) -> str:
        map_info = ""
        for cat, data in self.map_data.items():
            map_info += (
                self.client.get_guild(utils.GUILD_ID).get_role(role_map[cat]).mention + "\n"
                f"**Code:** {data['code']}\n"
                f"**Level:** {data['level']}\n"
                f"**Creator:** {data['creator']}\n"
            )

        return map_info

    def start_embed(self):
        return base_embed(self.embed_description() + "\n\n" + self.dates, "start")

    async def hall_of_fame(self):
        hof_embed = base_embed("", "hall_of_fame")
        hof_embed.title += "Hall of Fame - Top 3"
        lb_embeds = []
        for category in ["Time Attack", "Mildcore", "Hardcore", "Bonus"]:
            if category not in self.map_data:
                continue
            lb_description = []
            hof_embed_field_value = ""
            query = """
                WITH t_records AS (SELECT tr.user_id, record, coalesce(ur.value, 'Unranked') as value, tr.category, screenshot, inserted_at
                                   FROM tournament_records tr
                                            LEFT JOIN user_ranks ur on tr.user_id = ur.user_id and tr.category = ur.category
                                   WHERE tournament_id = $1),
                     ranks AS (SELECT user_id,
                                      record,
                                      value,
                                      category,
                                      screenshot,
                                      rank() OVER (
                                       PARTITION BY user_id, category
                                        ORDER BY inserted_at DESC
                                      ) as latest
                               FROM t_records)
                SELECT r.user_id, nickname, record, value , category, screenshot, latest,
                
                                      rank() OVER (
                                          PARTITION BY category
                                          ORDER BY record
                                          ) rank_num
                FROM ranks r
                LEFT JOIN users u ON r.user_id = u.user_id
                WHERE category = $2 
                AND latest = 1
                ORDER BY category != 'Time Attack',
                         category != 'Mildcore',
                         category != 'Hardcore',
                         category != 'Bonus',
                             rank_num
            """
            rows = await self.client.database.fetch(query, self.id, category)
            for row in rows:
                value = (
                    f"`{make_ordinal(row['rank_num'])}` - "
                    f"{row['nickname']} - [{pretty_record(row['record'])}]({row['screenshot']}) "
                    f"{rank_display[row['value']]}\n"
                )
                if row.rank_num <= 3:
                    hof_embed_field_value += value
                lb_description.append(value)
            hof_embed.add_field(
                name=category,
                value=hof_embed_field_value,
                inline=False,
            )

            num_of_embeds = math.ceil(len(lb_description) / EMBED_LIMIT)
            all_embeds = []
            for i in range(num_of_embeds):
                _data = lb_description[i * EMBED_LIMIT : (i + 1) * EMBED_LIMIT]
                _embed = leaderboard_embed("".join(_data), category, None)
                all_embeds.append(_embed)
            lb_embeds.extend(all_embeds)

        return hof_embed, lb_embeds
