import discord
from discord.ext import commands
from approval_views import ApprovalView, create_approval_embed
import json
import uuid
from datetime import datetime

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.slash_command(
        name="pending_calendars",
        description="View pending calendar submissions (requires moderate_members permission)"
    )
    @commands.has_permissions(moderate_members=True)
    async def pending_calendars(self, ctx):
        """View pending calendar submissions"""
        try:
            with open("pending_calendars.json", mode="r", encoding="utf-8") as rb:
                pending_data = json.load(rb)
            
            if not pending_data["pending_submissions"]:
                await ctx.respond(
                    "No pending calendar submissions.", 
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title="📋 Pending Calendar Submissions",
                description=f"There are {len(pending_data['pending_submissions'])} pending submission(s).",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            for i, submission in enumerate(pending_data["pending_submissions"][:10], 1):  # Limit to 10 for readability
                calendar_data = submission["calendar_data"]
                submitter_name = submission["submitter_name"]
                submission_time = datetime.fromisoformat(submission["submission_timestamp"])
                
                embed.add_field(
                    name=f"{i}. {calendar_data['name']}",
                    value=(
                        f"**Key:** {calendar_data['key']}\n"
                        f"**Current Year:** {calendar_data['current_year']}\n"
                        f"**Hours Per Year:** {calendar_data['hours_per_year']}\n"
                        f"**Is Staff Years:** {'Yes' if calendar_data['is_staff_years'] else 'No'}\n"
                        f"**Submitted by:** {submitter_name}\n"
                        f"**Submitted:** {submission_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"**ID:** {submission['submission_id'][:8]}..."
                    ),
                    inline=False
                )
            
            if len(pending_data["pending_submissions"]) > 10:
                embed.add_field(
                    name="Note",
                    value=f"And {len(pending_data['pending_submissions']) - 10} more submission(s)...",
                    inline=False
                )
            
            await ctx.respond(embed=embed, ephemeral=True)
            
        except FileNotFoundError:
            await ctx.respond("No pending submissions file found.", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"Error viewing pending submissions: {str(e)}", ephemeral=True)

    @commands.slash_command(
        name="test_approval",
        description="Test the approval system by sending a test submission (requires moderate_members permission)"
    )
    @commands.has_permissions(moderate_members=True)
    async def test_approval(self, ctx):
        """Test command to verify the approval system is working"""
        try:
            # Create a test calendar submission
            test_calendar_data = {
                "name": "Test Calendar",
                "key": "test",
                "hours_per_year": 96.0,
                "current_year": 100,
                "is_staff_years": False
            }
            
            # Generate a test submission ID
            submission_id = str(uuid.uuid4())
            
            # Create approval embed and view
            embed = create_approval_embed(test_calendar_data, ctx.author.id, submission_id)
            approval_view = ApprovalView(submission_id, test_calendar_data, ctx.author.id)
            
            # Send the test approval request
            await ctx.channel.send(embed=embed, view=approval_view)
            
            await ctx.respond(
                "✅ Test approval request sent! Check the channel for the approval message.",
                ephemeral=True
            )
            
        except Exception as e:
            await ctx.respond(f"Error creating test approval: {str(e)}", ephemeral=True)

    @commands.slash_command(
        name="clear_pending",
        description="Clear all pending calendar submissions (requires moderate_members permission)"
    )
    @commands.has_permissions(moderate_members=True)
    async def clear_pending(self, ctx):
        """Clear all pending submissions - useful for testing"""
        try:
            with open("pending_calendars.json", mode="w", encoding="utf-8") as wb:
                json.dump({"pending_submissions": []}, wb, indent=2)
            
            await ctx.respond(
                "✅ All pending calendar submissions have been cleared.",
                ephemeral=True
            )
            
        except Exception as e:
            await ctx.respond(f"Error clearing pending submissions: {str(e)}", ephemeral=True)

def setup(bot: commands.Bot):
    bot.add_cog(AdminCog(bot)) 