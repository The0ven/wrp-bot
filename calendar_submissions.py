"""Queue calendar submissions for approval and restore their buttons after restarts."""

from __future__ import annotations

import json
import logging
import math
import os
import uuid
from datetime import datetime
from typing import Any

import discord

from approval_views import DEFAULT_APPROVAL_USER_ID, ApprovalView, create_approval_embed
from file_locks import CONFIG_LOCK, PENDING_LOCK

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.json"
PENDING_PATH = "pending_calendars.json"
HISTORY_PATH = "history.jsonl"


class CalendarConflict(ValueError):
    """The calendar name or key is already used or awaiting approval."""


def approver_id() -> int:
    raw = os.getenv("CALENDAR_APPROVER_ID", "").strip()
    return int(raw) if raw else DEFAULT_APPROVAL_USER_ID


def current_staff_year(config_path: str = CONFIG_PATH, history_path: str = HISTORY_PATH) -> int | None:
    """The staff year as last announced by the new-year loop.

    Uses the same rounding as the "A New Year Has Dawned" post. Falls back to the whole part of
    the latest computed value when nothing has been announced yet; None when it cannot be read.
    """
    try:
        with open(config_path, mode="r", encoding="utf-8") as fh:
            calendars = json.load(fh).get("calendars") or []
        key = next(c["key"] for c in calendars if c.get("is_staff_years") is True)
        announced = latest = None
        with open(history_path, mode="r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                value = row.get(key)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or math.isnan(value):
                    continue
                latest = value
                if row.get("printed") not in (None, ""):
                    announced = value
    except (OSError, ValueError, KeyError, StopIteration, AttributeError):
        logger.warning("Could not read the current staff year", exc_info=True)
        return None
    if announced is not None:
        return int(f"{announced:.0f}")
    return math.floor(latest) if latest is not None else None


async def load_calendars() -> list[dict]:
    async with CONFIG_LOCK:
        try:
            with open(CONFIG_PATH, mode="r", encoding="utf-8") as fh:
                return list(json.load(fh).get("calendars") or [])
        except FileNotFoundError:
            return []


def _read_pending() -> dict:
    try:
        with open(PENDING_PATH, mode="r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        data = {}
    data.setdefault("pending_submissions", [])
    return data


async def load_pending() -> list[dict]:
    async with PENDING_LOCK:
        return list(_read_pending()["pending_submissions"])


def _conflict(calendar_data: dict, calendars: list[dict], pending: list[dict]) -> str | None:
    name = str(calendar_data["name"]).strip().casefold()
    key = str(calendar_data["key"]).strip().casefold()
    existing = list(calendars) + [p.get("calendar_data") or {} for p in pending]
    if any(str(c.get("name", "")).strip().casefold() == name for c in existing):
        return f"A calendar named '{calendar_data['name']}' already exists or is awaiting approval."
    if any(str(c.get("key", "")).strip().casefold() == key for c in existing):
        return f"The acronym '{calendar_data['key']}' is already used."
    return None


async def queue_calendar_submission(bot: discord.Client, calendar_data: dict, submitter_id: int,
                                    submitter_name: str, *, registration_application_id: str | None = None,
                                    registration_url: str | None = None,
                                    fallback_channel: Any = None) -> str:
    """Persist a pending calendar and send the approval DM. Returns the submission ID."""
    calendars = await load_calendars()
    submission_id = str(uuid.uuid4())
    submission: dict[str, Any] = {
        "submission_id": submission_id,
        "submitter_id": submitter_id,
        "submitter_name": submitter_name,
        "submission_timestamp": datetime.now().isoformat(),
        "calendar_data": calendar_data,
    }
    if registration_application_id:
        submission["registration_application_id"] = registration_application_id
    if registration_url:
        submission["registration_url"] = registration_url

    async with PENDING_LOCK:
        pending = _read_pending()
        problem = _conflict(calendar_data, calendars, pending["pending_submissions"])
        if problem:
            raise CalendarConflict(problem)
        pending["pending_submissions"].append(submission)
        with open(PENDING_PATH, mode="w", encoding="utf-8") as fh:
            json.dump(pending, fh, indent=2)

    await send_calendar_approval(bot, submission, fallback_channel=fallback_channel)
    return submission_id


async def pending_for_registration(application_id: str) -> dict | None:
    """A pending submission that was queued for this registration, if any."""
    for submission in await load_pending():
        if submission.get("registration_application_id") == application_id:
            return submission
    return None


async def send_calendar_approval(bot: discord.Client, submission: dict, *, fallback_channel: Any = None) -> None:
    """Send (or resend) the approval DM for an already-persisted submission."""
    submission_id = submission["submission_id"]
    calendar_data = submission["calendar_data"]
    submitter_id = int(submission["submitter_id"])
    embed = create_approval_embed(calendar_data, submitter_id, submission_id)
    if submission.get("registration_url"):
        embed.add_field(name="Nation registration", value=submission["registration_url"], inline=False)
    view = ApprovalView(submission_id, calendar_data, submitter_id)
    try:
        approver = await bot.fetch_user(approver_id())
        await approver.send(embed=embed, view=view)
    except Exception:
        logger.exception("Calendar approval DM failed submission_id=%s", submission_id)
        if fallback_channel is None:
            raise
        await fallback_channel.send(embed=embed, view=view)


async def restore_calendar_views(bot: discord.Client) -> int:
    """Re-register approval buttons for pending submissions. Returns the number restored."""
    restored = 0
    for submission in await load_pending():
        try:
            bot.add_view(ApprovalView(submission["submission_id"], submission["calendar_data"],
                                      int(submission["submitter_id"])))
            restored += 1
        except Exception:
            logger.exception("Could not restore calendar approval view submission=%s",
                             submission.get("submission_id"))
    return restored
