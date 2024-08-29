from typing import Optional
import discord
import os
from discord.enums import ChannelType
from dotenv import load_dotenv
from views import AddCalendar, Initialize
from discord.ext import tasks
import pandas as pd
from datetime import datetime as dt, timedelta
import numpy as np
from time import time
import json

load_dotenv()

def compute_years(last_entry, calendars):
    ts = dt.fromtimestamp(time())
    out = {"timestamp": ts}
    td = dt.fromtimestamp(last_entry["timestamp"]) - ts
    for cal in calendars:
        if cal["key"] in last_entry:
            # calculate year delta from timestamps. years transposed to seconds via hrs/yr config
            td_f = td.total_seconds() / timedelta(hours=cal['hours_per_year']).total_seconds()
            print(td_f)
            out[cal["key"]] = last_entry[cal["key"]] + td_f
        else:
            out[cal["key"]] = cal["current_year"]
    return out

def acronym(key: str):
    return ''.join([f"{s.upper()}." for s in key])

class WRPClient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def on_ready(self):

        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    async def setup_hook(self) -> None:
        new_year.start()
        # Sync the application command with Discord.
        await self.tree.sync()

client = WRPClient()

@tasks.loop(minutes=30)
async def new_year():
    with open('config.json', mode='r') as rb:
        config = json.load(rb)
    df = None
    sy = [cal for cal in config['calendars'] if cal['is_staff_years'] == True][0]
    entry = None

    if os.path.exists('history.jsonl'):
        df = pd.read_json('history.jsonl', lines=True)
        delta = df['timestamp'].iat[-1] - dt.fromtimestamp(time())
        print(f"{df['timestamp'].iat[-1]}, time_since_last: {abs(delta.total_seconds() / 60):.2f}, delta_threshold_sy: {timedelta(hours=sy['hours_per_year']).total_seconds() / 60:.2f}, delta_threshold_min: {timedelta(hours=6).total_seconds() / 60:.2f}")
        if abs(delta) > timedelta(hours=sy["hours_per_year"]):
            entry = compute_years(df.to_dict("records")[-1], config['calendars'])
            df.loc[len(df.index)] = entry
        elif abs(delta) > timedelta(hours=6):
            entry = compute_years(df.to_dict("records")[-1], config['calendars'])
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
        await client.get_channel(channel).send(f"# A New Year Has Dawned\n\n**{entry[sy['key']]:.0f} {acronym(sy['key'])}**\n\n{calendars}")

@new_year.before_loop 
async def before_new_year():
    await client.wait_until_ready()

@client.tree.command(
    name="configure",
    description="intialize calendar tracking"
)
async def configure(interaction: discord.Interaction):
    if interaction.channel is not None and interaction.channel.type in [ChannelType.text, ChannelType.private, ChannelType.public_thread, ChannelType.private_thread]:
        await interaction.channel.send("Configure The Standard Calendar", view=Initialize())

@client.tree.command(
    name="add_calendar",
    description="add a calendar"
)
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

    if target_day < df['timestamp'].iat[0]:
        await inter.response.send_message(f"Sorry, {day} is before the calendar recording began.")
    elif target_day > df['timestamp'].iat[0]:
        await inter.response.send_message(f"Sorry, {day} is in the future or has not been recorded yet.")
    else:
        i = np.argmin(np.abs(df['timestamp'] - target_day))

        years = df.iloc[i]
        print(f"closest_entry: {years['timestamp'].timestamp()}")

        if arg_calendar is not None and arg_calendar in years.columns:
            cal_year = years[arg_calendar]
            cal_conf = [conf_cal for conf_cal in config['calendars'] if conf_cal['key'] == arg_calendar][0]
            await inter.response.send_message(f"On {day} it was {cal_year} {acronym(cal_conf['key'])}")
        else:
            msgs = "\n".join([f"{years[conf_cal['key']]:.0f} {acronym(conf_cal['key'])}" for conf_cal in config['calendars']])
            await inter.response.send_message(f"**On {day} it was:**\n{msgs}")



client.run(os.getenv('TOKEN'))
