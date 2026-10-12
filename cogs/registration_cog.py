"""Slash commands, component routing and background work for nation registration."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

import discord
from discord.ext import commands, tasks

import calendar_submissions as cs
import registration_logic as logic
import registration_store as rs
import registration_ui as ui
from registration_logic import ActionError
from registration_service import (CALENDAR_RETRY, NO_MENTIONS, POST_APPROVAL,
                                  RegistrationService, step_status)
from registration_settings import load_settings
from registration_store import RegistrationStore
from tracker_client import TrackerClient

logger = logging.getLogger(__name__)

SETTINGS = load_settings()
GUILD_IDS = list(SETTINGS.guild_ids) or None
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
PURPOSE_CHOICES = [discord.OptionChoice(label, key) for key, label in logic.UPLOAD_PURPOSES.items()]
GROUP_CHOICES = [discord.OptionChoice(group.title(), group) for group in ui.GROUPS]
QUEUE_TITLES = {
    "review": "Awaiting staff review",
    "population": "Awaiting population",
    "attention": "Needs attention",
}
CALENDAR_FLASH = {
    "denied": "Your proposed calendar was declined. Your nation is still accepted; "
              "choose an existing calendar or propose a new one.",
    "conflict": "A calendar with that name already exists. Choose it or propose a different one.",
    "failed": "Your calendar could not be submitted for approval. Choose or propose it again.",
}
NO_PERMISSION = "You do not have permission to use this."


def is_admin(member: Any) -> bool:
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and perms.administrator)


def safe_filename(name: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("._")
    return (cleaned or "upload")[:80]


def validate_attachment(attachment: Any, max_bytes: int) -> None:
    extension = Path(attachment.filename or "").suffix.lower()
    content_type = (attachment.content_type or "").lower()
    if extension not in IMAGE_EXTENSIONS or (content_type and not content_type.startswith("image/")):
        raise ActionError("Upload a PNG, JPG, GIF or WebP image.")
    if (attachment.size or 0) > max_bytes:
        raise ActionError(f"That image is larger than {max_bytes // (1024 * 1024)} MB.")


async def nation_autocomplete(ctx: discord.AutocompleteContext) -> list[discord.OptionChoice]:
    cog = ctx.bot.get_cog("RegistrationCog")
    if cog is None or not cog.tracker.configured:
        return []
    try:
        nations = await cog.tracker.search_nations(ctx.value or "")
    except Exception:  # noqa: BLE001 - autocomplete must never raise
        logger.warning("Nation autocomplete failed", exc_info=True)
        return []
    choices = []
    for nation in nations[:25]:
        extra = nation.get("region") or "no region"
        if nation.get("isArchived"):
            extra += ", archived"
        label = logic.truncate(f"{nation.get('name')} ({extra})", 100)
        choices.append(discord.OptionChoice(label, str(nation.get("id"))))
    return choices


class RegistrationCog(commands.Cog):
    registrations = discord.SlashCommandGroup(
        "registrations", "Staff tools for nation registrations", guild_ids=GUILD_IDS)

    def __init__(self, bot: Any, settings: Any = SETTINGS, store: RegistrationStore | None = None,
                 tracker: Any = None):
        self.bot = bot
        self.settings = settings
        if store is None:
            Path(settings.db_path).resolve().parent.mkdir(parents=True, exist_ok=True)
            store = RegistrationStore(settings.db_path)
        Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
        self.store = store
        self.tracker = tracker or TrackerClient(settings.tracker_url, settings.tracker_token)
        self.service = RegistrationService(bot, self.store, settings, self.tracker)
        self._resumed = False

    def cog_unload(self) -> None:
        self.expiry_loop.cancel()
        self.store.close()

    # Registrant commands ---------------------------------------------------------

    async def _calendar_lists(self) -> tuple[list[dict], list[dict]]:
        try:
            calendars = await cs.load_calendars()
        except Exception:  # noqa: BLE001
            logger.warning("Loading calendars failed", exc_info=True)
            calendars = []
        try:
            pending = await cs.load_pending()
        except Exception:  # noqa: BLE001
            logger.warning("Loading pending calendars failed", exc_info=True)
            pending = []
        return calendars, pending

    async def send_home(self, followup: Any, app: rs.Application, user_id: int,
                        flash: str | None = None) -> None:
        """Show the registrant whatever their application needs next."""
        amendment_pending = (app.amendment or {}).get("status") == "pending"
        calendar_status = step_status(app, "calendar")
        if app.state in rs.EDITABLE_STATES:
            mode = "edit"
        elif app.state in POST_APPROVAL and calendar_status in CALENDAR_RETRY:
            mode = "calendar"
            flash = flash or CALENDAR_FLASH.get(calendar_status)
        elif app.state == rs.ACTIVE and app.source != "legacy" and not amendment_pending:
            mode = "amend"
        else:
            embed = ui.status_embed(app, self.settings, note=flash)
            if app.state in rs.WITHDRAWABLE_STATES:
                await followup.send(embed=embed, view=ui.WithdrawView(self.service, app.id, user_id),
                                    ephemeral=True)
            else:
                await followup.send(embed=embed, ephemeral=True)
            return
        calendars, pending = await self._calendar_lists()
        view = ui.WizardView(self.service, app.id, user_id, mode=mode, calendars=calendars,
                             pending=pending, flash=flash)
        await followup.send(embed=view.embed(), view=view, ephemeral=True)

    @discord.slash_command(name="register", description="Register a new nation", guild_ids=GUILD_IDS)
    async def register(self, ctx: discord.ApplicationContext) -> None:
        if ctx.guild is None:
            await ctx.respond("Use this command in the server.", ephemeral=True)
            return
        if not self.settings.enabled and not is_admin(ctx.author):
            await ctx.respond("Nation registration is not open yet.", ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        try:
            reason = await self.service.eligibility(ctx.guild.id, ctx.author)
            if reason:
                await ctx.followup.send(reason, ephemeral=True)
                return
            app = self.service.start(ctx.guild.id, ctx.author.id)
            await self.send_home(ctx.followup, app, ctx.author.id)
        except Exception as error:  # noqa: BLE001
            await ui.send_error(ctx.interaction, error)

    @discord.slash_command(name="registration_upload",
                           description="Attach a flag or map image to your nation registration",
                           guild_ids=GUILD_IDS)
    async def registration_upload(
        self,
        ctx: discord.ApplicationContext,
        purpose: discord.Option(str, "What the image shows", choices=PURPOSE_CHOICES),
        file: discord.Option(discord.Attachment, "PNG, JPG, GIF or WebP image"),
    ) -> None:
        if ctx.guild is None:
            await ctx.respond("Use this command in the server.", ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        try:
            app = await self.save_upload(ctx.guild.id, ctx.author.id, purpose, file)
            label = logic.UPLOAD_PURPOSES[purpose]
            flash = f"{ui.DONE} {label} saved."
            if app.state in rs.EDITABLE_STATES:
                had_thread = bool(app.thread_id)
                await self.service.sync_draft_thread(app.id)
                app = self.service.require(app.id)
                url = self.service.thread_url(app)
                if url and not had_thread:
                    flash += f" Your draft thread is open: {url}"
            await self.send_home(ctx.followup, app, ctx.author.id, flash=flash)
        except Exception as error:  # noqa: BLE001
            await ui.send_error(ctx.interaction, error)

    async def save_upload(self, guild_id: int, member_id: int, purpose: str, attachment: Any) -> rs.Application:
        if purpose not in logic.UPLOAD_PURPOSES:
            raise ActionError("Choose what the image shows.")
        app = self.store.live_for_member(guild_id, member_id)
        if app is None:
            raise ActionError("Start your registration with `/register` first.")
        if app.state not in rs.EDITABLE_STATES and not (app.state == rs.ACTIVE and app.source != "legacy"):
            raise ActionError("Your registration is being reviewed, so images cannot change right now.")
        validate_attachment(attachment, self.settings.max_upload_bytes)
        file_id = self.store.add_file(app.id, purpose, "", attachment.filename,
                                      attachment.content_type, attachment.size)
        folder = Path(self.settings.upload_dir) / app.id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{file_id}-{safe_filename(attachment.filename)}"
        await attachment.save(str(path))
        self.store.set_file_path(file_id, str(path))
        app = self.service.set_upload(app.id, member_id, purpose, file_id)
        self.service.set_position(app.id, "images")
        return self.service.require(app.id)

    # Persistent thread and DM buttons ---------------------------------------------

    @commands.Cog.listener("on_interaction")
    async def route_component(self, interaction: discord.Interaction) -> None:
        if interaction.type != discord.InteractionType.component:
            return
        parsed = logic.parse_custom_id((interaction.data or {}).get("custom_id"))
        if parsed is None:
            return
        kind, action, app_id, revision = parsed
        try:
            await self.handle_component(interaction, kind, action, app_id, revision)
        except Exception as error:  # noqa: BLE001
            await ui.send_error(interaction, error)

    async def _regions(self) -> list[str]:
        if not self.tracker.configured:
            return []
        try:
            return list(await self.tracker.regions())
        except Exception:  # noqa: BLE001 - staff can still enter a region by hand
            logger.warning("Loading tracker regions failed", exc_info=True)
            return []

    @staticmethod
    def _reason_modal(title: str, handler: Callable[[discord.Interaction, str], Awaitable[str]]) -> Any:
        return ui.ReasonModal(title, "Reason shown to the registrant", handler)

    async def handle_component(self, interaction: discord.Interaction, kind: str, action: str,
                               app_id: str, revision: int) -> None:
        user = interaction.user
        service = self.service
        if kind == "staff":
            app = service.check_current(app_id, rs.AWAITING_STAFF, revision)
            service._check_reviewer(app, user)
            if action == "review":
                await interaction.response.defer(ephemeral=True, invisible=False)
                view = ui.ReviewView(service, app_id, revision, user, await self._regions(),
                                     service.group_roles(), interaction.guild)
                await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)
                return
            if action in ("changes", "reject"):
                reject = action == "reject"

                async def decline(inter: discord.Interaction, reason: str) -> str:
                    return await service.staff_decline(app_id, revision, inter.user, reason, reject)

                title = "Reject registration" if reject else "Request changes"
                await interaction.response.send_modal(self._reason_modal(title, decline))
                return
        elif kind == "pop" and action == "assign":
            if user.id != self.settings.population_approver_id:
                raise ActionError("Only the population approver can assign population.")
            service.check_current(app_id, rs.AWAITING_POPULATION, revision)
            await interaction.response.send_modal(ui.PopulationModal(service, app_id, revision))
            return
        elif kind == "amend":
            app = service.check_current(app_id, rs.ACTIVE, revision)
            service._check_reviewer(app, user)
            if action == "approve":
                await interaction.response.defer(ephemeral=True, invisible=False)
                note = await service.decide_amendment(app_id, revision, user, "approve")
                await interaction.followup.send(note, ephemeral=True, allowed_mentions=NO_MENTIONS)
                return
            if action in ("changes", "decline"):

                async def decide(inter: discord.Interaction, reason: str) -> str:
                    return await service.decide_amendment(app_id, revision, inter.user, action, reason)

                title = "Decline changes" if action == "decline" else "Request changes"
                await interaction.response.send_modal(self._reason_modal(title, decide))
                return
        raise ActionError("These controls are no longer supported.")

    # Staff commands ------------------------------------------------------------------

    async def _staff_action(self, ctx: discord.ApplicationContext, work: Callable[[], Awaitable[Any]],
                            *, admin: bool = False) -> None:
        allowed = ctx.guild is not None and (
            is_admin(ctx.author) if admin else logic.is_staff(ctx.author, self.settings.staff_role_id))
        if not allowed:
            await ctx.respond(NO_PERMISSION, ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        try:
            result = await work()
            if isinstance(result, discord.Embed):
                await ctx.followup.send(embed=result, ephemeral=True)
            else:
                await ctx.followup.send(result or "Done.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        except Exception as error:  # noqa: BLE001
            await ui.send_error(ctx.interaction, error)

    def _member_app(self, guild_id: int, member: Any) -> rs.Application:
        app = self.store.live_for_member(guild_id, member.id)
        if app is None:
            raise ActionError(f"{member.mention} has no registration in progress or active.")
        return app

    def queue_embed(self, guild_id: int) -> discord.Embed:
        queue = self.service.queue(guild_id)
        embed = discord.Embed(title="Registration queue", colour=discord.Colour.blurple())
        for key, title in QUEUE_TITLES.items():
            apps = queue.get(key, [])
            lines = []
            for app in apps[:15]:
                name = discord.utils.escape_markdown(app.nation_name or "Untitled nation")
                url = self.service.thread_url(app)
                line = f"[{name}]({url})" if url else name
                line += f" - <@{app.member_id}>"
                if key == "attention":
                    failed = app.failed_steps()
                    line += " - failed: " + ", ".join(str(s) for s in failed) if failed else " - provisioning"
                lines.append(line)
            if len(apps) > 15:
                lines.append(f"...and {len(apps) - 15} more")
            embed.add_field(name=f"{title} ({len(apps)})",
                            value=logic.truncate("\n".join(lines) or "None", 1024), inline=False)
        return embed

    def roles_embed(self) -> discord.Embed:
        embed = discord.Embed(title="Registration group roles", colour=discord.Colour.blurple())
        for group, role_ids in self.service.group_roles().items():
            value = ", ".join(f"<@&{rid}>" for rid in role_ids) or "None configured"
            embed.add_field(name=group.title(), value=logic.truncate(value, 1024), inline=False)
        return embed

    @registrations.command(name="queue", description="Show registrations waiting on staff or population")
    async def reg_queue(self, ctx: discord.ApplicationContext) -> None:
        async def work() -> Any:
            return self.queue_embed(ctx.guild.id)
        await self._staff_action(ctx, work)

    @registrations.command(name="status", description="Show a member's registration")
    async def reg_status(self, ctx: discord.ApplicationContext,
                         member: discord.Option(discord.User, "Registrant")) -> None:
        async def work() -> Any:
            return ui.status_embed(self._member_app(ctx.guild.id, member), self.settings)
        await self._staff_action(ctx, work)

    @registrations.command(name="retry", description="Retry failed registration steps")
    async def reg_retry(self, ctx: discord.ApplicationContext,
                        member: discord.Option(discord.User, "Registrant")) -> None:
        async def work() -> Any:
            app = await self.service.retry(self._member_app(ctx.guild.id, member).id)
            return ui.status_embed(app, self.settings, note="Retried failed steps.")
        await self._staff_action(ctx, work)

    @registrations.command(name="resend_population", description="Resend the population request DM")
    async def reg_resend_population(self, ctx: discord.ApplicationContext,
                                    member: discord.Option(discord.User, "Registrant")) -> None:
        async def work() -> Any:
            app = self._member_app(ctx.guild.id, member)
            if app.state != rs.AWAITING_POPULATION:
                raise ActionError("That registration is not waiting for population.")
            await self.service.send_population_request(app.id)
            app = self.service.require(app.id)
            if step_status(app, "population_request") == "failed":
                return "The population request could not be delivered. Check the thread for details."
            return "Population request sent."
        await self._staff_action(ctx, work)

    @registrations.command(name="reopen_review", description="Post fresh staff review controls")
    async def reg_reopen_review(self, ctx: discord.ApplicationContext,
                                member: discord.Option(discord.User, "Registrant")) -> None:
        async def work() -> Any:
            return await self.service.reopen_review(self._member_app(ctx.guild.id, member).id)
        await self._staff_action(ctx, work)

    @registrations.command(name="withdraw", description="Withdraw a member's unfinished registration")
    async def reg_withdraw(self, ctx: discord.ApplicationContext,
                           member: discord.Option(discord.User, "Registrant")) -> None:
        async def work() -> Any:
            app = self._member_app(ctx.guild.id, member)
            return await self.service.withdraw(app.id, ctx.author.id, by_staff=True)
        await self._staff_action(ctx, work)

    @registrations.command(name="link", description="Link a member to an existing tracker nation")
    async def reg_link(self, ctx: discord.ApplicationContext,
                       member: discord.Option(discord.User, "Player"),
                       nation: discord.Option(str, "Tracker nation", autocomplete=nation_autocomplete)) -> None:
        async def work() -> Any:
            app = await self.service.link_existing(ctx.guild.id, member.id, nation, ctx.author)
            return ui.status_embed(app, self.settings, note="Linked to the tracker nation.")
        await self._staff_action(ctx, work)

    @registrations.command(name="release", description="Release a member's nation so they can register again")
    async def reg_release(self, ctx: discord.ApplicationContext,
                          member: discord.Option(discord.User, "Player")) -> None:
        async def work() -> Any:
            return await self.service.release(ctx.guild.id, member.id, ctx.author)
        await self._staff_action(ctx, work)

    @registrations.command(name="roles_add", description="Allow a faith or continent role in staff review")
    async def reg_roles_add(self, ctx: discord.ApplicationContext,
                            group: discord.Option(str, "Role group", choices=GROUP_CHOICES),
                            role: discord.Option(discord.Role, "Role to allow")) -> None:
        async def work() -> Any:
            self.service.add_group_role(group, role.id)
            return f"Added {role.mention} to the {group} roles."
        await self._staff_action(ctx, work, admin=True)

    @registrations.command(name="roles_remove", description="Remove a faith or continent role from staff review")
    async def reg_roles_remove(self, ctx: discord.ApplicationContext,
                               group: discord.Option(str, "Role group", choices=GROUP_CHOICES),
                               role: discord.Option(discord.Role, "Role to remove")) -> None:
        async def work() -> Any:
            if self.service.remove_group_role(group, role.id):
                return f"Removed {role.mention} from the {group} roles."
            return f"{role.mention} was not one of the {group} roles."
        await self._staff_action(ctx, work, admin=True)

    @registrations.command(name="roles_list", description="List the faith and continent roles staff can grant")
    async def reg_roles_list(self, ctx: discord.ApplicationContext) -> None:
        async def work() -> Any:
            return self.roles_embed()
        await self._staff_action(ctx, work, admin=True)

    # Background work -------------------------------------------------------------------

    @tasks.loop(minutes=1)
    async def expiry_loop(self) -> None:
        try:
            removed = await self.service.expire_temp_roles()
            if removed:
                logger.info("Removed %d expired temporary registration roles", removed)
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("Temporary role expiry check failed")

    @expiry_loop.before_loop
    async def _before_expiry(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self.expiry_loop.is_running():
            self.expiry_loop.start()
        if self._resumed:
            return
        self._resumed = True
        try:
            restored = await cs.restore_calendar_views(self.bot)
            logger.info("Restored %s calendar approval views", restored)
        except Exception:  # noqa: BLE001
            logger.exception("Restoring calendar approval views failed")
        try:
            await self.service.resume()
        except Exception:  # noqa: BLE001
            logger.exception("Resuming registrations failed")

    @commands.Cog.listener()
    async def on_calendar_decision(self, submission_id: str, status: str, calendar_data: dict) -> None:
        try:
            await self.service.on_calendar_decision(submission_id, status, calendar_data)
        except Exception:  # noqa: BLE001
            logger.exception("Handling calendar decision %s failed", submission_id)


def setup(bot: Any) -> None:
    bot.add_cog(RegistrationCog(bot))
