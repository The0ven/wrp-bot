import asyncio
import discord
from discord import Button, ButtonStyle
from discord.ui import View, button
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
import logging
import os
from file_locks import CONFIG_LOCK, PENDING_LOCK

logger = logging.getLogger(__name__)
DEFAULT_APPROVAL_USER_ID = 322487124102479873

def calendar_rate_label(calendar_data: Dict[str, Any]) -> str:
    if "staff_years_per_year" in calendar_data:
        return str(calendar_data["staff_years_per_year"])
    if "hours_per_year" in calendar_data:
        return f"legacy hours={calendar_data['hours_per_year']}"
    return "unknown"

class ApprovalView(View):
    def __init__(self, submission_id: str, calendar_data: Dict[str, Any], submitter_id: int):
        super().__init__(timeout=None)  # No timeout for approval buttons
        self.submission_id = submission_id
        self.calendar_data = calendar_data
        self.submitter_id = submitter_id
        # Stable custom IDs let the bot re-register these buttons after a restart.
        for item, action in ((self.approve_calendar, "approve"), (self.deny_calendar, "deny")):
            item.custom_id = f"wrpcal:{action}:{submission_id}"
            item._provided_custom_id = True
        logger.info(
            "Initialized ApprovalView submission_id=%s submitter_id=%s calendar_name=%s",
            submission_id,
            submitter_id,
            calendar_data.get("name"),
        )

    @button(label="✅ Approve", style=ButtonStyle.success)
    async def approve_calendar(self, button: Button, interaction: discord.Interaction):
        # Check if user has permission to approve (moderate_members or higher)
        if not self._can_review_submission(interaction):
            logger.warning(
                "Approve denied for missing permissions submission_id=%s user_id=%s",
                self.submission_id,
                interaction.user.id,
            )
            await interaction.response.send_message("You don't have permission to approve calendar submissions.", ephemeral=True)
            return

        try:
            logger.info(
                "Approve started submission_id=%s approver_id=%s calendar_name=%s",
                self.submission_id,
                interaction.user.id,
                self.calendar_data.get("name"),
            )
            # Lock config read-modify-write to avoid concurrent approvals clobbering each other.
            async with CONFIG_LOCK:
                with open("config.json", mode="r", encoding="utf-8") as rb:
                    config = json.load(rb)
                
                # Remove any existing calendar with the same name
                previous_count = len(config["calendars"])
                config["calendars"] = [cal for cal in config["calendars"] if cal["name"] != self.calendar_data["name"]]
                
                # Add the approved calendar
                config["calendars"].append(self.calendar_data)
                logger.info(
                    "Approve updated config submission_id=%s calendars_before=%s calendars_after=%s",
                    self.submission_id,
                    previous_count,
                    len(config["calendars"]),
                )
                
                with open("config.json", mode="w", encoding="utf-8") as wb:
                    json.dump(config, wb, separators=(',', ':'))
                logger.info("Approve wrote config submission_id=%s", self.submission_id)
            
            # Remove from pending submissions
            await self._remove_from_pending()
            
            # Update the approval message
            embed = discord.Embed(
                title="✅ Calendar Approved",
                description=f"**{self.calendar_data['name']}** has been approved and added to the system.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Calendar Details", value=self._format_calendar_details(), inline=False)
            embed.add_field(name="Approved by", value=interaction.user.mention, inline=True)
            
            await interaction.response.edit_message(embed=embed, view=None)
            logger.info("Approve interaction message updated submission_id=%s", self.submission_id)
            
            # Notify the submitter
            await self._notify_submitter(interaction.client, "approved")
            self._dispatch_decision(interaction.client, "approved")
            logger.info("Approve flow complete submission_id=%s", self.submission_id)
            
        except Exception as e:
            logger.exception("Approve failed submission_id=%s", self.submission_id)
            await interaction.response.send_message(f"Error approving calendar: {str(e)}", ephemeral=True)

    @button(label="❌ Deny", style=ButtonStyle.danger)
    async def deny_calendar(self, button: Button, interaction: discord.Interaction):
        # Check if user has permission to deny (moderate_members or higher)
        if not self._can_review_submission(interaction):
            logger.warning(
                "Deny denied for missing permissions submission_id=%s user_id=%s",
                self.submission_id,
                interaction.user.id,
            )
            await interaction.response.send_message("You don't have permission to deny calendar submissions.", ephemeral=True)
            return

        try:
            logger.info(
                "Deny started submission_id=%s reviewer_id=%s calendar_name=%s",
                self.submission_id,
                interaction.user.id,
                self.calendar_data.get("name"),
            )
            # Remove from pending submissions
            await self._remove_from_pending()
            
            # Update the denial message
            embed = discord.Embed(
                title="❌ Calendar Denied",
                description=f"**{self.calendar_data['name']}** has been denied and will not be added to the system.",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Calendar Details", value=self._format_calendar_details(), inline=False)
            embed.add_field(name="Denied by", value=interaction.user.mention, inline=True)
            
            await interaction.response.edit_message(embed=embed, view=None)
            logger.info("Deny interaction message updated submission_id=%s", self.submission_id)
            
            # Notify the submitter
            await self._notify_submitter(interaction.client, "denied")
            self._dispatch_decision(interaction.client, "denied")
            logger.info("Deny flow complete submission_id=%s", self.submission_id)
            
        except Exception as e:
            logger.exception("Deny failed submission_id=%s", self.submission_id)
            await interaction.response.send_message(f"Error denying calendar: {str(e)}", ephemeral=True)

    def _dispatch_decision(self, client: discord.Client, status: str) -> None:
        """Let other cogs (nation registration) react to calendar decisions."""
        dispatch = getattr(client, "dispatch", None)
        # Client.dispatch is synchronous; skip async test doubles.
        if dispatch is None or asyncio.iscoroutinefunction(dispatch):
            return
        try:
            dispatch("calendar_decision", self.submission_id, status, self.calendar_data)
        except Exception:
            logger.exception("Dispatching calendar_decision failed submission_id=%s", self.submission_id)

    async def _remove_from_pending(self):
        """Remove the submission from pending_calendars.json"""
        try:
            async with PENDING_LOCK:
                with open("pending_calendars.json", mode="r", encoding="utf-8") as rb:
                    pending_data = json.load(rb)
                
                # Remove the submission with matching ID
                previous_count = len(pending_data["pending_submissions"])
                pending_data["pending_submissions"] = [
                    sub for sub in pending_data["pending_submissions"] 
                    if sub["submission_id"] != self.submission_id
                ]
                
                with open("pending_calendars.json", mode="w", encoding="utf-8") as wb:
                    json.dump(pending_data, wb, indent=2)
            logger.info(
                "Removed pending submission_id=%s before=%s after=%s",
                self.submission_id,
                previous_count,
                len(pending_data["pending_submissions"]),
            )
                
        except Exception as e:
            logger.exception("Error removing from pending submission_id=%s", self.submission_id)

    def _format_calendar_details(self) -> str:
        """Format calendar details for display"""
        return (
            f"**Name:** {self.calendar_data['name']}\n"
            f"**Key:** {self.calendar_data['key']}\n"
            f"**Current Year:** {self.calendar_data['current_year']}\n"
            f"**Staff Years Per Year:** {calendar_rate_label(self.calendar_data)}\n"
            f"**Is Staff Years:** {'Yes' if self.calendar_data['is_staff_years'] else 'No'}"
        )

    async def _notify_submitter(self, client: discord.Client, status: str):
        """Send DM notification to the submitter"""
        try:
            logger.info(
                "Notifying submitter submission_id=%s submitter_id=%s status=%s",
                self.submission_id,
                self.submitter_id,
                status,
            )
            user = await client.fetch_user(self.submitter_id)
            if user:
                status_emoji = "✅" if status == "approved" else "❌"
                status_text = "approved" if status == "approved" else "denied"
                
                embed = discord.Embed(
                    title=f"{status_emoji} Calendar Submission {status_text.title()}",
                    description=f"Your calendar submission **{self.calendar_data['name']}** has been {status_text}.",
                    color=discord.Color.green() if status == "approved" else discord.Color.red(),
                    timestamp=datetime.now()
                )
                embed.add_field(name="Calendar Details", value=self._format_calendar_details(), inline=False)
                
                await user.send(embed=embed)
                logger.info("Submitter notification sent submission_id=%s", self.submission_id)
            else:
                logger.warning(
                    "Submitter lookup returned no user submission_id=%s submitter_id=%s",
                    self.submission_id,
                    self.submitter_id,
                )
        except Exception as e:
            logger.exception("Error notifying submitter submission_id=%s", self.submission_id)

    def _can_review_submission(self, interaction: discord.Interaction) -> bool:
        """
        Allow review from:
        - members with moderate_members permission in a guild context
        - configured reviewer user IDs in DM context
        """
        guild_permissions = getattr(interaction.user, "guild_permissions", None)
        if guild_permissions and getattr(guild_permissions, "moderate_members", False):
            return True

        # In DMs, interaction.user is discord.User and has no guild_permissions.
        reviewer_ids = self._get_reviewer_ids()
        return interaction.user.id in reviewer_ids

    def _get_reviewer_ids(self) -> set[int]:
        raw_ids = os.getenv("APPROVAL_REVIEWER_IDS", str(DEFAULT_APPROVAL_USER_ID))
        reviewer_ids: set[int] = set()
        for raw_id in raw_ids.split(","):
            cleaned = raw_id.strip()
            if not cleaned:
                continue
            try:
                reviewer_ids.add(int(cleaned))
            except ValueError:
                logger.warning("Invalid APPROVAL_REVIEWER_IDS entry ignored value=%s", cleaned)
        if not reviewer_ids:
            reviewer_ids.add(DEFAULT_APPROVAL_USER_ID)
        return reviewer_ids

def create_approval_embed(calendar_data: Dict[str, Any], submitter_id: int, submission_id: str) -> discord.Embed:
    """Create an embed for calendar approval"""
    logger.debug(
        "Creating approval embed submission_id=%s submitter_id=%s calendar_name=%s",
        submission_id,
        submitter_id,
        calendar_data.get("name"),
    )
    embed = discord.Embed(
        title="📅 New Calendar Submission",
        description="A new calendar has been submitted and requires approval.",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    embed.add_field(
        name="Calendar Details", 
        value=(
            f"**Name:** {calendar_data['name']}\n"
            f"**Key:** {calendar_data['key']}\n"
            f"**Current Year:** {calendar_data['current_year']}\n"
            f"**Staff Years Per Year:** {calendar_rate_label(calendar_data)}\n"
            f"**Is Staff Years:** {'Yes' if calendar_data['is_staff_years'] else 'No'}"
        ), 
        inline=False
    )
    
    embed.add_field(name="Submitted by", value=f"<@{submitter_id}>", inline=True)
    embed.add_field(name="Submission ID", value=submission_id, inline=True)
    
    return embed 
