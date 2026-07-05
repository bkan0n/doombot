from __future__ import annotations

import datetime
import io
import itertools
import typing

import discord
from discord import app_commands, ui
from discord.ext import commands
from sqlspec.exceptions import UniqueViolationError

from utilities import views
from utilities.errors import UserFacingError

from .._base import BaseCog
from . import naming
from .views import TagEditModal, TagMakeModal

if typing.TYPE_CHECKING:
    from core import Akande, AkandeCtx, AkandeItx
    from database import Services
    from database.services.tags import Tag

_MENTIONS = discord.AllowedMentions.none()


async def _autocomplete_all(
    itx: AkandeItx, current: str
) -> list[app_commands.Choice[str]]:
    assert itx.guild_id
    async with itx.client.acquire() as svc:
        names = await svc.tags.autocomplete_tags_with_aliases(
            itx.guild_id, current.lower()
        )
    return [app_commands.Choice(name=n, value=n) for n in names]


async def _autocomplete_originals(
    itx: AkandeItx, current: str
) -> list[app_commands.Choice[str]]:
    assert itx.guild_id
    async with itx.client.acquire() as svc:
        names = await svc.tags.autocomplete_tags(itx.guild_id, current.lower())
    return [app_commands.Choice(name=n, value=n) for n in names]


async def _autocomplete_owned(
    itx: AkandeItx, current: str
) -> list[app_commands.Choice[str]]:
    assert itx.guild_id
    async with itx.client.acquire() as svc:
        names = await svc.tags.autocomplete_owned_tags(
            itx.guild_id, itx.user.id, current.lower()
        )
    return [app_commands.Choice(name=n, value=n) for n in names]


async def _autocomplete_owned_all(
    itx: AkandeItx, current: str
) -> list[app_commands.Choice[str]]:
    assert itx.guild_id
    async with itx.client.acquire() as svc:
        names = await svc.tags.autocomplete_owned_tags_with_aliases(
            itx.guild_id, itx.user.id, current.lower()
        )
    return [app_commands.Choice(name=n, value=n) for n in names]


def _can_moderate(itx: AkandeItx) -> bool:
    assert isinstance(itx.user, discord.Member)
    staff_role = itx.client.config.roles.staff
    return itx.user.guild_permissions.manage_messages or any(
        role.id == staff_role for role in itx.user.roles
    )


class TagsCog(BaseCog, name="tags", description="Tag text for later retrieval."):
    """Tags"""

    def __init__(self, bot: Akande) -> None:
        super().__init__(bot)
        # guild_id -> names currently being made via modal
        self._in_progress: dict[int, set[str]] = {}

    # -- helpers -----------------------------------------------------------

    @staticmethod
    async def _get_tag_or_suggest(svc: Services, location_id: int, name: str) -> Tag:
        tag = await svc.tags.fetch_tag(location_id, name)
        if tag is not None:
            return tag
        similar = await svc.tags.search_similar_tag_names(location_id, name)
        if similar:
            raise UserFacingError(
                "Tag not found. Did you mean...\n" + "\n".join(similar)
            )
        raise UserFacingError("Tag not found.")

    def _reserved(self) -> frozenset[str]:
        return frozenset(command.name for command in self.tag.app_command.commands)

    def _is_in_progress(self, guild_id: int, name: str) -> bool:
        return name in self._in_progress.get(guild_id, set())

    async def _create_tag(self, itx: AkandeItx, name: str, content: str) -> None:
        """Shared by /tag create and the make modal. Responds on success."""
        assert itx.guild_id
        name = naming.validate_tag_name(name, self._reserved())
        if self._is_in_progress(itx.guild_id, name):
            raise UserFacingError("This tag is currently being made by someone else.")
        async with itx.client.acquire() as svc:
            if await svc.tags.tag_exists(itx.guild_id, name):
                raise UserFacingError("This tag already exists.")
            try:
                await svc.tags.create_tag(name, content, itx.user.id, itx.guild_id)
            except UniqueViolationError:
                raise UserFacingError("This tag already exists.") from None
        await itx.response.send_message(
            f"Tag `{name}` successfully created.", ephemeral=True
        )

    # -- commands ----------------------------------------------------------

    @commands.hybrid_group(
        name="tag", fallback="get", description="Tag text for later retrieval"
    )
    @commands.guild_only()
    @app_commands.guild_only()
    @app_commands.describe(name="The tag to retrieve")
    @app_commands.autocomplete(name=_autocomplete_all)
    async def tag(self, ctx: AkandeCtx, *, name: str) -> None:
        """Retrieve a tag's content."""
        assert ctx.guild
        name = name.strip().lower()
        async with ctx.bot.acquire() as svc:
            tag = await self._get_tag_or_suggest(svc, ctx.guild.id, name)
            await svc.tags.increment_tag_uses(tag.name, ctx.guild.id)
        await ctx.send(tag.content, allowed_mentions=_MENTIONS)

    @tag.app_command.command(name="create", description="Create a new tag owned by you")
    @app_commands.describe(name="The tag name", content="The tag content")
    async def create(
        self,
        itx: AkandeItx,
        name: app_commands.Range[str, 1, 100],
        content: app_commands.Range[str, 1, 2000],
    ) -> None:
        await self._create_tag(itx, name, content)

    @tag.app_command.command(
        name="make", description="Interactively create a tag via a form"
    )
    async def make(self, itx: AkandeItx) -> None:
        assert itx.guild_id
        guild_id = itx.guild_id

        async def submit(modal_itx: AkandeItx, name: str, content: str) -> None:
            normalized = name.strip().lower()
            self._in_progress.setdefault(guild_id, set()).add(normalized)
            try:
                await self._create_tag(modal_itx, name, content)
            finally:
                self._in_progress.get(guild_id, set()).discard(normalized)

        await itx.response.send_modal(TagMakeModal(submit))

    @tag.app_command.command(name="edit", description="Edit a tag you own")
    @app_commands.describe(
        name="The tag to edit",
        content="New content; omit to edit in a form",
    )
    @app_commands.autocomplete(name=_autocomplete_owned)
    async def edit(
        self,
        itx: AkandeItx,
        name: str,
        content: app_commands.Range[str, 1, 2000] | None = None,
    ) -> None:
        assert itx.guild_id
        guild_id = itx.guild_id
        name = name.strip().lower()

        async def apply(target_itx: AkandeItx, new_content: str) -> None:
            async with target_itx.client.acquire() as svc:
                updated = await svc.tags.update_tag_content(
                    new_content, name, guild_id, target_itx.user.id
                )
            if not updated:
                raise UserFacingError(
                    "Could not edit that tag. Are you sure it exists and you own it?"
                )
            await target_itx.response.send_message(
                "Successfully edited tag.", ephemeral=True
            )

        if content is not None:
            await apply(itx, content)
            return
        async with itx.client.acquire() as svc:
            current = await svc.tags.fetch_owned_tag_content(
                name, guild_id, itx.user.id
            )
        if current is None:
            raise UserFacingError(
                "Could not find a tag with that name, are you sure it exists "
                "or you own it?"
            )
        await itx.response.send_modal(TagEditModal(current, apply))

    @tag.app_command.command(
        name="alias", description="Create an alias for an existing tag"
    )
    @app_commands.describe(
        new_name="The name of the alias", old_name="The original tag to alias"
    )
    @app_commands.rename(new_name="aliased-name", old_name="original-tag")
    @app_commands.autocomplete(old_name=_autocomplete_originals)
    async def alias(
        self,
        itx: AkandeItx,
        new_name: app_commands.Range[str, 1, 100],
        old_name: app_commands.Range[str, 1, 100],
    ) -> None:
        assert itx.guild_id
        new_name = naming.validate_tag_name(new_name, self._reserved())
        async with itx.client.acquire() as svc:
            try:
                inserted = await svc.tags.create_tag_alias(
                    new_name, old_name.strip().lower(), itx.guild_id, itx.user.id
                )
            except UniqueViolationError:
                raise UserFacingError("A tag with this name already exists.") from None
        if not inserted:
            raise UserFacingError(
                f'A tag with the name of "{old_name}" does not exist.'
            )
        await itx.response.send_message(
            f"Tag alias `{new_name}` that points to `{old_name}` created.",
            ephemeral=True,
        )

    @tag.app_command.command(name="remove", description="Remove a tag you own")
    @app_commands.describe(name="The tag to remove")
    @app_commands.autocomplete(name=_autocomplete_owned_all)
    async def remove(self, itx: AkandeItx, name: str) -> None:
        assert itx.guild_id
        name = name.strip().lower()
        bypass = _can_moderate(itx)
        async with itx.client.acquire() as svc:
            if bypass:
                tag_id = await svc.tags.delete_tag_lookup(name, itx.guild_id)
            else:
                tag_id = await svc.tags.delete_tag_lookup_owned(
                    name, itx.guild_id, itx.user.id
                )
            if tag_id is None:
                raise UserFacingError(
                    "Could not delete tag. Either it does not exist or you do "
                    "not have permission."
                )
            if bypass:
                deleted = await svc.tags.delete_tag(tag_id, name, itx.guild_id)
            else:
                deleted = await svc.tags.delete_tag_owned(
                    tag_id, name, itx.guild_id, itx.user.id
                )
        message = (
            "Tag and corresponding aliases successfully deleted."
            if deleted
            else "Tag alias successfully deleted."
        )
        await itx.response.send_message(message, ephemeral=True)

    @tag.app_command.command(
        name="remove-id", description="Remove a tag by its internal ID"
    )
    @app_commands.describe(tag_id="The internal tag ID to delete")
    @app_commands.rename(tag_id="id")
    async def remove_id(self, itx: AkandeItx, tag_id: int) -> None:
        assert itx.guild_id
        bypass = _can_moderate(itx)
        async with itx.client.acquire() as svc:
            if bypass:
                real_id = await svc.tags.delete_tag_lookup_by_id(tag_id, itx.guild_id)
            else:
                real_id = await svc.tags.delete_tag_lookup_by_id_owned(
                    tag_id, itx.guild_id, itx.user.id
                )
            if real_id is None:
                raise UserFacingError(
                    "Could not delete tag. Either it does not exist or you do "
                    "not have permission."
                )
            if bypass:
                deleted = await svc.tags.delete_tag_by_id(real_id, itx.guild_id)
            else:
                deleted = await svc.tags.delete_tag_by_id_owned(
                    real_id, itx.guild_id, itx.user.id
                )
        message = (
            "Tag and corresponding aliases successfully deleted."
            if deleted
            else "Tag alias successfully deleted."
        )
        await itx.response.send_message(message, ephemeral=True)

    @tag.app_command.command(
        name="info", description="Info about a tag: owner, uses, rank"
    )
    @app_commands.describe(name="The tag to retrieve information for")
    @app_commands.autocomplete(name=_autocomplete_all)
    async def info(self, itx: AkandeItx, name: str) -> None:
        assert itx.guild_id
        await itx.response.defer(ephemeral=True)
        async with itx.client.acquire() as svc:
            record = await svc.tags.fetch_tag_info(name.strip().lower(), itx.guild_id)
            rank = (
                await svc.tags.fetch_tag_rank(record.id)
                if record is not None and not record.is_alias
                else None
            )
        if record is None:
            raise UserFacingError("Tag not found.")
        created_at = record.lookup_created_at
        if created_at.tzinfo is None:  # column is a naive timestamp
            created_at = created_at.replace(tzinfo=datetime.UTC)
        created = discord.utils.format_dt(created_at, style="R")
        if record.is_alias:
            body = (
                f"### {record.lookup_name}\n"
                f"**Alias of:** {record.name}\n"
                f"**Owner:** <@{record.lookup_owner_id}>\n"
                f"**Created:** {created}"
            )
        else:
            body = (
                f"### {record.name}\n"
                f"**Owner:** <@{record.owner_id}>\n"
                f"**Uses:** {record.uses}\n"
                f"**Rank:** {rank}\n"
                f"**Created:** {created}"
            )
        await itx.edit_original_response(view=views.Card([body]))

    @tag.app_command.command(
        name="raw", description="Raw, markdown-escaped tag content"
    )
    @app_commands.describe(name="The tag to retrieve raw content for")
    @app_commands.autocomplete(name=_autocomplete_originals)
    async def raw(self, itx: AkandeItx, name: str) -> None:
        assert itx.guild_id
        async with itx.client.acquire() as svc:
            tag = await self._get_tag_or_suggest(
                svc, itx.guild_id, name.strip().lower()
            )
        escaped = discord.utils.escape_markdown(tag.content).replace("<", "\\<")
        if len(escaped) > 2000:
            buffer = io.BytesIO(escaped.encode())
            await itx.response.send_message(
                file=discord.File(buffer, filename="tag_content.txt")
            )
            return
        await itx.response.send_message(escaped, allowed_mentions=_MENTIONS)

    @tag.app_command.command(name="random", description="Display a random tag")
    async def random(self, itx: AkandeItx) -> None:
        assert itx.guild_id
        async with itx.client.acquire() as svc:
            tag = await svc.tags.fetch_random_tag(itx.guild_id)
        if tag is None:
            raise UserFacingError("This server has no tags.")
        await itx.response.send_message(
            f"Random tag found: `{tag.name}`\n{tag.content}",
            allowed_mentions=_MENTIONS,
        )

    @staticmethod
    def _entry_pages(
        entries: list, header: str, per_page: int = 20
    ) -> list[list[str | ui.Item]]:
        return [
            [header, *(f"{entry.name} (ID: {entry.id})" for entry in chunk)]
            for chunk in itertools.batched(entries, per_page)
        ]

    @tag.app_command.command(
        name="list", description="List tags owned by you or someone else"
    )
    @app_commands.describe(member="Whose tags to list (defaults to you)")
    async def list_(self, itx: AkandeItx, member: discord.Member | None = None) -> None:
        assert itx.guild_id
        target = member or itx.user
        await itx.response.defer(ephemeral=True)
        async with itx.client.acquire() as svc:
            rows = await svc.tags.fetch_owned_tag_list(itx.guild_id, target.id)
        if not rows:
            raise UserFacingError(f"{target.display_name} has no tags.")
        pages = self._entry_pages(rows, f"### Tags — {target.display_name}")
        await views.Paginator(itx, pages).start()

    @tag.app_command.command(name="all", description="List every tag in this server")
    @app_commands.describe(text_file="Dump all tags as a text file instead")
    async def all_(self, itx: AkandeItx, text_file: bool = False) -> None:
        assert itx.guild_id
        await itx.response.defer(ephemeral=True)
        if text_file:
            async with itx.client.acquire() as svc:
                rows = await svc.tags.fetch_all_tags_dump(
                    itx.guild_id, _can_moderate(itx), itx.user.id
                )
            if not rows:
                raise UserFacingError("This server has no tags.")
            table = naming.render_table(
                ["id", "name", "owner_id", "uses", "can_delete", "is_alias"],
                [
                    [r.id, r.name, r.owner_id, r.uses, r.can_delete, r.is_alias]
                    for r in rows
                ],
            )
            buffer = io.BytesIO(table.encode())
            await itx.edit_original_response(
                attachments=[discord.File(buffer, filename="tags.txt")]
            )
            return
        async with itx.client.acquire() as svc:
            rows = await svc.tags.fetch_tag_list(itx.guild_id)
        if not rows:
            raise UserFacingError("This server has no tags.")
        await views.Paginator(itx, self._entry_pages(rows, "### All Tags")).start()

    @tag.app_command.command(name="search", description="Search tags by name")
    @app_commands.describe(query="The tag name to search for (min 3 characters)")
    async def search(
        self, itx: AkandeItx, query: app_commands.Range[str, 3, 100]
    ) -> None:
        assert itx.guild_id
        await itx.response.defer(ephemeral=True)
        async with itx.client.acquire() as svc:
            rows = await svc.tags.search_tags(itx.guild_id, query)
        if not rows:
            raise UserFacingError("No tags found.")
        pages = self._entry_pages(rows, f"### Tag Search — {query}")
        await views.Paginator(itx, pages).start()

    @tag.app_command.command(
        name="purge", description="Remove all tags owned by a member"
    )
    @app_commands.describe(member="The member whose tags to purge")
    async def purge(self, itx: AkandeItx, member: discord.User) -> None:
        assert itx.guild_id
        if not _can_moderate(itx):
            raise UserFacingError("You need Manage Messages to purge tags.")
        await itx.response.defer(ephemeral=True)
        async with itx.client.acquire() as svc:
            count = await svc.tags.count_owned_tags(itx.guild_id, member.id)
        if count == 0:
            raise UserFacingError(f"{member} does not have any tags to purge.")
        confirmed = await views.Confirm.prompt(
            itx,
            f"This will delete **{count}** tag(s) owned by {member.mention}.\n"
            "**This action cannot be reversed.**",
            defer_on_confirm=True,
        )
        if not confirmed:
            return
        async with itx.client.acquire() as svc:
            await svc.tags.purge_owned_tags(itx.guild_id, member.id)
        await itx.edit_original_response(
            view=views.Card([f"Removed all {count} tag(s) belonging to {member}."])
        )

    @tag.app_command.command(
        name="claim", description="Claim a tag whose owner left the server"
    )
    @app_commands.describe(tag="The tag to claim")
    @app_commands.autocomplete(tag=_autocomplete_all)
    async def claim(self, itx: AkandeItx, tag: str) -> None:
        assert itx.guild_id and itx.guild
        name = tag.strip().lower()
        await itx.response.defer(ephemeral=True)
        alias = False
        async with itx.client.acquire() as svc:
            row = await svc.tags.fetch_tag_owner(itx.guild_id, name)
            if row is None:
                lookup = await svc.tags.fetch_tag_lookup_owner(itx.guild_id, name)
                if lookup is None:
                    raise UserFacingError(
                        f'A tag with the name of "{tag}" does not exist.'
                    )
                alias = True
                owner_id, tag_id = lookup.owner_id, lookup.tag_id
            else:
                owner_id, tag_id = row.owner_id, row.id
            member = itx.guild.get_member(owner_id)
            if member is None:
                try:
                    member = await itx.guild.fetch_member(owner_id)
                except discord.NotFound:
                    member = None
            if member is not None:
                raise UserFacingError("Tag owner is still in the server.")
            if not alias:
                await svc.tags.set_tag_owner(tag_id, itx.user.id)
            await svc.tags.set_tag_lookup_owner(tag_id, itx.user.id)
        await itx.edit_original_response(
            view=views.Card(["Successfully transferred tag ownership to you."])
        )

    @tag.app_command.command(
        name="transfer", description="Transfer a tag you own to a member"
    )
    @app_commands.describe(member="The member to transfer to", tag="The tag")
    @app_commands.autocomplete(tag=_autocomplete_originals)
    async def transfer(self, itx: AkandeItx, member: discord.Member, tag: str) -> None:
        assert itx.guild_id
        if member.bot:
            raise UserFacingError("You cannot transfer a tag to a bot.")
        name = tag.strip().lower()
        await itx.response.defer(ephemeral=True)
        async with itx.client.acquire() as svc:
            row = await svc.tags.fetch_tag_owner(itx.guild_id, name)
            if row is None or row.owner_id != itx.user.id:
                raise UserFacingError(
                    f'A tag with the name of "{tag}" does not exist or is not '
                    "owned by you."
                )
            await svc.tags.set_tag_owner(row.id, member.id)
            await svc.tags.set_tag_lookup_owner(row.id, member.id)
        await itx.edit_original_response(
            view=views.Card([f"Transferred tag ownership to {member.mention}."])
        )
