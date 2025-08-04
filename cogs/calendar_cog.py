import discord
from discord.ext import commands, tasks
from discord import ChannelType
from views import AddCalendar, Initialize
from approval_views import ApprovalView, create_approval_embed
import json
import uuid
from datetime import datetime, timedelta
import os
import pandas as pd
from time import time
from tasks.new_year_task import compute_years, acronym

class CalendarCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
        description="Add a calendar"
    )
    @commands.has_permissions(moderate_members=True)
    async def add_calendar(self, ctx):
        """Add a new calendar to the system"""
        # For bridge commands, we need to send the modal differently
        if hasattr(ctx, 'interaction'):
            # This is a slash command, we can send the modal
            await ctx.interaction.response.send_modal(AddCalendar())
        else:
            # This is a prefix command, we can't send modals
            await ctx.respond("Please use the slash command version to add a calendar with a modal.", ephemeral=True)

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
                        f"**Hours Per Year:** {calendar['hours_per_year']}\n"
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
        try:
            with open('config.json', mode='r') as rb:
                config = json.load(rb)
        except FileNotFoundError:
            print("Warning: config.json not found. Skipping new year calculation.")
            return
        except json.JSONDecodeError as e:
            print(f"Error reading config.json: {e}. Skipping new year calculation.")
            return

        df = None
        try:
            sy = [cal for cal in config['calendars'] if cal['is_staff_years'] == True][0]
        except IndexError:
            print("Warning: No staff years calendar found in config. Skipping new year calculation.")
            return

        entry = None

        print([c['key'] for c in config['calendars']])
        
        if os.path.exists('history.jsonl'):
            df = pd.read_json('history.jsonl', lines=True)
            delta = df['timestamp'].iat[-1] - datetime.fromtimestamp(time())
            
            if "printed" not in df.columns:
                df["printed"] = None
                
            sy_delta = datetime.fromtimestamp(0) - datetime.fromtimestamp(time())
            dropped_df = df.dropna(subset=["printed"])
            
            if len(dropped_df) > 1:
                print('  '.join([f"{k}: {v}" for k,v in dropped_df.iloc[-1].items()]))
                sy_delta = dropped_df['timestamp'].iat[-1] - datetime.fromtimestamp(time())
                
            print(f"{df['timestamp'].iat[-1]}, time_since_last_save: {abs(delta.total_seconds() / 60):.2f}, time_since_last_print: {abs(sy_delta.total_seconds() / 60):.2f}, delta_threshold_sy: {timedelta(hours=sy['hours_per_year']).total_seconds() / 60:.2f}, delta_threshold_min: {timedelta(hours=6).total_seconds() / 60:.2f}")
            
            if abs(sy_delta) >= timedelta(hours=sy["hours_per_year"]):
                entry = compute_years(df.to_dict("records")[-1], config['calendars'], True)
                df = pd.concat([df, pd.DataFrame([entry])])
                print(df.tail(2))
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