from typing import TYPE_CHECKING

from discord.ext import commands

if TYPE_CHECKING:
    from core import Akande


class BaseCog(commands.Cog):
    def __init__(self, bot: Akande):
        self.bot = bot
