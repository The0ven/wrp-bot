import discord
from discord.ext import commands
from approval_views import ApprovalView, create_approval_embed
import json
import uuid
from datetime import datetime
import logging
from file_locks import PENDING_LOCK

logger = logging.getLogger(__name__)

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.slash_command(
        name="pending_calendars",
        description="View pending calendar submissions (requires moderate_members permission)"
    )
    @commands.has_permissions(moderate_members=True)
    async def pending_calendars(
        self,
        ctx,
        repost_views: discord.Option(
            bool,
            "Re-post approval views for all pending submissions in this channel",
            required=False,
            default=False,
        ),
    ):
        """View pending calendar submissions"""
        try:
            logger.info(
                "pending_calendars invoked user_id=%s repost_views=%s",
                ctx.author.id,
                repost_views,
            )
            async with PENDING_LOCK:
                with open("pending_calendars.json", mode="r", encoding="utf-8") as rb:
                    pending_data = json.load(rb)
            
            if not pending_data["pending_submissions"]:
                logger.info("pending_calendars empty user_id=%s", ctx.author.id)
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
                        f"**Staff Years Per Year:** {calendar_data.get('staff_years_per_year', 'legacy')}\n"
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

            reposted_count = 0
            if repost_views:
                if ctx.channel is None:
                    await ctx.respond(
                        "Can't repost approval views because this command was not used in a text channel.",
                        ephemeral=True,
                    )
                    return
                for submission in pending_data["pending_submissions"]:
                    calendar_data = submission["calendar_data"]
                    submission_id = submission["submission_id"]
                    submitter_id = submission["submitter_id"]
                    approval_embed = create_approval_embed(calendar_data, submitter_id, submission_id)
                    approval_view = ApprovalView(submission_id, calendar_data, submitter_id)
                    await ctx.channel.send(embed=approval_embed, view=approval_view)
                    reposted_count += 1
                logger.info(
                    "pending_calendars reposted views user_id=%s count=%s",
                    ctx.author.id,
                    reposted_count,
                )
            
            response_text = None
            if repost_views:
                response_text = f"Reposted {reposted_count} approval view(s) in this channel."
            await ctx.respond(content=response_text, embed=embed, ephemeral=True)
            logger.info(
                "pending_calendars responded user_id=%s pending_count=%s",
                ctx.author.id,
                len(pending_data["pending_submissions"]),
            )
            
        except FileNotFoundError:
            logger.warning("pending_calendars file missing user_id=%s", ctx.author.id)
            await ctx.respond("No pending submissions file found.", ephemeral=True)
        except Exception as e:
            logger.exception("pending_calendars failed user_id=%s", ctx.author.id)
            await ctx.respond(f"Error viewing pending submissions: {str(e)}", ephemeral=True)

    @commands.slash_command(
        name="test_approval",
        description="Test the approval system by sending a test submission (requires moderate_members permission)"
    )
    @commands.has_permissions(moderate_members=True)
    async def test_approval(self, ctx):
        """Test command to verify the approval system is working"""
        try:
            logger.info("test_approval invoked user_id=%s", ctx.author.id)
            # Create a test calendar submission
            test_calendar_data = {
                "name": "Test Calendar",
                "key": "test",
                "staff_years_per_year": 1.0,
                "current_year": 100,
                "is_staff_years": False
            }
            
            # Generate a test submission ID
            submission_id = str(uuid.uuid4())

            submission = {
                "submission_id": submission_id,
                "submitter_id": ctx.author.id,
                "submitter_name": ctx.author.display_name,
                "submission_timestamp": datetime.now().isoformat(),
                "calendar_data": test_calendar_data
            }

            async with PENDING_LOCK:
                try:
                    with open("pending_calendars.json", mode="r", encoding="utf-8") as rb:
                        pending_data = json.load(rb)
                except FileNotFoundError:
                    pending_data = {"pending_submissions": []}

                pending_data["pending_submissions"].append(submission)
                with open("pending_calendars.json", mode="w", encoding="utf-8") as wb:
                    json.dump(pending_data, wb, indent=2)
            logger.info(
                "test_approval added pending submission user_id=%s submission_id=%s pending_count=%s",
                ctx.author.id,
                submission_id,
                len(pending_data["pending_submissions"]),
            )
            
            # Create approval embed and view
            embed = create_approval_embed(test_calendar_data, ctx.author.id, submission_id)
            approval_view = ApprovalView(submission_id, test_calendar_data, ctx.author.id)
            
            # Send the test approval request
            await ctx.channel.send(embed=embed, view=approval_view)
            logger.info("test_approval sent message user_id=%s submission_id=%s", ctx.author.id, submission_id)
            
            await ctx.respond(
                "✅ Test approval request sent! Check the channel for the approval message.",
                ephemeral=True
            )
            
        except Exception as e:
            logger.exception("test_approval failed user_id=%s", ctx.author.id)
            await ctx.respond(f"Error creating test approval: {str(e)}", ephemeral=True)

    @commands.slash_command(
        name="clear_pending",
        description="Clear all pending calendar submissions (requires moderate_members permission)"
    )
    @commands.has_permissions(moderate_members=True)
    async def clear_pending(self, ctx):
        """Clear all pending submissions - useful for testing"""
        try:
            logger.info("clear_pending invoked user_id=%s", ctx.author.id)
            async with PENDING_LOCK:
                with open("pending_calendars.json", mode="w", encoding="utf-8") as wb:
                    json.dump({"pending_submissions": []}, wb, indent=2)
            
            await ctx.respond(
                "✅ All pending calendar submissions have been cleared.",
                ephemeral=True
            )
            logger.info("clear_pending completed user_id=%s", ctx.author.id)
            
        except Exception as e:
            logger.exception("clear_pending failed user_id=%s", ctx.author.id)
            await ctx.respond(f"Error clearing pending submissions: {str(e)}", ephemeral=True)

def setup(bot: commands.Bot):
    bot.add_cog(AdminCog(bot)) 