import discord
from discord import Button, ButtonStyle
from discord.ui import View, button
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

class ApprovalView(View):
    def __init__(self, submission_id: str, calendar_data: Dict[str, Any], submitter_id: int):
        super().__init__(timeout=None)  # No timeout for approval buttons
        self.submission_id = submission_id
        self.calendar_data = calendar_data
        self.submitter_id = submitter_id

    @button(label="✅ Approve", style=ButtonStyle.success)
    async def approve_calendar(self, interaction: discord.Interaction, button: Button):
        # Check if user has permission to approve (moderate_members or higher)
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message("You don't have permission to approve calendar submissions.", ephemeral=True)
            return

        try:
            # Load current config
            with open("config.json", mode="r", encoding="utf-8") as rb:
                config = json.load(rb)
            
            # Remove any existing calendar with the same name
            config["calendars"] = [cal for cal in config["calendars"] if cal["name"] != self.calendar_data["name"]]
            
            # Add the approved calendar
            config["calendars"].append(self.calendar_data)
            
            # Save updated config
            with open("config.json", mode="w", encoding="utf-8") as wb:
                json.dump(config, wb, separators=(',', ':'))
            
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
            
            # Notify the submitter
            await self._notify_submitter(interaction.client, "approved")
            
        except Exception as e:
            await interaction.response.send_message(f"Error approving calendar: {str(e)}", ephemeral=True)

    @button(label="❌ Deny", style=ButtonStyle.danger)
    async def deny_calendar(self, interaction: discord.Interaction, button: Button):
        # Check if user has permission to deny (moderate_members or higher)
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message("You don't have permission to deny calendar submissions.", ephemeral=True)
            return

        try:
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
            
            # Notify the submitter
            await self._notify_submitter(interaction.client, "denied")
            
        except Exception as e:
            await interaction.response.send_message(f"Error denying calendar: {str(e)}", ephemeral=True)

    async def _remove_from_pending(self):
        """Remove the submission from pending_calendars.json"""
        try:
            with open("pending_calendars.json", mode="r", encoding="utf-8") as rb:
                pending_data = json.load(rb)
            
            # Remove the submission with matching ID
            pending_data["pending_submissions"] = [
                sub for sub in pending_data["pending_submissions"] 
                if sub["submission_id"] != self.submission_id
            ]
            
            with open("pending_calendars.json", mode="w", encoding="utf-8") as wb:
                json.dump(pending_data, wb, indent=2)
                
        except Exception as e:
            print(f"Error removing from pending: {e}")

    def _format_calendar_details(self) -> str:
        """Format calendar details for display"""
        return (
            f"**Name:** {self.calendar_data['name']}\n"
            f"**Key:** {self.calendar_data['key']}\n"
            f"**Current Year:** {self.calendar_data['current_year']}\n"
            f"**Hours Per Year:** {self.calendar_data['hours_per_year']}\n"
            f"**Is Staff Years:** {'Yes' if self.calendar_data['is_staff_years'] else 'No'}"
        )

    async def _notify_submitter(self, client: discord.Client, status: str):
        """Send DM notification to the submitter"""
        try:
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
        except Exception as e:
            print(f"Error notifying submitter: {e}")

def create_approval_embed(calendar_data: Dict[str, Any], submitter_id: int, submission_id: str) -> discord.Embed:
    """Create an embed for calendar approval"""
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
            f"**Hours Per Year:** {calendar_data['hours_per_year']}\n"
            f"**Is Staff Years:** {'Yes' if calendar_data['is_staff_years'] else 'No'}"
        ), 
        inline=False
    )
    
    embed.add_field(name="Submitted by", value=f"<@{submitter_id}>", inline=True)
    embed.add_field(name="Submission ID", value=submission_id, inline=True)
    
    return embed 