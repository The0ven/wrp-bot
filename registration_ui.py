"""Discord embeds, views and modals for nation registration."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Iterable

import discord

import registration_logic as logic
import registration_store as rs
from registration_logic import ActionError

logger = logging.getLogger(__name__)

DONE = "\u2705"
TODO = "\u2B1C"
WARN = "\u26A0\uFE0F"
DOT = " \u00B7 "
NONE_VALUE = "__none__"
NEW_REGION = "__new__"
CUSTOM_REGION = "__custom__"
GROUPS = ("faith", "continent")
# "continent" is the stored key; staff and members know these as Region roles.
GROUP_LABELS = {"faith": "Faith", "continent": "Region"}

STATE_LABELS = {
    rs.DRAFT: "Draft",
    rs.AWAITING_STAFF: "Awaiting staff review",
    rs.CHANGES_REQUESTED: "Changes requested",
    rs.REJECTED: "Rejected",
    rs.WITHDRAWN: "Withdrawn",
    rs.AWAITING_POPULATION: "Awaiting population",
    rs.PROVISIONING: "Setting up",
    rs.ACTIVE: "Active",
    rs.RELEASED: "Released",
}
STATE_COLOURS = {
    rs.DRAFT: discord.Colour.light_grey(),
    rs.AWAITING_STAFF: discord.Colour.blurple(),
    rs.CHANGES_REQUESTED: discord.Colour.orange(),
    rs.REJECTED: discord.Colour.red(),
    rs.WITHDRAWN: discord.Colour.dark_grey(),
    rs.AWAITING_POPULATION: discord.Colour.gold(),
    rs.PROVISIONING: discord.Colour.teal(),
    rs.ACTIVE: discord.Colour.green(),
    rs.RELEASED: discord.Colour.dark_grey(),
}
CALENDAR_STEP_LABELS = {
    "pending": "Awaiting calendar approval",
    "approved": "Approved",
    "denied": "Declined, run /register",
    "conflict": "Name or acronym taken, run /register",
    "failed": "Could not be queued; staff will retry",
    "queued": "Queued",
    "done": "Set",
}


# Helpers ---------------------------------------------------------------------

def ts(value: Any, style: str = "f") -> str:
    moment = rs.parse_iso(value) if isinstance(value, str) else value
    if not moment:
        return "-"
    return f"<t:{int(moment.timestamp())}:{style}>"


def app_data(app: rs.Application) -> dict:
    return app.approved or app.submitted or app.draft or {}


def role_mentions(ids: Iterable[int]) -> str:
    return ", ".join(f"<@&{i}>" for i in ids) or "None"


async def send_error(interaction: discord.Interaction, error: BaseException) -> None:
    if isinstance(error, ActionError):
        message = str(error)
    else:
        logger.error("Registration interaction failed", exc_info=error)
        message = "Something went wrong. Your progress is saved; please try again."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


def status_embed(app: rs.Application, settings: Any, note: str | None = None) -> discord.Embed:
    """Status card shown in threads and ephemeral replies. Never includes tracker links."""
    data = app_data(app)
    if note is None and app.state == rs.DRAFT:
        note = ("Draft in progress. The registrant can keep editing with `/register`; staff are "
                "pinged once everything is filled in and submitted.")
    embed = discord.Embed(
        title=logic.truncate(data.get("official_name") or app.nation_name or "New nation", 256),
        description=logic.truncate(note, 4000) if note else None,
        colour=STATE_COLOURS.get(app.state, discord.Colour.blurple()),
    )
    embed.add_field(name="Registrant", value=f"<@{app.member_id}>")
    embed.add_field(name="Status", value=STATE_LABELS.get(app.state, app.state))
    embed.add_field(name="Revision", value=str(app.revision))
    system = logic.SYSTEMS.get(data.get("system"))
    if system:
        embed.add_field(name="System", value=system[0])
    review = app.review or {}
    if review.get("region"):
        embed.add_field(name="Region", value=logic.truncate(review["region"], 1024))
        groups = list(review.get("faith_role_ids") or []) + list(review.get("continent_role_ids") or [])
        embed.add_field(name="Group roles", value=logic.truncate(role_mentions(groups), 1024))
    if app.population is not None:
        embed.add_field(name="Population", value=f"{app.population:,}")
        embed.add_field(name="Start year", value=str(app.start_year))
    if app.temp_role_expires_at and not app.temp_role_removed_at:
        embed.add_field(name="Temporary role expires", value=ts(app.temp_role_expires_at, "F"))
    if app.notes:
        embed.add_field(name="Staff notes", value=logic.truncate(app.notes, 1024), inline=False)
    if data.get("calendar"):
        label = logic.calendar_label(data.get("calendar"))
        step = (app.steps.get("calendar") or {}).get("status")
        if step in CALENDAR_STEP_LABELS:
            label += DOT + CALENDAR_STEP_LABELS[step]
        embed.add_field(name="Calendar", value=logic.truncate(label, 1024), inline=False)
    amendment = app.amendment or {}
    if amendment.get("status") == "pending":
        changed = ", ".join(logic.field_label(k) for k in amendment.get("fields", []))
        embed.add_field(name="Requested changes", value=logic.truncate(changed or "-", 1024), inline=False)
    failed = app.failed_steps()
    if failed:
        lines = [f"{name}: {app.steps[name].get('detail') or 'failed'}" for name in failed]
        embed.add_field(name="Needs attention", value=logic.truncate("\n".join(lines), 1024), inline=False)
    if app.state in rs.EDITABLE_STATES:
        missing = logic.missing_items(app.draft or {})
        if missing:
            shown = [f"{TODO} {item}" for item in missing[:10]]
            if len(missing) > 10:
                shown.append(f"...and {len(missing) - 10} more")
            value = "\n".join(shown)
        else:
            value = f"{DONE} Everything is filled in, ready to submit."
        embed.add_field(name="Still needed", value=logic.truncate(value, 1024), inline=False)
    embed.set_footer(text=f"Application {app.id[:8]}")
    return embed


def population_embed(app: rs.Application, settings: Any, applicant: Any, thread_url: str | None, *,
                     staff_year: int | None = None) -> discord.Embed:
    data = app_data(app)
    review = app.review or {}
    system = logic.SYSTEMS.get(data.get("system"), ("Not chosen", ""))[0]
    embed = discord.Embed(
        title=logic.truncate(f"Population needed: {app.nation_name}", 256),
        description="Staff approved this registration. Assign a starting population; the start year is "
                    "the staff year when you confirm.",
        colour=discord.Colour.gold(),
    )
    name = getattr(applicant, "name", None)
    embed.add_field(name="Applicant", value=f"<@{app.member_id}>" + (f" ({name})" if name else ""))
    embed.add_field(name="Official name", value=logic.truncate(data.get("official_name") or "-", 1024))
    embed.add_field(name="Region", value=logic.truncate(review.get("region") or "-", 1024))
    embed.add_field(name="System", value=system)
    embed.add_field(name="Staff reviewer",
                    value=f"<@{review['reviewer_id']}>" if review.get("reviewer_id") else "-")
    embed.add_field(name="Calendar", value=logic.truncate(logic.calendar_label(data.get("calendar")), 1024),
                    inline=False)
    embed.add_field(name="Start year", value=f"{staff_year} (current staff year)" if staff_year is not None
                    else f"{WARN} Staff year unavailable, you will be asked for it")
    embed.add_field(name="Thread", value=thread_url or "-", inline=False)
    embed.set_footer(text=f"Application {app.id[:8]}{DOT}Revision {app.revision}")
    return embed


def active_embed(app: rs.Application, expiry: Any, thread_url: str | None = None, *,
                 show_tracker: bool = False) -> discord.Embed:
    """Completion card. Tracker links are only for the population approver's DM."""
    data = app_data(app)
    system = logic.SYSTEMS.get(data.get("system"), ("Not chosen", ""))[0]
    embed = discord.Embed(
        title=logic.truncate(f"{app.nation_name} is registered", 256),
        colour=discord.Colour.green(),
    )
    if app.population is not None:
        embed.add_field(name="Population", value=f"{app.population:,}")
    if app.start_year is not None:
        embed.add_field(name="Start year", value=str(app.start_year))
    embed.add_field(name="System", value=system)
    if show_tracker and app.tracker_url:
        embed.add_field(name="Tracker", value=app.tracker_url, inline=False)
    if expiry:
        embed.add_field(name="Temporary role expires", value=f"{ts(expiry, 'F')} ({ts(expiry, 'R')})", inline=False)
    if thread_url:
        embed.add_field(name="Registration thread", value=thread_url, inline=False)
    return embed


# Persistent controls ------------------------------------------------------------

class RoutedView(discord.ui.View):
    """Persistent controls; the registration cog's interaction listener handles every click."""

    def __init__(self, *items: discord.ui.Item):
        super().__init__(*items, timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return False

    async def on_check_failure(self, interaction: discord.Interaction) -> None:
        return None


def _routed(label: str, style: discord.ButtonStyle, kind: str, action: str, app: rs.Application,
            emoji: str | None = None) -> discord.ui.Button:
    return discord.ui.Button(label=label, style=style, emoji=emoji,
                             custom_id=logic.make_custom_id(kind, action, app.id, app.revision))


def staff_controls(app: rs.Application) -> RoutedView:
    return RoutedView(
        _routed("Review and approve", discord.ButtonStyle.success, "staff", "review", app, DONE),
        _routed("Request changes", discord.ButtonStyle.secondary, "staff", "changes", app, "\u270F\uFE0F"),
        _routed("Reject", discord.ButtonStyle.danger, "staff", "reject", app),
    )


def population_controls(app: rs.Application) -> RoutedView:
    return RoutedView(_routed("Assign population", discord.ButtonStyle.primary, "pop", "assign", app))


def amendment_controls(app: rs.Application) -> RoutedView:
    return RoutedView(
        _routed("Approve changes", discord.ButtonStyle.success, "amend", "approve", app, DONE),
        _routed("Request changes", discord.ButtonStyle.secondary, "amend", "changes", app, "\u270F\uFE0F"),
        _routed("Decline", discord.ButtonStyle.danger, "amend", "decline", app),
    )


def _button(label: str, style: discord.ButtonStyle, callback: Callable, *, row: int,
            disabled: bool = False, emoji: str | None = None) -> discord.ui.Button:
    button = discord.ui.Button(label=label, style=style, row=row, disabled=disabled, emoji=emoji)
    button.callback = callback
    return button


# Registrant wizard ----------------------------------------------------------------

class WizardView(discord.ui.View):
    """The step-by-step registration form.

    Public forms live in the registrant's thread (only they can use the controls) and stay
    open much longer than ephemeral ones, whose interaction token expires after 15 minutes.
    """

    PUBLIC_TIMEOUT = 12 * 3600

    def __init__(self, service: Any, app_id: str, user_id: int, *, mode: str = "edit",
                 calendars: Iterable[dict] = (), pending: Iterable[dict] = (), flash: str | None = None,
                 public: bool = False):
        super().__init__(timeout=self.PUBLIC_TIMEOUT if public else 840)
        self.public = public
        self.service = service
        self.app_id = app_id
        self.user_id = user_id
        self.mode = mode
        self.calendars = list(calendars)
        self.pending = list(pending)
        self.names = logic.calendar_names(self.calendars)
        if mode == "calendar":
            self.steps = ["calendar"]
        elif mode == "amend":
            self.steps = [s for s in logic.STEPS if s != "rules"]
        else:
            self.steps = list(logic.STEPS)
        self.confirming: str | None = None
        self.flash = flash
        self.last_calendar: dict | None = None
        self.page = 0
        choice = self.data.get("calendar") or {}
        if choice.get("mode") == "existing" and choice.get("name") in self.names:
            self.page = self.names.index(choice["name"]) // 25
        self.build()

    @property
    def app(self) -> rs.Application:
        return self.service.require(self.app_id)

    @property
    def data(self) -> dict:
        return self.app.draft

    @property
    def step(self) -> str:
        if self.mode == "calendar":
            return "calendar"
        step = self.app.step
        return step if step in self.steps else self.steps[0]

    def go(self, step: str) -> None:
        self.confirming = None
        if self.mode != "calendar" and step in self.steps:
            self.service.set_position(self.app_id, step)

    def _move(self, delta: int) -> None:
        index = self.steps.index(self.step)
        self.go(self.steps[min(max(index + delta, 0), len(self.steps) - 1)])

    def advance_if_complete(self, step: str) -> None:
        if step == self.step and logic.step_complete(self.data, step) and step != self.steps[-1]:
            self._move(1)

    def missing(self) -> list[str]:
        data = self.data
        if self.mode == "amend" and not logic.diff_fields(self.app.approved or {}, data):
            return ["No changes yet"]
        return logic.missing_items(data)

    def step_done(self, step: str) -> bool:
        if step == "review":
            return not self.missing()
        return logic.step_complete(self.data, step)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user is None or interaction.user.id != self.user_id:
            await interaction.response.send_message("This form belongs to someone else.", ephemeral=True)
            return False
        return True

    async def on_error(self, error: Exception, item: discord.ui.Item, interaction: discord.Interaction) -> None:
        await send_error(interaction, error)

    async def on_timeout(self) -> None:
        if self.public and self.service.wizards.get(self.app_id) is self:
            await self.service.retire_wizard(
                self.app_id, note="This form timed out. Your progress is saved; run `/register` to reopen it.")

    # Layout -----------------------------------------------------------------

    def build(self) -> None:
        self.clear_items()
        data = self.data
        step = self.step
        if step in logic.SECTIONS:
            self.add_item(_button(f"Edit {logic.STEP_TITLES[step].lower()}", discord.ButtonStyle.primary,
                                  self._edit_section, row=0, emoji="\u270F\uFE0F"))
        elif step == "calendar":
            self._build_calendar(data)
        elif step == "system":
            current = data.get("system")
            select = discord.ui.Select(placeholder="Closed or open system", row=0, options=[
                discord.SelectOption(label=label, value=key, description=desc, default=key == current)
                for key, (label, desc) in logic.SYSTEMS.items()
            ])
            select.callback = self._pick_system
            self.add_item(select)
        elif step == "images":
            self.add_item(_button("Refresh", discord.ButtonStyle.secondary, self._refresh_images, row=0,
                                  emoji="\U0001F504"))
        elif step == "rules":
            acks = set(data.get("acknowledgements") or [])
            select = discord.ui.Select(
                placeholder="Confirm each rule", row=0, min_values=0,
                max_values=len(logic.ACKNOWLEDGEMENTS),
                options=[discord.SelectOption(label=text, value=key, default=key in acks)
                         for key, text in logic.ACKNOWLEDGEMENTS.items()],
            )
            select.callback = self._pick_rules
            self.add_item(select)
        elif step == "review":
            label = "Submit changes" if self.mode == "amend" else "Submit registration"
            if self.confirming == "submit":
                self.add_item(_button(f"Confirm: {label.lower()}", discord.ButtonStyle.success,
                                      self._confirm_submit, row=0, emoji=DONE))
                self.add_item(_button("Not yet", discord.ButtonStyle.secondary, self._keep, row=0))
            else:
                self.add_item(_button(label, discord.ButtonStyle.success, self._submit, row=0,
                                      disabled=bool(self.missing())))

        if self.confirming == "cancel":
            yes = "Discard changes" if self.mode == "amend" else "Yes, withdraw"
            self.add_item(_button(yes, discord.ButtonStyle.danger, self._confirm_cancel, row=3))
            self.add_item(_button("Keep", discord.ButtonStyle.secondary, self._keep, row=3))
        elif self.mode != "calendar":
            jump = discord.ui.Select(placeholder="Jump to a step", row=3, options=[
                discord.SelectOption(label=f"{i + 1}. {logic.STEP_TITLES[s]}", value=s,
                                     emoji=DONE if self.step_done(s) else TODO, default=s == step)
                for i, s in enumerate(self.steps)
            ])
            jump.callback = self._jump
            self.add_item(jump)

        if self.mode != "calendar":
            index = self.steps.index(step)
            self.add_item(_button("Back", discord.ButtonStyle.secondary, self._back, row=4, disabled=index == 0))
            self.add_item(_button("Continue", discord.ButtonStyle.primary, self._next, row=4,
                                  disabled=index == len(self.steps) - 1))
            self.add_item(_button("Preview", discord.ButtonStyle.secondary, self._preview, row=4))
            self.add_item(_button("Cancel", discord.ButtonStyle.danger, self._cancel, row=4))

    def _build_calendar(self, data: dict) -> None:
        names, page, pages = logic.calendar_page(self.names, self.page)
        self.page = page
        current = data.get("calendar") or {}
        if names:
            select = discord.ui.Select(
                placeholder=f"Choose an existing calendar (page {page + 1} of {pages})", row=0,
                options=[
                    discord.SelectOption(
                        label=logic.truncate(name, 100), value=str(page * 25 + i),
                        default=current.get("mode") == "existing" and current.get("name") == name)
                    for i, name in enumerate(names)
                ],
            )
            select.callback = self._pick_calendar
            self.add_item(select)
        if pages > 1:
            self.add_item(_button("Previous page", discord.ButtonStyle.secondary, self._prev_page, row=1,
                                  disabled=page == 0))
            self.add_item(_button("Next page", discord.ButtonStyle.secondary, self._next_page, row=1,
                                  disabled=page >= pages - 1))
        self.add_item(_button("Create calendar", discord.ButtonStyle.primary, self._create_calendar, row=1,
                              emoji="\u2795"))

    # Embed ------------------------------------------------------------------

    def embed(self) -> discord.Embed:
        app = self.app
        data = app.draft
        step = self.step
        heading = {"edit": "Nation registration", "amend": "Update your nation",
                   "calendar": "Choose a calendar"}.get(self.mode, "Nation registration")
        parts: list[str] = []
        if self.flash:
            parts.extend([self.flash, ""])
            self.flash = None
        parts.extend(self._step_lines(app, data, step))
        embed = discord.Embed(
            title=logic.truncate(f"{heading}: {logic.STEP_TITLES[step]}", 256),
            description=logic.truncate("\n".join(parts), 4000),
            colour=STATE_COLOURS.get(app.state, discord.Colour.blurple()),
        )
        if self.mode != "calendar":
            progress = "\n".join(f"{DONE if self.step_done(s) else TODO} {logic.STEP_TITLES[s]}"
                                 for s in self.steps)
            embed.add_field(name="Progress", value=progress, inline=False)
        if app.notes:
            embed.add_field(name="Staff notes", value=logic.truncate(app.notes, 1024), inline=False)
        index = self.steps.index(step)
        embed.set_footer(text=f"Step {index + 1} of {len(self.steps)}{DOT}Progress is saved automatically.")
        return embed

    def _step_lines(self, app: rs.Application, data: dict, step: str) -> list[str]:
        settings = self.service.settings
        lines: list[str] = []
        if step == "lore":
            total = logic.lore_length(data)
            mark = DONE if total >= logic.LORE_MIN else TODO
            lines.append(f"{mark} **{total:,}/{logic.LORE_MIN:,} characters**")
            lines.append(f"Each box holds {logic.INPUT_LIMIT:,} characters. Use the extra parts for longer lore.")
            filled = [str(i) for i in range(1, logic.LORE_PARTS + 1) if logic.clean(data.get(f"lore_{i}"))]
            lines.append(f"Parts filled: {', '.join(filled) or 'none'}")
        elif step in logic.SECTIONS:
            for f in logic.SECTIONS[step][1]:
                value = logic.clean(data.get(f.key))
                if value:
                    shown = logic.truncate(value, 150)
                else:
                    shown = "*Optional*" if not f.required else "*Not filled*"
                lines.append(f"**{f.label}**: {shown}")
        elif step == "calendar":
            lines.append(f"**Current choice**: {logic.calendar_label(data.get('calendar'))}")
            lines.append(f"Calendar guide: <#{settings.calendar_guide_channel_id}>")
            if self.mode != "calendar":
                lines.append("New calendars go to calendar approval after staff accept your nation.")
        elif step == "system":
            current = logic.SYSTEMS.get(data.get("system"), ("Not chosen", ""))[0]
            lines.append(f"**Current choice**: {current}")
            for label, desc in logic.SYSTEMS.values():
                lines.append(f"**{label}**: {desc}")
        elif step == "images":
            files = data.get("files") or {}
            for purpose, label in logic.UPLOAD_PURPOSES.items():
                record = self.service.store.get_file(files.get(purpose))
                if record:
                    shown = f"{DONE} {record.get('filename')}"
                elif purpose in logic.REQUIRED_UPLOADS:
                    shown = f"{TODO} missing"
                else:
                    shown = "*optional*"
                lines.append(f"**{label}**: {shown}")
            lines.append("")
            lines.append("Run `/registration_upload` in this thread: pick what the image shows, then attach "
                         "the file. The claim map should circle your spot with borders. City dots can be "
                         "added later.")
        elif step == "rules":
            claims = " and ".join(f"<#{c}>" for c in settings.claim_check_channel_ids)
            lines.append("**No AI.** Everything must be your own writing and art.")
            lines.append("**Languages** must be fictional; you may name a real-world equivalent.")
            lines.append(f"**Unclaimed land**: check {claims} before claiming.")
            lines.append(f"**Calendars**: see <#{settings.calendar_guide_channel_id}>.")
            acks = set(data.get("acknowledgements") or [])
            lines.append("")
            for key, text in logic.ACKNOWLEDGEMENTS.items():
                lines.append(f"{DONE if key in acks else TODO} {text}")
        elif step == "review":
            if self.mode == "amend":
                changed = logic.diff_fields(app.approved or {}, data)
                direct = [logic.field_label(k) for k in changed if k in logic.DIRECT_AMEND_KEYS]
                reviewed = [logic.field_label(k) for k in changed if k not in logic.DIRECT_AMEND_KEYS]
                lines.append(f"**Applied right away**: {', '.join(direct) or 'None'}")
                lines.append(f"**Needs staff review**: {', '.join(reviewed) or 'None'}")
                lines.append("")
            missing = self.missing()
            if missing:
                lines.append("**Still needed:**")
                lines.extend(f"{TODO} {item}" for item in missing)
            elif self.mode == "amend":
                lines.append("Ready to submit your changes.")
            else:
                lines.append("Everything is filled in. Submitting pings staff for review.")
            if self.mode == "edit":
                url = self.service.thread_url(app)
                if url:
                    lines.append(f"Your thread: {url}")
                elif missing:
                    lines.append(f"Save anything to open your draft thread in <#{settings.channel_id}>. "
                                 "Staff are only pinged when you submit.")
            if self.confirming == "submit":
                lines.append("")
                lines.append("**Submit now?**")
        return lines

    # Wiring -----------------------------------------------------------------

    async def refresh(self, interaction: discord.Interaction) -> None:
        self.build()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=self.embed(), view=self)
        else:
            await interaction.response.edit_message(embed=self.embed(), view=self)

    async def redraw(self, flash: str | None = None, step: str | None = None) -> bool:
        """Update a public form in place, e.g. after an upload made with a slash command."""
        if self.message is None or self.is_finished():
            return False
        if step:
            self.go(step)
        self.flash = flash
        self.build()
        try:
            await self.message.edit(embed=self.embed(), view=self)
            return True
        except discord.HTTPException:
            return False

    async def _finish(self, interaction: discord.Interaction, note: str | None) -> None:
        self.stop()
        if self.public:
            self.service.forget_wizard(self.app_id, self)
        await interaction.edit_original_response(
            embed=status_embed(self.app, self.service.settings, note), view=None)

    async def save(self, interaction: discord.Interaction, mutate: Callable[[dict], dict], flash: str,
                   step: str) -> None:
        self.service.save_draft(self.app_id, self.user_id, mutate, self.mode)
        self.flash = flash
        self.advance_if_complete(step)
        await self.refresh_after_save(interaction)

    async def refresh_after_save(self, interaction: discord.Interaction) -> None:
        """Refresh the wizard and keep the public draft thread in sync (never pings)."""
        if self.mode != "edit":
            await self.refresh(interaction)
            return
        if self.app.thread_id:
            await self.refresh(interaction)
            await self.service.sync_draft_thread(self.app_id)
            return
        # First save: open the thread before refreshing so the wizard can link to it.
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.service.sync_draft_thread(self.app_id)
        url = self.service.thread_url(self.app)
        if url:
            self.flash = " ".join(filter(None, [self.flash, f"Your draft thread is open: {url}"]))
        await self.refresh(interaction)

    # Step callbacks -----------------------------------------------------------

    async def _edit_section(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SectionModal(self, self.step))

    async def _pick_calendar(self, interaction: discord.Interaction) -> None:
        try:
            name = self.names[int(interaction.data["values"][0])]
        except (KeyError, IndexError, ValueError):
            raise ActionError("That calendar is no longer available. Run `/register` again.")
        await self.save_calendar(interaction, {"mode": "existing", "name": name})

    async def _prev_page(self, interaction: discord.Interaction) -> None:
        self.page -= 1
        await self.refresh(interaction)

    async def _next_page(self, interaction: discord.Interaction) -> None:
        self.page += 1
        await self.refresh(interaction)

    async def _create_calendar(self, interaction: discord.Interaction) -> None:
        prefill = self.last_calendar
        if prefill is None:
            current = self.data.get("calendar") or {}
            prefill = {}
            if current.get("mode") == "new":
                prefill = {"name": current.get("name"), "key": current.get("key"),
                           "current_year": current.get("current_year"),
                           "rate": current.get("staff_years_per_year")}
        await interaction.response.send_modal(CalendarModal(self, prefill))

    async def save_calendar(self, interaction: discord.Interaction, choice: dict) -> None:
        self.last_calendar = None
        if self.mode == "calendar":
            if not interaction.response.is_done():
                await interaction.response.defer()
            note = await self.service.replace_calendar(self.app_id, self.user_id, choice)
            await self._finish(interaction, note)
            return

        def mutate(data: dict) -> dict:
            data["calendar"] = choice
            return data

        await self.save(interaction, mutate, f"{DONE} Calendar set: {logic.calendar_label(choice)}", "calendar")

    async def _pick_system(self, interaction: discord.Interaction) -> None:
        value = interaction.data["values"][0]
        if value not in logic.SYSTEMS:
            raise ActionError("Unknown system.")

        def mutate(data: dict) -> dict:
            data["system"] = value
            return data

        await self.save(interaction, mutate, f"{DONE} {logic.SYSTEMS[value][0]} selected.", "system")

    async def _pick_rules(self, interaction: discord.Interaction) -> None:
        values = [v for v in interaction.data.get("values", []) if v in logic.ACKNOWLEDGEMENTS]

        def mutate(data: dict) -> dict:
            data["acknowledgements"] = [k for k in logic.ACKNOWLEDGEMENTS if k in values]
            return data

        done = len(values) == len(logic.ACKNOWLEDGEMENTS)
        await self.save(interaction, mutate, f"{DONE} All rules confirmed." if done else "Saved.", "rules")

    async def _refresh_images(self, interaction: discord.Interaction) -> None:
        self.advance_if_complete("images")
        await self.refresh(interaction)

    # Submit and cancel ----------------------------------------------------------

    async def _submit(self, interaction: discord.Interaction) -> None:
        self.confirming = "submit"
        await self.refresh(interaction)

    async def _confirm_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        self.confirming = None
        try:
            if self.mode == "amend":
                note = await self.service.submit_amendment(self.app_id, self.user_id)
            else:
                note = await self.service.submit(self.app_id, self.user_id)
        except ActionError as error:
            self.flash = f"{WARN} {error}"
            await self.refresh(interaction)
            return
        await self._finish(interaction, note)

    async def _cancel(self, interaction: discord.Interaction) -> None:
        self.confirming = "cancel"
        await self.refresh(interaction)

    async def _confirm_cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        self.confirming = None
        if self.mode == "amend":
            note = await self.service.discard_amendment(self.app_id, self.user_id)
        else:
            note = await self.service.withdraw(self.app_id, self.user_id)
        await self._finish(interaction, note)

    async def _keep(self, interaction: discord.Interaction) -> None:
        self.confirming = None
        await self.refresh(interaction)

    # Navigation -----------------------------------------------------------------

    async def _jump(self, interaction: discord.Interaction) -> None:
        self.go(interaction.data["values"][0])
        await self.refresh(interaction)

    async def _back(self, interaction: discord.Interaction) -> None:
        self._move(-1)
        await self.refresh(interaction)

    async def _next(self, interaction: discord.Interaction) -> None:
        self._move(1)
        await self.refresh(interaction)

    async def _preview(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, invisible=False)
        await send_preview(interaction.followup, self.service, self.data, ephemeral=True)


async def send_preview(target: Any, service: Any, data: dict, *, ephemeral: bool = False) -> None:
    """Send the rendered template, lore and images to a channel, thread or followup."""
    extra = {"ephemeral": True} if ephemeral else {}
    for i, chunk in enumerate(logic.chunk_text(logic.render_template(data), 4000)):
        embed = discord.Embed(title="Registration preview" if i == 0 else None, description=chunk,
                              colour=discord.Colour.blurple())
        await target.send(embed=embed, **extra)
    lore = logic.lore_text(data)
    for i, chunk in enumerate(logic.chunk_text(lore, 4000)):
        title = f"Lore ({logic.lore_length(data):,} characters)" if i == 0 else None
        await target.send(embed=discord.Embed(title=title, description=chunk, colour=discord.Colour.blurple()),
                          **extra)
    for purpose, file in service.files_for(data):
        await target.send(content=f"**{logic.UPLOAD_PURPOSES[purpose]}**", file=file, **extra)


# Registrant modals --------------------------------------------------------------

class SectionModal(discord.ui.Modal):
    def __init__(self, wizard: WizardView, section: str):
        super().__init__(title=logic.truncate(logic.SECTIONS[section][0], 45))
        self.wizard = wizard
        self.section = section
        data = wizard.data
        for f in logic.SECTIONS[section][1]:
            self.add_item(discord.ui.InputText(
                custom_id=f.key, label=logic.truncate(f.label, 45),
                style=discord.InputTextStyle.long if f.long else discord.InputTextStyle.short,
                placeholder=self._placeholder(f),
                # Never required here so drafts can be saved partially; submit checks completeness.
                max_length=f.max_length, required=False,
                value=(data.get(f.key) or None),
            ))

    @staticmethod
    def _placeholder(f: Any) -> str | None:
        text = f.placeholder or ""
        if f.required:
            text = f"Required to submit. {text}".strip()
        return logic.truncate(text, 100) if text else None

    async def callback(self, interaction: discord.Interaction) -> None:
        values = {child.custom_id: child.value or "" for child in self.children}
        section = self.section

        def mutate(data: dict) -> dict:
            return logic.apply_section(data, section, values)

        wizard = self.wizard
        wizard.service.save_draft(wizard.app_id, wizard.user_id, mutate, wizard.mode)
        flash = [f"{DONE} Saved."]
        if section == "lore":
            flash.append(f"Lore: {logic.lore_length(wizard.data):,}/{logic.LORE_MIN:,} characters.")
        missing = logic.section_missing(wizard.data, section)
        if missing:
            flash.append("Still needed: " + ", ".join(missing))
        wizard.flash = " ".join(flash)
        wizard.advance_if_complete(section)
        await wizard.refresh_after_save(interaction)

    async def on_error(self, error: Exception, interaction: discord.Interaction) -> None:
        await send_error(interaction, error)


class CalendarModal(discord.ui.Modal):
    def __init__(self, wizard: WizardView, prefill: dict | None = None):
        super().__init__(title="Create a calendar")
        self.wizard = wizard
        prefill = prefill or {}

        def text(key: str) -> str | None:
            value = prefill.get(key)
            return None if value in (None, "") else str(value)

        self.add_item(discord.ui.InputText(custom_id="name", label="Calendar name", max_length=100,
                                           value=text("name")))
        self.add_item(discord.ui.InputText(custom_id="key", label="Acronym", max_length=20,
                                           placeholder="e.g. AE", value=text("key")))
        self.add_item(discord.ui.InputText(custom_id="current_year", label="Current year", max_length=20,
                                           value=text("current_year")))
        self.add_item(discord.ui.InputText(custom_id="rate", label="Staff years per calendar year",
                                           max_length=20, placeholder="e.g. 1 or 0.5", value=text("rate")))

    async def callback(self, interaction: discord.Interaction) -> None:
        raw = {child.custom_id: child.value or "" for child in self.children}
        wizard = self.wizard
        choice, error = logic.validate_new_calendar(raw["name"], raw["key"], raw["current_year"], raw["rate"],
                                                    wizard.calendars, wizard.pending)
        if error:
            wizard.last_calendar = raw
            wizard.flash = f"{WARN} {error}"
            await wizard.refresh(interaction)
            return
        await wizard.save_calendar(interaction, choice)

    async def on_error(self, error: Exception, interaction: discord.Interaction) -> None:
        await send_error(interaction, error)


# Staff review ---------------------------------------------------------------------

class NewRegionModal(discord.ui.Modal):
    def __init__(self, review: "ReviewView"):
        super().__init__(title="Other region")
        self.review = review
        self.add_item(discord.ui.InputText(custom_id="region", label="Region name", max_length=100,
                                           value=review.custom_region))

    async def callback(self, interaction: discord.Interaction) -> None:
        name = logic.clean(self.children[0].value)
        if not name:
            raise ActionError("Region name cannot be empty.")
        match = next((r for r in self.review.regions if r.casefold() == name.casefold()), None)
        self.review.custom_region = match or name
        self.review.region = self.review.custom_region
        self.review._match_region_role()
        await self.review.refresh(interaction)

    async def on_error(self, error: Exception, interaction: discord.Interaction) -> None:
        await send_error(interaction, error)


def role_suffix(name: str, prefix: str) -> str:
    """'Region: Outer Csaria' -> 'outer csaria' for matching against tracker regions and religions."""
    name = logic.clean(name)
    if prefix and name.casefold().startswith(prefix.casefold()):
        name = name[len(prefix):]
    return name.strip().casefold()


class ReviewView(discord.ui.View):
    """Ephemeral staff form: tracker region plus faith and region roles.

    The region role matching the chosen tracker region, and faith roles named in the
    registrant's religions, are pre-selected; staff can change either before approving.
    """

    def __init__(self, service: Any, app_id: str, rev: int, reviewer: Any, regions: Iterable[str],
                 group_roles: dict, guild: Any):
        super().__init__(timeout=900)
        self.service = service
        self.app_id = app_id
        self.rev = rev
        self.reviewer_id = reviewer.id
        self.regions = sorted({r for r in regions if logic.clean(r)}, key=str.casefold)
        self.region: str | None = None
        self.custom_region: str | None = None
        self.roles: dict[str, list] = {}
        for group in GROUPS:
            roles = [guild.get_role(int(r)) for r in (group_roles.get(group) or [])]
            self.roles[group] = [r for r in roles if r is not None][:24]
        self.choices: dict[str, list[int] | None] = {g: ([] if not self.roles[g] else None) for g in GROUPS}
        prefixes = service.settings.group_role_prefixes
        self.prefixes = prefixes
        religions = logic.clean((service.require(app_id).submitted or {}).get("religions")).casefold()
        faith = [r.id for r in self.roles["faith"]
                 if (name := role_suffix(r.name, prefixes["faith"])) and name in religions]
        if faith:
            self.choices["faith"] = faith
        self.region_auto = True
        self.build()

    @property
    def ready(self) -> bool:
        return bool(self.region) and all(self.choices[g] is not None for g in GROUPS)

    def build(self) -> None:
        self.clear_items()
        options: list[discord.SelectOption] = []
        if self.custom_region:
            options.append(discord.SelectOption(label=logic.truncate(self.custom_region, 100), value=CUSTOM_REGION,
                                                default=self.region == self.custom_region))
        room = 25 - len(options) - 1
        for i, name in enumerate(self.regions[:room]):
            if name == self.custom_region:
                continue
            options.append(discord.SelectOption(label=logic.truncate(name, 100), value=str(i),
                                                default=self.region == name))
        options.append(discord.SelectOption(label="Other region...", value=NEW_REGION,
                                            description="Type a region name"))
        region = discord.ui.Select(placeholder="Tracker region (required)", row=0, options=options)
        region.callback = self._pick_region
        self.add_item(region)
        for row, group in enumerate(GROUPS, start=1):
            roles = self.roles[group]
            if not roles:
                continue
            chosen = self.choices[group]
            opts = [discord.SelectOption(label="None", value=NONE_VALUE, default=chosen == [])]
            opts.extend(discord.SelectOption(label=logic.truncate(r.name, 100), value=str(r.id),
                                             default=bool(chosen) and r.id in chosen) for r in roles)
            select = discord.ui.Select(placeholder=f"{GROUP_LABELS[group]} roles (required, or None)", row=row,
                                       min_values=1, max_values=len(opts), options=opts)
            select.callback = self._group_callback(group)
            self.add_item(select)
        approve = discord.ui.Button(label="Approve registration", style=discord.ButtonStyle.success, row=3,
                                    emoji=DONE, disabled=not self.ready)
        approve.callback = self._approve
        self.add_item(approve)

    def embed(self) -> discord.Embed:
        app = self.service.require(self.app_id)
        embed = discord.Embed(title=logic.truncate(f"Approve {app.nation_name}", 256),
                              colour=discord.Colour.blurple(),
                              description="Choose the tracker region. Matching region and faith roles are "
                                          "pre-selected; adjust them if needed, then approve.")
        embed.add_field(name="Region", value=logic.truncate(self.region or "Not chosen", 1024))
        religions = logic.clean((app.submitted or {}).get("religions"))
        if religions:
            embed.add_field(name="Religions (from form)", value=logic.truncate(religions, 1024), inline=False)
        for group in GROUPS:
            chosen = self.choices[group]
            if not self.roles[group]:
                value = "None configured"
            elif chosen is None:
                value = "Not chosen"
            else:
                value = role_mentions(chosen)
            embed.add_field(name=f"{GROUP_LABELS[group]} roles", value=logic.truncate(value, 1024))
        embed.add_field(name="Next", inline=False,
                        value=f"<@{self.service.settings.population_approver_id}> is asked for population.")
        return embed

    async def refresh(self, interaction: discord.Interaction) -> None:
        self.build()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user is None or interaction.user.id != self.reviewer_id:
            await interaction.response.send_message("This review form belongs to someone else.", ephemeral=True)
            return False
        return True

    async def on_error(self, error: Exception, item: discord.ui.Item, interaction: discord.Interaction) -> None:
        await send_error(interaction, error)

    async def _pick_region(self, interaction: discord.Interaction) -> None:
        value = interaction.data["values"][0]
        if value == NEW_REGION:
            await interaction.response.send_modal(NewRegionModal(self))
            return
        if value == CUSTOM_REGION:
            self.region = self.custom_region
        else:
            self.region = self.regions[int(value)]
        self._match_region_role()
        await self.refresh(interaction)

    def _match_region_role(self) -> None:
        if not self.region_auto or not self.region:
            return
        wanted = logic.clean(self.region).casefold()
        match = [r.id for r in self.roles["continent"]
                 if role_suffix(r.name, self.prefixes["continent"]) == wanted]
        if match:
            self.choices["continent"] = match[:1]
        elif self.roles["continent"]:
            self.choices["continent"] = None

    def _group_callback(self, group: str) -> Callable[[discord.Interaction], Awaitable[None]]:
        async def callback(interaction: discord.Interaction) -> None:
            values = interaction.data.get("values", [])
            if NONE_VALUE in values and len(values) > 1:
                raise ActionError("Choose None on its own, or pick roles without None.")
            self.choices[group] = [] if NONE_VALUE in values else [int(v) for v in values]
            if group == "continent":
                self.region_auto = False
            await self.refresh(interaction)
        return callback

    async def _approve(self, interaction: discord.Interaction) -> None:
        if not self.ready:
            raise ActionError("Choose a region and every group first.")
        await interaction.response.defer()
        message = await self.service.staff_approve(
            self.app_id, self.rev, interaction.user, self.region,
            self.choices["faith"] or [], self.choices["continent"] or [])
        self.stop()
        await interaction.edit_original_response(content=message, embed=None, view=None)


# Population ---------------------------------------------------------------------

class PopulationModal(discord.ui.Modal):
    def __init__(self, service: Any, app_id: str, rev: int, prefill: dict | None = None, *, edit: bool = False):
        super().__init__(title="Assign population")
        self.service = service
        self.app_id = app_id
        self.rev = rev
        self.edit = edit
        prefill = prefill or {}
        # The start year follows the staff calendar; ask for it only if that cannot be read.
        self.manual_year = bool(prefill.get("manual_year")) or service.staff_year() is None
        self.add_item(discord.ui.InputText(custom_id="population", label="Starting population", max_length=20,
                                           placeholder="e.g. 1,250,000", value=prefill.get("population") or None))
        if self.manual_year:
            self.add_item(discord.ui.InputText(custom_id="start_year", label="Start year (staff years)",
                                               max_length=10, value=prefill.get("start_year") or None))

    async def callback(self, interaction: discord.Interaction) -> None:
        raw = {child.custom_id: logic.clean(child.value) for child in self.children}
        if self.manual_year:
            raw["manual_year"] = "1"
        view = PopulationConfirmView(self.service, self.app_id, self.rev, raw)
        if self.edit:
            await interaction.response.edit_message(embed=view.embed(), view=view)
        else:
            await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

    async def on_error(self, error: Exception, interaction: discord.Interaction) -> None:
        await send_error(interaction, error)


class PopulationConfirmView(discord.ui.View):
    def __init__(self, service: Any, app_id: str, rev: int, raw: dict):
        super().__init__(timeout=600)
        self.service = service
        self.app_id = app_id
        self.rev = rev
        self.raw = raw
        self.manual_year = bool(raw.get("manual_year"))
        self.population = logic.parse_int(raw.get("population"), *logic.POPULATION_RANGE)
        if self.manual_year:
            self.start_year = logic.parse_int(raw.get("start_year"), *logic.YEAR_RANGE)
        else:
            self.start_year = service.staff_year()
        valid = self.population is not None and self.start_year is not None
        self.add_item(_button("Confirm", discord.ButtonStyle.success, self._confirm, row=0, emoji=DONE,
                              disabled=not valid))
        self.add_item(_button("Edit", discord.ButtonStyle.secondary, self._edit, row=0, emoji="\u270F\uFE0F"))

    def embed(self) -> discord.Embed:
        app = self.service.require(self.app_id)
        low, high = logic.POPULATION_RANGE
        ylow, yhigh = logic.YEAR_RANGE
        pop = f"{self.population:,}" if self.population is not None else (
            f"{WARN} '{logic.truncate(self.raw.get('population'), 30)}' must be a whole number from {low:,} to {high:,}")
        if not self.manual_year:
            year = (f"{self.start_year} (current staff year)" if self.start_year is not None
                    else f"{WARN} Staff year unavailable; press Edit to enter it")
        elif self.start_year is not None:
            year = str(self.start_year)
        else:
            year = (f"{WARN} '{logic.truncate(self.raw.get('start_year'), 30)}' must be a whole number "
                    f"from {ylow} to {yhigh}")
        embed = discord.Embed(title=logic.truncate(f"Confirm population: {app.nation_name}", 256),
                              colour=discord.Colour.gold())
        embed.add_field(name="Starting population", value=pop, inline=False)
        embed.add_field(name="Start year", value=year, inline=False)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user is None or interaction.user.id != self.service.settings.population_approver_id:
            await interaction.response.send_message("Only the population approver can do this.", ephemeral=True)
            return False
        return True

    async def on_error(self, error: Exception, item: discord.ui.Item, interaction: discord.Interaction) -> None:
        await send_error(interaction, error)

    async def _confirm(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        # Automatic years are read again at confirmation, so a year change in between is respected.
        app = await self.service.confirm_population(self.app_id, self.rev, interaction.user.id,
                                                    self.population,
                                                    self.start_year if self.manual_year else None)
        self.stop()
        if app.state == rs.ACTIVE:
            content = f"{DONE} {app.nation_name} is registered."
        else:
            failed = ", ".join(app.failed_steps()) or "setup"
            content = (f"{WARN} Population saved, but these steps need attention: {failed}. "
                       f"Staff can run `/registrations retry`.")
        await interaction.edit_original_response(content=content,
                                                 embed=status_embed(app, self.service.settings), view=None)

    async def _edit(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.send_modal(
            PopulationModal(self.service, self.app_id, self.rev, self.raw, edit=True))


# Shared ---------------------------------------------------------------------------

class ReasonModal(discord.ui.Modal):
    def __init__(self, title: str, label: str,
                 handler: Callable[[discord.Interaction, str], Awaitable[str]]):
        super().__init__(title=logic.truncate(title, 45))
        self.handler = handler
        self.add_item(discord.ui.InputText(custom_id="reason", label=logic.truncate(label, 45),
                                           style=discord.InputTextStyle.long, max_length=1000))

    async def callback(self, interaction: discord.Interaction) -> None:
        reason = logic.clean(self.children[0].value)
        if not reason:
            raise ActionError("A reason is required.")
        await interaction.response.defer(ephemeral=True, invisible=False)
        message = await self.handler(interaction, reason)
        await interaction.followup.send(message, ephemeral=True)

    async def on_error(self, error: Exception, interaction: discord.Interaction) -> None:
        await send_error(interaction, error)


class WithdrawView(discord.ui.View):
    def __init__(self, service: Any, app_id: str, user_id: int):
        super().__init__(timeout=600)
        self.service = service
        self.app_id = app_id
        self.user_id = user_id
        self.confirming = False
        self.build()

    def build(self) -> None:
        self.clear_items()
        if self.confirming:
            self.add_item(_button("Yes, withdraw", discord.ButtonStyle.danger, self._yes, row=0))
            self.add_item(_button("Keep", discord.ButtonStyle.secondary, self._keep, row=0))
        else:
            self.add_item(_button("Withdraw application", discord.ButtonStyle.danger, self._ask, row=0))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user is not None and interaction.user.id == self.user_id

    async def on_error(self, error: Exception, item: discord.ui.Item, interaction: discord.Interaction) -> None:
        await send_error(interaction, error)

    async def _ask(self, interaction: discord.Interaction) -> None:
        self.confirming = True
        self.build()
        await interaction.response.edit_message(view=self)

    async def _keep(self, interaction: discord.Interaction) -> None:
        self.confirming = False
        self.build()
        await interaction.response.edit_message(view=self)

    async def _yes(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        note = await self.service.withdraw(self.app_id, self.user_id)
        self.stop()
        await interaction.edit_original_response(
            embed=status_embed(self.service.require(self.app_id), self.service.settings, note), view=None)
