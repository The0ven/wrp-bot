import discord
from discord.ext import commands
import pandas as pd
import numpy as np
import json
from typing import Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

def acronym(key: str):
    """Convert a key to its acronym format"""
    return ''.join([f"{s.upper()}." for s in key])

class QueryCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.slash_command(
        name="when",
        description="Get one or all calendars' year for a given real day using a date in format YYYY-MM-DD."
    )
    async def get_year(
        self,
        ctx,
        day: discord.Option(str, "Target real date in YYYY-MM-DD format", required=True),
        calendar: discord.Option(str, "Optional calendar key to query (e.g. sy)", required=False, default=None),
    ):
        """Get calendar year for a specific date"""
        try:
            arg_calendar = calendar
            df = pd.read_json('history.jsonl', lines=True)
            
            with open('config.json', mode='r') as rb:
                config = json.load(rb)
            
            target_day = datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1) - timedelta(seconds=60)
            logger.info(f"target_day: {target_day.timestamp()}")

            # Find the closest entry in the history
            i = np.argmin(np.abs(df['timestamp'] - target_day))
            years: pd.Series = df.iloc[i]
            logger.info(f"closest_entry: {years['timestamp'].timestamp()}")

            if arg_calendar is not None and arg_calendar in years.index:
                cal_year = years[arg_calendar]
                logger.info(f"cal_year: {cal_year}")
                cal_conf = [conf_cal for conf_cal in config['calendars'] if conf_cal['key'] == arg_calendar][0]
                await ctx.respond(
                    f"On {day} it was {cal_year:.0f} {acronym(cal_conf['key'])}"
                )
            elif arg_calendar is not None:
                configured_keys = {conf_cal["key"] for conf_cal in config["calendars"]}
                if arg_calendar not in configured_keys:
                    await ctx.respond(
                        f"Calendar key `{arg_calendar}` is not configured.",
                        ephemeral=True,
                    )
                else:
                    await ctx.respond(
                        f"No data for calendar `{arg_calendar}` on {day}.",
                        ephemeral=True,
                    )
            else:
                msgs = []
                for conf_cal in config["calendars"]:
                    key = conf_cal["key"]
                    if key not in years.index:
                        continue
                    value = years[key]
                    if pd.isna(value) or value <= 0:
                        continue
                    msgs.append(f"{value:.0f} {acronym(key)}")

                if not msgs:
                    await ctx.respond(
                        f"No calendar data available for {day}.",
                        ephemeral=True,
                    )
                else:
                    await ctx.respond(f"**On {day} it was:**\n" + "\n".join(msgs))
                
        except FileNotFoundError:
            await ctx.respond(
                "No history file found. Please configure the calendar first.", 
                ephemeral=True
            )
        except ValueError:
            await ctx.respond(
                "Invalid date format. Please use YYYY-MM-DD format.", 
                ephemeral=True
            )
        except Exception as e:
            await ctx.respond(
                f"Error querying calendar: {str(e)}", 
                ephemeral=True
            )

def setup(bot: commands.Bot):
    bot.add_cog(QueryCog(bot)) 