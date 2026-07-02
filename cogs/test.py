from __future__ import annotations

import asyncio
import datetime
import io
import typing

import chat_exporter
import discord
from discord import app_commands
from discord.app_commands import locale_str as _T
from discord.ext import commands

import utils
from views import MAP_DATA

if typing.TYPE_CHECKING:
    import core
    from core import DoomCtx, DoomItx


class Test(commands.Cog):
    @app_commands.command()
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID))
    async def purge(
        self,
        itx: DoomItx,
        count: int,
        reason: str,
        user_to_ignore_1: discord.Member | None,
        user_to_ignore_2: discord.Member | None,
        user_to_ignore_3: discord.Member | None,
        user_to_ignore_4: discord.Member | None,
        user_to_ignore_5: discord.Member | None,
    ):
        await itx.response.send_message("Purging.", ephemeral=True)
        users = [
            user_to_ignore_1,
            user_to_ignore_2,
            user_to_ignore_3,
            user_to_ignore_4,
            user_to_ignore_5,
        ]
        ignored = [u for u in users if u]

        def check(m: discord.Message):
            return m.author not in ignored

        messages: list[discord.Message] = await itx.channel.purge(
            limit=count, check=check, before=itx.created_at, reason=reason
        )
        print(messages)
        applicable_users = set(u.author for u in messages)
        users_str = [f"{u.name} ({u.id})" for u in applicable_users]
        content = (
            f"# {len(messages)} messages purged in {itx.channel.mention}\n"
            f"**Issued by:** {itx.user}\n"
            f"**Reason:** {reason}\n"
            f"**Affected users:** {', '.join(users_str)}\n"
        )
        msg = await itx.guild.get_channel(860313850993836042).send(content)
        thread = await msg.create_thread(name=f"Deleted Messages")
        all_strings = []
        current_string = ""

        for i, message in enumerate(messages[::-1]):
            formatted = f"**{message.author.display_name}:**\n{message.content}\n\n"
            if len(current_string) + len(formatted) >= 2000 or i + 1 == len(messages):
                if i + 1 == len(messages):
                    current_string += formatted

                all_strings.append(current_string)
                current_string = ""

            current_string += formatted

        transcript = await chat_exporter.raw_export(
            itx.channel,
            messages=messages,
            bot=itx.client,
        )

        if transcript is None:
            return

        transcript_file = discord.File(
            io.BytesIO(transcript.encode()),
            filename=f"transcript-{itx.channel.name}.html",
        )
        await thread.send(
            "# This thread will never show images and some emojis among other non-text content. "
            "Use this as a quick overview.\n\n"
            "The attached file will display more information.",
            file=transcript_file,
        )
        for s in all_strings:
            await thread.send(s)

    @app_commands.command()
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID))
    async def intervene(
        self,
        itx: DoomItx,
        user: discord.Member,
        reason: str,
        user_2: discord.Member | None,
        user_3: discord.Member | None,
        user_4: discord.Member | None,
        user_5: discord.Member | None,
        user_6: discord.Member | None,
        user_7: discord.Member | None,
        user_8: discord.Member | None,
        user_9: discord.Member | None,
        user_10: discord.Member | None,
    ):

        await itx.response.send_message("Intervening.", ephemeral=True)

        all_users = [
            user,
            user_2,
            user_3,
            user_4,
            user_5,
            user_6,
            user_7,
            user_8,
            user_9,
            user_10,
        ]
        users = set(u for u in all_users if u)
        users_str = [f"{u.name} ({u.id})" for u in users]

        timeout_notice = (
            "# 🛑 Timeout Notice 🛑\n\n"
            "Hey {name},\n\n"
            "We've noticed that things got a bit heated in the conversation, and it's important for all of us to "
            "maintain a respectful and friendly environment. "
            "To ensure a cool-off period and promote positive interactions, "
            "you've been temporarily timed out from the chat.\n\n"
            "Remember, disagreements are okay, but let's keep our discussions civil and "
            "focused on understanding each other's viewpoints. Take this time to reflect, "
            "and when the timeout ends, you're welcome to rejoin the conversation with a fresh perspective.\n\n"
            "We appreciate your cooperation in creating a welcoming community for everyone.".format
        )

        for u in users:
            await u.send(timeout_notice(name=u.name))
            await u.timeout(datetime.timedelta(hours=1), reason=f"Cool off for an hour. {reason}")

        content = (
            f"# Intervened in {itx.channel.mention}\n"
            f"**Issued by:** {itx.user}\n"
            f"**Reason:** {reason}\n"
            f"**Affected users:** {', '.join(users_str)}\n"
        )
        await itx.guild.get_channel(860313850993836042).send(content)

    @commands.command()
    @commands.guild_only()
    @commands.is_owner()
    async def sync(
        self,
        ctx: DoomCtx,
        guilds: commands.Greedy[discord.Object],
        spec: typing.Literal["~", "*", "^"] | None = None,
    ) -> None:
        """
        ?sync -> global sync
        ?sync ~ -> sync current guild
        ?sync * -> copies all global app commands to current guild and syncs
        ?sync ^ -> clears all commands from the current
                        guild target and syncs (removes guild commands)
        ?sync id_1 id_2 -> syncs guilds with id 1 and 2
        >sync $ -> Clears global commands
        """
        if not guilds:
            if spec == "~":
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
            elif spec == "*":
                ctx.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await ctx.bot.tree.sync(guild=ctx.guild)
            elif spec == "^":
                ctx.bot.tree.clear_commands(guild=ctx.guild)
                await ctx.bot.tree.sync(guild=ctx.guild)
                synced = []
            elif spec == "$":
                ctx.bot.tree.clear_commands()
                await ctx.bot.tree.sync()
                synced = []
            else:
                synced = await ctx.bot.tree.sync()

            await ctx.send(f"Synced {len(synced)} commands " f"{'globally' if spec is None else 'to the current guild.'}")
            return

        ret = 0
        for guild in guilds:
            try:
                await ctx.bot.tree.sync(guild=guild)
            except discord.HTTPException:
                pass
            else:
                ret += 1

        await ctx.send(f"Synced the tree to {ret}/{len(guilds)}.")

    @commands.command()
    @commands.is_owner()
    async def xx(self, ctx: DoomCtx):
        embed = discord.Embed(
            title="Tournament Information",
            description=(
                "# Basics"
                "To be able to take part in these tournaments, "
                "use the role selector in this channel to get the roles you want for the tournament.\n"
                "You can ask any questions you have in <#698004781188382811>.\n\n"
                "At the start of each tournament, which will be announced in <#774436274542739467>, "
                "you will get **up to four** different levels that you can play to win XP from the tournament.\n"
                "- Time Attack (speedrunning easy levels)\n"
                "- Mildcore (speedrunning levels that are not too hard but not too easy)\n"
                "- Hardcore (speedrunning hard levels)\n"
                "- Bonus (speedrunning a level that isn't only about Doomfist)\n\n"
                "Click the buttons below to learn more."
            ),
        )
        await ctx.send(embed=embed)

    @commands.command()
    @commands.is_owner()
    async def log(
        self,
        ctx: DoomCtx,
        level: typing.Literal["debug", "info", "DEBUG", "INFO"],
    ):
        ctx.bot.logger.setLevel(level.upper())
        await ctx.message.delete()

    @app_commands.command(name=_T("testing123"))
    @app_commands.guilds(discord.Object(id=utils.GUILD_ID))
    # @app_commands.describe(user=_T("The user to bonk."))
    async def bonk(self, interaction: DoomItx, user: discord.User):
        await interaction.response.send_message(f":hammer: {user.mention}", ephemeral=True)
        await interaction.response.send_message


async def setup(bot: core.Doom):
    await bot.add_cog(Test(bot))
