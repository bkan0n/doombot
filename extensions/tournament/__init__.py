from typing import TYPE_CHECKING

from .cog import TournamentCog

if TYPE_CHECKING:
    from core import Akande


async def setup(bot: Akande) -> None:
    await bot.add_cog(TournamentCog(bot))


async def teardown(bot: Akande) -> None:
    await bot.remove_cog("tournament")
