import discord
from discord.ext import tasks
import pandas as pd
import json
import os
from datetime import datetime, timedelta
from time import time

def compute_years(last_entry, calendars, printed):
    """Compute years for all calendars based on time delta"""
    ts = datetime.fromtimestamp(time())
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
    """Convert a key to its acronym format"""
    return ''.join([f"{s.upper()}." for s in key])