from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord
    from discord.ext import commands

    from core.bot import Akande

type AkandeItx = discord.Interaction[Akande]
type AkandeCtx = commands.Context[Akande]
