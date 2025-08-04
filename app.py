from typing import Optional
import discord
import os
from discord import app_commands
from discord import ChannelType
from dotenv import load_dotenv
from views import AddCalendar, Initialize
from approval_views import ApprovalView, create_approval_embed
from discord.ext import tasks
import pandas as pd
from datetime import datetime as dt, timedelta
import numpy as np
from time import time
import json

load_dotenv()

def compute_years(last_entry, calendars, printed):
    ts = dt.fromtimestamp(time())
    out = {"timestamp": ts, "printed": printed}
    td = abs((last_entry["timestamp"] - ts).total_seconds())
    for cal in calendars:
        if cal["key"] in last_entry:
            # calculate year delta from timestamps. years transposed to seconds via hrs/yr config
            td_f = td / timedelta(hours=cal['hours_per_year']).total_seconds()
            print(td_f)
            out[cal["key"]] = last_entry[cal["key"]] + td_f
        else:
            out[cal["key"]] = cal["current_year"]
    print('  '.join([f"{k}: {v}" for k,v in out.items()]))
    return out

def acronym(key: str):
    return ''.join([f"{s.upper()}." for s in key])

class WRPClient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    async def setup_hook(self) -> None:
        new_year.start()
        # Sync the application command with Discord.
        await self.tree.sync()
        
        # Initialize pending_calendars.json if it doesn't exist
        if not os.path.exists('pending_calendars.json'):
            with open('pending_calendars.json', 'w') as f:
                json.dump({"pending_submissions": []}, f, indent=2)

client = WRPClient()

@tasks.loop(minutes=30)
async def new_year():
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
        delta = df['timestamp'].iat[-1] - dt.fromtimestamp(time())
        if "printed" not in df.columns:
            df["printed"] = None
        sy_delta = dt.fromtimestamp(0) - dt.fromtimestamp(time())
        dropped_df = df.dropna(subset=["printed"])
        if len(dropped_df) > 1:
            print('  '.join([f"{k}: {v}" for k,v in dropped_df.iloc[-1].items()]))
            sy_delta = dropped_df['timestamp'].iat[-1] - dt.fromtimestamp(time())
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
        entry = compute_years({"timestamp": dt.fromtimestamp(time())}, config['calendars'])
        df = pd.DataFrame([entry])
    if df is not None and sy is not None and entry is not None:
        df.to_json('history.jsonl', orient="records", lines=True)
        channel = config['channel']
        calendars = '\n'.join([f"{c['name']}: {entry[c['key']]:.0f}({acronym(c['key'])})" for c in [cal for cal in config['calendars'] if cal['is_staff_years'] == False]])
        async for message in client.get_channel(channel).history():
            if message.author.id == client.application_id:
                await message.delete()
        await client.get_channel(channel).send(f"# A New Year Has Dawned\n\n**{entry[sy['key']]:.0f} {acronym(sy['key'])}**\n\n{calendars}")

@new_year.before_loop 
async def before_new_year():
    await client.wait_until_ready()

@client.tree.command(
    name="configure",
    description="intialize calendar tracking"
)
@app_commands.checks.has_permissions(manage_channels=True)
async def configure(interaction: discord.Interaction):
    if interaction.channel is not None and interaction.channel.type in [ChannelType.text, ChannelType.private, ChannelType.public_thread, ChannelType.private_thread]:
        await interaction.channel.send("Configure The Standard Calendar", view=Initialize())

@client.tree.command(
    name="add_calendar",
    description="add a calendar"
)
@app_commands.checks.has_permissions(moderate_members=True)
async def add_calendar(interaction: discord.Interaction):
    await interaction.response.send_modal(AddCalendar())

@client.tree.command(
    name="when",
    description="get a calendar year for a given real day."
)
async def get_year(inter: discord.Interaction, day: str, calendar: Optional[str]):
    arg_calendar = calendar
    df = pd.read_json('history.jsonl', lines=True)
    with open('config.json', mode='r') as rb:
        config = json.load(rb)
    target_day = dt.strptime(day, "%Y-%m-%d")
    print(f"target_day: {target_day.timestamp()}")

    # if target_day < df['timestamp'].iat[0]:
    #     await inter.response.send_message(f"Sorry, {day} is before the calendar recording began.")
    # elif target_day > df['timestamp'].iat[-1]:
    #     await inter.response.send_message(f"Sorry, {day} is in the future or has not been recorded yet.")
    # else:
    i = np.argmin(np.abs(df['timestamp'] - target_day))

    years: pd.Series = df.iloc[i]
    print(f"closest_entry: {years['timestamp'].timestamp()}")

    if arg_calendar is not None and arg_calendar in years.index:
        cal_year = years[arg_calendar]
        cal_conf = [conf_cal for conf_cal in config['calendars'] if conf_cal['key'] == arg_calendar][0]
        await inter.response.send_message(f"On {day} it was {cal_year:.0f} {acronym(cal_conf['key'])}")
    else:
        msgs = "\n".join([f"{years[conf_cal['key']]:.0f} {acronym(conf_cal['key'])}" for conf_cal in config['calendars']])
        await inter.response.send_message(f"**On {day} it was:**\n{msgs}")

@client.tree.command(
    name="pending_calendars",
    description="View pending calendar submissions (requires moderate_members permission)"
)
@app_commands.checks.has_permissions(moderate_members=True)
async def pending_calendars(inter: discord.Interaction):
    try:
        with open("pending_calendars.json", mode="r", encoding="utf-8") as rb:
            pending_data = json.load(rb)
        
        if not pending_data["pending_submissions"]:
            await inter.response.send_message("No pending calendar submissions.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📋 Pending Calendar Submissions",
            description=f"There are {len(pending_data['pending_submissions'])} pending submission(s).",
            color=discord.Color.blue(),
            timestamp=dt.now()
        )
        
        for i, submission in enumerate(pending_data["pending_submissions"][:10], 1):  # Limit to 10 for readability
            calendar_data = submission["calendar_data"]
            submitter_name = submission["submitter_name"]
            submission_time = dt.fromisoformat(submission["submission_timestamp"])
            
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
        
        await inter.response.send_message(embed=embed, ephemeral=True)
        
    except FileNotFoundError:
        await inter.response.send_message("No pending submissions file found.", ephemeral=True)
    except Exception as e:
        await inter.response.send_message(f"Error viewing pending submissions: {str(e)}", ephemeral=True)

@client.tree.command(
    name="test_approval",
    description="Test the approval system by sending a test submission (requires moderate_members permission)"
)
@app_commands.checks.has_permissions(moderate_members=True)
async def test_approval(inter: discord.Interaction):
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
        import uuid
        submission_id = str(uuid.uuid4())
        
        # Create approval embed and view
        embed = create_approval_embed(test_calendar_data, inter.user.id, submission_id)
        approval_view = ApprovalView(submission_id, test_calendar_data, inter.user.id)
        
        # Send the test approval request
        await inter.channel.send(embed=embed, view=approval_view)
        
        await inter.response.send_message(
            "✅ Test approval request sent! Check the channel for the approval message.",
            ephemeral=True
        )
        
    except Exception as e:
        await inter.response.send_message(f"Error creating test approval: {str(e)}", ephemeral=True)

@client.tree.command(
    name="clear_pending",
    description="Clear all pending calendar submissions (requires moderate_members permission)"
)
@app_commands.checks.has_permissions(moderate_members=True)
async def clear_pending(inter: discord.Interaction):
    """Clear all pending submissions - useful for testing"""
    try:
        with open("pending_calendars.json", mode="w", encoding="utf-8") as wb:
            json.dump({"pending_submissions": []}, wb, indent=2)
        
        await inter.response.send_message(
            "✅ All pending calendar submissions have been cleared.",
            ephemeral=True
        )
        
    except Exception as e:
        await inter.response.send_message(f"Error clearing pending submissions: {str(e)}", ephemeral=True)

@client.tree.command(
    name="list_calendars",
    description="List all currently configured calendars"
)
async def list_calendars(inter: discord.Interaction):
    """List all calendars currently in the system"""
    try:
        with open('config.json', mode='r', encoding='utf-8') as rb:
            config = json.load(rb)
        
        if not config.get('calendars'):
            await inter.response.send_message("No calendars are currently configured.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📅 Configured Calendars",
            description=f"There are {len(config['calendars'])} calendar(s) configured.",
            color=discord.Color.green(),
            timestamp=dt.now()
        )
        
        for i, calendar in enumerate(config['calendars'], 1):
            embed.add_field(
                name=f"{i}. {calendar['name']}",
                value=(
                    f"**Key:** {calendar['key']}\n"
                    f"**Current Year:** {calendar['current_year']}\n"
                    f"**Hours Per Year:** {calendar['hours_per_year']}\n"
                    f"**Is Staff Years:** {'Yes' if calendar['is_staff_years'] else 'No'}"
                ),
                inline=False
            )
        
        await inter.response.send_message(embed=embed, ephemeral=True)
        
    except FileNotFoundError:
        await inter.response.send_message("No configuration file found.", ephemeral=True)
    except Exception as e:
        await inter.response.send_message(f"Error listing calendars: {str(e)}", ephemeral=True)

client.run(os.getenv('TOKEN'))
