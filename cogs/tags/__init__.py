from __future__ import annotations

from typing import TYPE_CHECKING

from cogs.tags.tags import Tags

if TYPE_CHECKING:
    from core import Doom


async def setup(bot: Doom):
    await bot.add_cog(Tags(bot))
