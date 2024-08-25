import discord
import os
from discord.enums import ChannelType
from dotenv import load_dotenv
from views import AddCalendar, Initialize
from discord.ext import tasks
import pandas as pd
from datetime import datetime as dt, timedelta
from time import time
import json

load_dotenv()

def compute_years(last_entry, calendars):
    ts = time()
    out = {"timestamp": ts}
    td = last_entry["timestamp"] - dt.fromtimestamp(ts)
    for cal in calendars:
        if cal["key"] in last_entry:
            # calculate year delta from timestamps. years transposed to seconds via hrs/yr config
            td = td / (cal['hours_per_year'] * 60)
            out[cal["key"]] = last_entry[cal["key"]] + td.total_seconds()
        else:
            out[cal["key"]] = cal["current_year"]
    return out



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

@tasks.loop(minutes=1)
async def new_year():
    with open('config.json', mode='r') as rb:
        config = json.load(rb)
    df = None
    sy = [cal for cal in config['calendars'] if cal['is_staff_years'] == True][0]
    entry = None

    try:
        df = pd.read_json('history.jsonl', lines=True)
        if df['timestamp'].iat[-1] - dt.fromtimestamp(time()) > timedelta(hours=sy["hours_per_year"]):
            entry = compute_years(df.to_dict("records")[-1], config['calendars'])
            df.loc[len(df.index)] = entry
        else:
            df = None
    except Exception as e:
        raise e
        entry = compute_years({"timestamp": time()}, config['calendars'])
        df = pd.DataFrame([entry])
    if df is not None and sy is not None and entry is not None:
        df.to_json('history.jsonl', orient="records", lines=True)
        channel = config['channel']
        calendars = '\n'.join([f"{c['name']}: {entry[c['key']]:.0f}({c['acronym']})" for c in [cal for cal in config['calendars'] if cal['is_staff_years'] == False]])
        await client.get_channel(channel).send(f"# A New Year Has Dawned\n\n**{entry[sy['key']]:.0f} {sy['acronym']}**\n\n{calendars}")

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

client.run(os.getenv('TOKEN'))
