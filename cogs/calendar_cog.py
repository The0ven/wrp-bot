import discord
from discord.ext import commands, tasks
from discord import ChannelType
from views import Initialize
from approval_views import ApprovalView, create_approval_embed
from calendar_submissions import CalendarConflict, queue_calendar_submission
import json
import uuid
from datetime import datetime, timedelta
import os
import pandas as pd
from time import time
from tasks.new_year_task import compute_years, acronym, ensure_staff_years_per_year
import logging
from file_locks import CONFIG_LOCK, PENDING_LOCK

logger = logging.getLogger(__name__)

class CalendarCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Start the new_year_loop when the bot is ready (Pycord: no cog_load, so we use on_ready)."""
        if not self.new_year_loop.is_running():
            self.new_year_loop.start()
            logger.info("[CalendarCog] new_year_loop started")

    def cog_unload(self):
        """Stop the background loop when this cog is unloaded."""
        if self.new_year_loop.is_running():
            self.new_year_loop.cancel()

    @commands.slash_command(
        name="configure",
        description="Initialize calendar tracking"
    )
    @commands.has_permissions(manage_channels=True)
    async def configure(self, ctx):
        """Initialize calendar tracking configuration"""
        if ctx.channel is not None and ctx.channel.type in [
            ChannelType.text, 
            ChannelType.private, 
            ChannelType.public_thread, 
            ChannelType.private_thread
        ]:
            await ctx.respond("Configure The Standard Calendar", view=Initialize())

    @commands.slash_command(
        name="add_calendar",
        description="Add a calendar submission for approval"
    )
    async def add_calendar(
        self,
        ctx,
        name: discord.Option(str, "Calendar display name (must be unique)", required=True),
        key: discord.Option(str, "Short key/acronym, e.g. sy (must be unique)", required=True),
        current_year: discord.Option(int, "Current year for this calendar", required=True),
        staff_years_per_year: discord.Option(float, "How many staff years per in-game year", required=True),
        is_staff_years: discord.Option(bool, "Whether this is the staff years calendar", required=False, default=False),
    ):
        """Add a new calendar to the system"""
        try:
            logger.info("add_calendar invoked user_id=%s name=%s key=%s", ctx.author.id, name, key)
            cleaned_name = name.strip()
            cleaned_key = key.strip()

            if not cleaned_name:
                await ctx.respond("Calendar name cannot be empty.", ephemeral=True)
                return
            if not cleaned_key:
                await ctx.respond("Calendar key cannot be empty.", ephemeral=True)
                return
            if staff_years_per_year <= 0:
                await ctx.respond("Staff years per year must be a positive number.", ephemeral=True)
                return
            if current_year < 0:
                await ctx.respond("Current year must be a non-negative number.", ephemeral=True)
                return

            calendar_data = {
                "name": cleaned_name,
                "key": cleaned_key,
                "staff_years_per_year": 1.0 if is_staff_years else float(staff_years_per_year),
                "current_year": int(current_year),
                "is_staff_years": bool(is_staff_years),
            }

            try:
                await queue_calendar_submission(
                    ctx.bot,
                    calendar_data,
                    ctx.author.id,
                    ctx.author.display_name,
                    fallback_channel=ctx.channel,
                )
            except CalendarConflict as conflict:
                await ctx.respond(str(conflict), ephemeral=True)
                return

            await ctx.respond(
                f"✅ Calendar submission **{cleaned_name}** has been submitted for approval!\n\n"
                f"**Details:**\n"
                f"• Name: {cleaned_name}\n"
                f"• Key: {cleaned_key}\n"
                f"• Current Year: {int(current_year)}\n"
                f"• Staff Years Per Year: {1.0 if is_staff_years else float(staff_years_per_year)}\n"
                f"• Is Staff Years: {'Yes' if is_staff_years else 'No'}\n\n"
                f"You will be notified when your submission is reviewed.",
                ephemeral=True,
            )
        except Exception as e:
            logger.exception("add_calendar failed user_id=%s", ctx.author.id)
            await ctx.respond(f"Error submitting calendar: {str(e)}", ephemeral=True)

    @commands.slash_command(
        name="list_calendars",
        description="List all currently configured calendars"
    )
    async def list_calendars(self, ctx):
        """List all calendars currently in the system"""
        try:
            with open('config.json', mode='r', encoding='utf-8') as rb:
                config = json.load(rb)
            
            if not config.get('calendars'):
                await ctx.respond(
                    "No calendars are currently configured.", 
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title="📅 Configured Calendars",
                description=f"There are {len(config['calendars'])} calendar(s) configured.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            
            # discord has a 25 field limit for embeds, so we need to split the calendars into multiple embeds
            embeds = []
            for i, calendar in enumerate(config['calendars'], 1):
                if len(embeds) == 0:
                    embeds.append(discord.Embed(
                        title="📅 Configured Calendars",
                        description=f"There are {len(config['calendars'])} calendar(s) configured.",
                        color=discord.Color.green(),
                        timestamp=datetime.now()
                    ))
                embeds[-1].add_field(
                    name=f"{i}. {calendar['name']}",
                    value=(
                        f"**Key:** {calendar['key']}\n"
                        f"**Current Year:** {calendar['current_year']}\n"
                        f"**Staff Years Per Year:** {calendar.get('staff_years_per_year', 'legacy')}\n"
                        f"**Is Staff Years:** {'Yes' if calendar['is_staff_years'] else 'No'}"
                    ),
                    inline=False
                )
                if len(embeds[-1].fields) >= 25:
                    embeds.append(discord.Embed(
                        title="📅 Configured Calendars",
                        description=f"There are {len(config['calendars'])} calendar(s) configured.",
                        color=discord.Color.green(),
                        timestamp=datetime.now()
                    ))
            
            for embed in embeds:
                await ctx.respond(embed=embed, ephemeral=True)
            
        except FileNotFoundError:
            await ctx.respond("No configuration file found.",
            ephemeral=True)



    @tasks.loop(minutes=30)
    async def new_year_loop(self):
        """Task that runs every 30 minutes to check for new years"""
        logger.info("new_year_loop started")
        try:
            async with CONFIG_LOCK:
                with open('config.json', mode='r', encoding='utf-8') as rb:
                    config = json.load(rb)
                if ensure_staff_years_per_year(config):
                    with open("config.json", mode="w", encoding="utf-8") as wb:
                        json.dump(config, wb, separators=(",", ":"))
        except FileNotFoundError:
            logger.warning("Warning: config.json not found. Skipping new year calculation.")
            return
        except json.JSONDecodeError as e:
            logger.warning(f"Error reading config.json: {e}. Skipping new year calculation.")
            return
        except Exception as e:
            logger.warning(f"Unexpected error reading config.json: {e}. Skipping new year calculation.")
            return
        logger.info("new_year_loop config loaded")
        try:
            sy = [cal for cal in config['calendars'] if cal['is_staff_years'] == True][0]
        except IndexError:
            logger.warning("Warning: No staff years calendar found in config. Skipping new year calculation.")
            return

        df = None
        entry = None
        
        if os.path.exists('history.jsonl'):
            df = pd.read_json('history.jsonl', lines=True)
            delta = df['timestamp'].iat[-1] - datetime.fromtimestamp(time())
            
            if "printed" not in df.columns:
                df["printed"] = None
                
            sy_delta = datetime.fromtimestamp(0) - datetime.fromtimestamp(time())
            dropped_df = df.dropna(subset=["printed"])
            
            if len(dropped_df) > 1:
                logger.info('  '.join([f"{k}: {v}" for k,v in dropped_df.iloc[-1].items()]))
                sy_delta = dropped_df['timestamp'].iat[-1] - datetime.fromtimestamp(time())
                
            logger.info(f"{df['timestamp'].iat[-1]}, time_since_last_save: {abs(delta.total_seconds() / 60):.2f}, time_since_last_print: {abs(sy_delta.total_seconds() / 60):.2f}, delta_threshold_sy: {timedelta(hours=sy['hours_per_year']).total_seconds() / 60:.2f}, delta_threshold_min: {timedelta(hours=6).total_seconds() / 60:.2f}")
            
            if abs(sy_delta) >= timedelta(hours=sy["hours_per_year"]):
                entry = compute_years(df.to_dict("records")[-1], config['calendars'], True)
                df = pd.concat([df, pd.DataFrame([entry])])
                logger.info(df.tail(2))
            elif abs(delta) > timedelta(hours=6):
                entry = compute_years(df.to_dict("records")[-1], config['calendars'], None)
                df.loc[len(df.index)] = entry
                df.to_json('history.jsonl', orient="records", lines=True)
                df = None
            else:
                df = None
        else:
            entry = compute_years({"timestamp": datetime.fromtimestamp(time())}, config['calendars'], None)
            df = pd.DataFrame([entry])

        if df is not None and sy is not None and entry is not None:
            df.to_json('history.jsonl', orient="records", lines=True)
            channel = config['channel']
            calendars = '\n'.join([
                f"{c['name']}: {entry[c['key']]:.0f}({acronym(c['key'])})" 
                for c in [cal for cal in config['calendars'] if cal['is_staff_years'] == False]
            ])
            
            # Delete previous messages from the bot
            async for message in self.bot.get_channel(channel).history():
                if message.author.id == self.bot.application_id:
                    await message.delete()
                    
            # Send new year announcement
            await self.bot.get_channel(channel).send(
                f"# A New Year Has Dawned\n\n"
                f"**{entry[sy['key']]:.0f} {acronym(sy['key'])}**\n\n"
                f"{calendars}"
            )

    @new_year_loop.before_loop 
    async def before_new_year(self):
        """Wait for the bot to be ready before starting the task"""
        await self.bot.wait_until_ready() 

def setup(bot: commands.Bot):
    bot.add_cog(CalendarCog(bot))
