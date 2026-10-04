import discord
from discord.ext import tasks
import pandas as pd
import json
import os
from datetime import datetime, timedelta
from time import time

def get_staff_calendar(calendars):
    """Return the configured staff-years calendar."""
    return next((cal for cal in calendars if cal.get("is_staff_years") is True), None)


def ensure_staff_years_per_year(config):
    """
    Ensure each calendar stores staff_years_per_year.

    Backfills from legacy hours_per_year using the current staff-year length.
    """
    calendars = config.get("calendars", [])
    staff_calendar = get_staff_calendar(calendars)
    if staff_calendar is None:
        return False

    staff_hours = float(staff_calendar.get("hours_per_year", 0))
    if staff_hours <= 0:
        return False

    changed = False
    for cal in calendars:
        if cal.get("is_staff_years"):
            if cal.get("staff_years_per_year") != 1.0:
                cal["staff_years_per_year"] = 1.0
                changed = True
            continue

        ratio = cal.get("staff_years_per_year")
        if isinstance(ratio, (int, float)) and ratio > 0:
            continue

        legacy_hours = float(cal.get("hours_per_year", 0))
        if legacy_hours <= 0:
            continue
        cal["staff_years_per_year"] = legacy_hours / staff_hours
        changed = True

    return changed


def calendar_year_delta(delta_seconds, calendar, staff_hours_per_year):
    """Convert elapsed real seconds into years for one calendar."""
    if calendar.get("is_staff_years"):
        return delta_seconds / timedelta(hours=staff_hours_per_year).total_seconds()

    staff_years_per_year = float(calendar.get("staff_years_per_year", 0))
    if staff_years_per_year <= 0:
        # Legacy fallback: preserve prior behavior if ratio is unavailable.
        legacy_hours = float(calendar.get("hours_per_year", 0))
        if legacy_hours <= 0:
            return 0.0
        return delta_seconds / timedelta(hours=legacy_hours).total_seconds()

    staff_year_delta = delta_seconds / timedelta(hours=staff_hours_per_year).total_seconds()
    return staff_year_delta / staff_years_per_year


def compute_years(last_entry, calendars, printed):
    """Compute years for all calendars based on time delta"""
    ts = datetime.fromtimestamp(time())
    out = {"timestamp": ts, "printed": printed}
    td = abs((last_entry["timestamp"] - ts).total_seconds())
    staff_calendar = get_staff_calendar(calendars)
    if staff_calendar is None:
        return out

    staff_hours = float(staff_calendar.get("hours_per_year", 0))
    if staff_hours <= 0:
        return out
    
    for cal in calendars:
        if cal["key"] in last_entry:
            # calculate year delta from elapsed real time via staff-years conversion
            td_f = calendar_year_delta(td, cal, staff_hours)
            print(td_f)
            out[cal["key"]] = last_entry[cal["key"]] + td_f
        else:
            out[cal["key"]] = cal["current_year"]
    
    print('  '.join([f"{k}: {v}" for k,v in out.items()]))
    return out

def acronym(key: str):
    """Convert a key to its acronym format"""
    return ''.join([f"{s.upper()}." for s in key])