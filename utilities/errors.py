from discord import app_commands

__all__ = ("UserFacingError",)


class UserFacingError(app_commands.errors.AppCommandError): ...
