from __future__ import annotations

import asyncio
import json
import random
import typing

import discord
from discord import app_commands
from discord.ext import commands

import utils
import views

if typing.TYPE_CHECKING:
    import core
    from core import DoomCtx, DoomItx

with open("assets/emoji-data.json", "r", encoding="utf8") as f:
    mapping = json.load(f)


class Personal(commands.Cog):
    length = 0

    # async def cog_check(self, ctx: DoomCtx) -> bool:
    #     return ctx.channel.id == 882243150419197952 or ctx.guild.id == 968553235239559239  # Spam-friendly

    @commands.command()
    async def joe_army(self, ctx: DoomCtx):
        flag = "<a:_:1105236433523974305>"
        salute = "<:_:1105236435600146493>"
        l_hulk = "<:joehulk:1105236434660630598>"
        r_hulk = "<:joehulkR:1105236430697021491>"
        running = "<a:runningjoe:1105236437290455132>"
        message = f"{flag}{salute * 3}{l_hulk * 3}{running * 3}{r_hulk * 3}{salute * 3}{flag}\n" * 4

        await ctx.send(message)
        await ctx.message.delete(delay=2)

    @app_commands.command(**utils.alerts)
    @app_commands.describe(**utils.alerts_args)
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID))
    async def alerts(
        self,
        itx: DoomItx,
        value: typing.Literal["On", "Off"],
    ):
        value_bool = value == "On"
        query = "UPDATE users SET alertable=$1 WHERE user_id=$2;"
        await itx.client.database.execute(
            query,
            value_bool,
            itx.user.id,
        )

        await itx.response.send_message(f"Alerts set to {value}.", ephemeral=True)
        # await itx.followup.send(await itx.translate("Testing123"), ephemeral=True)

    @app_commands.command(**utils.name)
    @app_commands.describe(**utils.name_args)
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID))
    async def nickname_change(
        self,
        itx: DoomItx,
        nickname: app_commands.Range[str, 1, 25],
    ) -> None:
        await itx.response.send_message(
            f"Changing your nick name from {itx.client.all_users[itx.user.id]['nickname']} to {nickname}",
            ephemeral=True,
        )
        query = "UPDATE users SET nickname=$2 WHERE user_id=$1;"
        await itx.client.database.execute(
            query,
            itx.user.id,
            nickname,
        )
        itx.client.all_users[itx.user.id]["nickname"] = nickname

    @app_commands.command(**utils.brug_mode)
    @app_commands.describe(**utils.fun_args)
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID), discord.Object(id=968553235239559239))
    async def brug_mode(self, itx: DoomItx, text: str):
        await itx.response.send_message(utils.emojify(text)[:2000])

    @app_commands.command(**utils.uwufier)
    @app_commands.describe(**utils.fun_args)
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID), discord.Object(id=968553235239559239))
    async def uwufier(self, itx: DoomItx, text: str):
        await itx.response.send_message(utils.uwuify(text)[:2000])

    @app_commands.command(**utils.blarg)
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID), discord.Object(id=968553235239559239))
    async def blarg(self, itx: DoomItx):
        await itx.response.send_message("BLARG")

    @app_commands.command(**utils.u)
    @app_commands.describe(**utils.u_args)
    @app_commands.guilds(discord.Object(id=968553235239559239))
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
    async def _u(self, itx: DoomItx, user: discord.Member):
        insult = random.choice(itx.client.insults)
        await itx.response.send_message(f"{user.display_name}{insult}")

    @app_commands.command(**utils.u_add)
    @app_commands.describe(**utils.u_add_args)
    @app_commands.guilds(discord.Object(id=968553235239559239))
    async def _u_add(self, itx: DoomItx, insult: str):
        if itx.user.id != 703279496538619907:
            await itx.response.send_message(
                "Stop, you can't use this command noob",
                ephemeral=True,
            )
            return
        view = views.Confirm(itx)
        await itx.response.send_message(
            f"**Is this correct?**\n" f"**Preview:**\n\n" f"{itx.user.display_name}{insult}",
            ephemeral=True,
            view=view,
        )
        await view.wait()
        if not view.value:
            return
        query = "INSERT INTO insults (value) VALUES ($1);"
        await itx.client.database.execute(query, insult)
        itx.client.insults.append(insult)

    @app_commands.command(**utils.increase)
    @app_commands.guilds(discord.Object(id=968553235239559239))
    async def increase(self, itx: DoomItx):
        self.length += 1
        await itx.response.send_message(f"8{'=' * self.length}D")
        if random.random() > 0.80:
            await asyncio.sleep(2)
            await itx.edit_original_response(content=f"DICK CHOPPED...")
            self.length = 0

    @app_commands.command(**utils.decrease)
    @app_commands.guilds(discord.Object(id=968553235239559239))
    async def decrease(self, itx: DoomItx):
        if self.length > 0:
            self.length -= 1
        await itx.response.send_message(f"8{'=' * self.length}D")
        if random.random() < 0.20:
            await asyncio.sleep(2)
            await itx.edit_original_response(content=f"DICK VIAGRA TIME...")
            self.length = 50


async def setup(bot: core.Doom):
    await bot.add_cog(Personal(bot))
