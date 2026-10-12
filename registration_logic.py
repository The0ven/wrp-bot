"""Pure helpers for the registration flow: form layout, validation, and rendering."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

INPUT_LIMIT = 4000
LORE_MIN = 2000
LORE_PARTS = 5
CUSTOM_ID_PREFIX = "wrpreg"
POPULATION_RANGE = (0, 2147483647)
YEAR_RANGE = (-9999, 9999)


class ActionError(Exception):
    """A user-facing reason an action cannot be performed."""


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    max_length: int
    required: bool = True
    long: bool = False
    placeholder: str | None = None


SECTIONS: dict[str, tuple[str, list[Field]]] = {
    "identity": ("Identity", [
        Field("official_name", "Official name", 200, placeholder="The Most Serene Republic of ..."),
        Field("short_name", "Short name", 100, placeholder="Used as your tracker name"),
        Field("other_names", "Other names (optional)", 500, required=False, long=True),
        Field("demonyms", "Demonyms", 200, placeholder="What your people are called"),
        Field("capital", "Capital", 200),
    ]),
    "government": ("Government", [
        Field("government", "Government", 1000, long=True, placeholder="Monarchy, oligarchy, republic ..."),
        Field("legislature", "Legislature", 1000, long=True, placeholder="e.g. House and Senate, or None"),
        Field("rulers", "Rulers", 1000, long=True),
        Field("religions", "Religions", 1000, long=True, placeholder="Or None"),
    ]),
    "land": ("Languages and land", [
        Field("languages", "Languages and real-world equivalents", 1000, long=True,
              placeholder="Name and its real-world equivalent. It cannot be a real language."),
        Field("spawn_location", "Spawn location", 500, long=True),
        Field("cities", "Cities and locations (optional)", 1500, required=False, long=True,
              placeholder="Can also be added after acceptance"),
    ]),
    "lore": ("Lore", [
        Field(f"lore_{i}", "Lore" if i == 1 else f"Lore, part {i} (optional)", INPUT_LIMIT,
              required=i == 1, long=True,
              placeholder=f"Minimum {LORE_MIN:,} characters in total" if i == 1 else None)
        for i in range(1, LORE_PARTS + 1)
    ]),
}
FIELDS = {f.key: f for _, fields in SECTIONS.values() for f in fields}

STEPS = ["identity", "government", "land", "lore", "calendar", "system", "images", "rules", "review"]
STEP_TITLES = {
    "identity": "Identity", "government": "Government", "land": "Languages and land",
    "lore": "Lore", "calendar": "Calendar", "system": "System", "images": "Flag and map",
    "rules": "Rules", "review": "Review and submit",
}
SYSTEMS = {
    "closed": ("Closed System", "No war; focus on worldbuilding"),
    "open": ("Open System", "War enabled"),
}
ACKNOWLEDGEMENTS = {
    "no_ai": "I wrote this myself, without AI",
    "fictional_language": "My languages are fictional, not real languages",
    "unclaimed_land": "I checked that my claimed land is unclaimed",
}
UPLOAD_PURPOSES = {
    "flag": "Flag",
    "claim_map": "Claim map with borders",
    "city_map": "City map",
}
REQUIRED_UPLOADS = ("flag", "claim_map")
# Fields registrants may change after acceptance without another staff review.
DIRECT_AMEND_KEYS = {"cities", "calendar", "files.city_map"}


# Text helpers ----------------------------------------------------------------

def clean(value: Any) -> str:
    return str(value or "").strip()


def lore_parts(data: dict) -> list[str]:
    return [clean(data.get(f"lore_{i}")) for i in range(1, LORE_PARTS + 1) if clean(data.get(f"lore_{i}"))]


def lore_length(data: dict) -> int:
    return sum(len(part) for part in lore_parts(data))


def lore_text(data: dict) -> str:
    return "\n\n".join(lore_parts(data))


def chunk_text(text: str, limit: int = INPUT_LIMIT) -> list[str]:
    """Split text into chunks no longer than limit, preferring line breaks."""
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            space = line.rfind(" ", 0, limit)
            cut = space if space > limit // 2 else limit
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:cut].rstrip())
            line = line[cut:].lstrip()
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current.strip():
        chunks.append(current)
    return [c for c in chunks if c.strip()]


def truncate(text: str, limit: int) -> str:
    text = clean(text)
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


# Completeness ----------------------------------------------------------------

def section_missing(data: dict, section: str) -> list[str]:
    _, fields = SECTIONS[section]
    missing = [f.label for f in fields if f.required and not clean(data.get(f.key))]
    if section == "lore" and not missing and lore_length(data) < LORE_MIN:
        missing.append(f"Lore needs {LORE_MIN - lore_length(data):,} more characters")
    return missing


def calendar_valid(choice: Any) -> bool:
    if not isinstance(choice, dict):
        return False
    if choice.get("mode") == "existing":
        return bool(clean(choice.get("name")))
    if choice.get("mode") == "new":
        return all(k in choice for k in ("name", "key", "current_year", "staff_years_per_year"))
    return False


def step_missing(data: dict, step: str) -> list[str]:
    if step in SECTIONS:
        return section_missing(data, step)
    if step == "calendar":
        return [] if calendar_valid(data.get("calendar")) else ["Calendar"]
    if step == "system":
        return [] if data.get("system") in SYSTEMS else ["Closed or open system"]
    if step == "images":
        files = data.get("files") or {}
        return [UPLOAD_PURPOSES[p] for p in REQUIRED_UPLOADS if not files.get(p)]
    if step == "rules":
        acks = set(data.get("acknowledgements") or [])
        return [text for key, text in ACKNOWLEDGEMENTS.items() if key not in acks]
    if step == "review":
        return missing_items(data)
    raise KeyError(step)


def missing_items(data: dict) -> list[str]:
    items: list[str] = []
    for step in STEPS[:-1]:
        items.extend(step_missing(data, step))
    return items


def step_complete(data: dict, step: str) -> bool:
    return not step_missing(data, step)


def apply_section(data: dict, section: str, values: dict[str, str]) -> dict:
    """Return a copy of data with a modal section's trimmed values applied."""
    updated = dict(data)
    for f in SECTIONS[section][1]:
        if f.key in values:
            value = clean(values[f.key])[: f.max_length]
            if value:
                updated[f.key] = value
            else:
                updated.pop(f.key, None)
    return updated


# Calendars -------------------------------------------------------------------

def calendar_names(calendars: Iterable[dict]) -> list[str]:
    return sorted((c["name"] for c in calendars if not c.get("is_staff_years")), key=str.casefold)


def calendar_page(names: list[str], page: int, size: int = 25) -> tuple[list[str], int, int]:
    pages = max(1, math.ceil(len(names) / size))
    page = min(max(page, 0), pages - 1)
    return names[page * size:(page + 1) * size], page, pages


def calendar_label(choice: Any) -> str:
    if not calendar_valid(choice):
        return "Not chosen"
    if choice["mode"] == "existing":
        return choice["name"]
    return (f"{choice['name']} ({choice['key']}), new calendar: year {choice['current_year']}, "
            f"{choice['staff_years_per_year']:g} staff years per year")


def parse_number(raw: Any) -> float | None:
    text = re.sub(r"[\s,_]", "", clean(raw))
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def parse_int(raw: Any, low: int, high: int) -> int | None:
    text = re.sub(r"[\s,_]", "", clean(raw))
    if not re.fullmatch(r"[+-]?\d+", text):
        return None
    value = int(text)
    return value if low <= value <= high else None


def validate_new_calendar(name: Any, key: Any, current_year: Any, rate: Any,
                          calendars: Iterable[dict], pending: Iterable[dict] = ()) -> tuple[dict | None, str | None]:
    name, key = clean(name), clean(key)
    if not name or len(name) > 100:
        return None, "Calendar name must be 1-100 characters."
    if not key or len(key) > 20 or " " in key:
        return None, "Acronym must be 1-20 characters with no spaces."
    year = parse_int(current_year, 0, 10**9)
    if year is None:
        return None, "Current year must be a whole number of 0 or more."
    staff_rate = parse_number(rate)
    if staff_rate is None or staff_rate <= 0:
        return None, "Staff years per calendar year must be a positive number."
    existing = list(calendars) + [p.get("calendar_data", {}) for p in pending]
    if any(clean(c.get("name")).casefold() == name.casefold() for c in existing):
        return None, f"A calendar named '{name}' already exists or is awaiting approval."
    if any(clean(c.get("key")).casefold() == key.casefold() for c in existing):
        return None, f"The acronym '{key}' is already used."
    return {"mode": "new", "name": name, "key": key, "current_year": year,
            "staff_years_per_year": staff_rate}, None


def calendar_submission_data(choice: dict) -> dict:
    return {
        "name": choice["name"],
        "key": choice["key"],
        "staff_years_per_year": float(choice["staff_years_per_year"]),
        "current_year": int(choice["current_year"]),
        "is_staff_years": False,
    }


# Rendering -------------------------------------------------------------------

def thread_name(data: dict) -> str:
    return truncate(data.get("short_name") or data.get("official_name") or "New nation", 100)


def render_template(data: dict, *, population: int | None = None, start_year: int | None = None) -> str:
    files = data.get("files") or {}
    system = SYSTEMS.get(data.get("system"), ("Not chosen", ""))

    def value(key: str, fallback: str = "None") -> str:
        return clean(data.get(key)) or fallback

    lines = [
        ("Official Name", value("official_name")),
        ("Flag", "Attached below" if files.get("flag") else "Missing"),
        ("Short Name", value("short_name")),
        ("Other Names", value("other_names")),
        ("Government", value("government")),
        ("Legislature", value("legislature")),
        ("Population", f"{population:,}" if population is not None else "Assigned after staff approval"),
        ("Religions", value("religions")),
        ("Rulers", value("rulers")),
        ("Demonyms", value("demonyms")),
        ("Capital", value("capital")),
        ("Languages", value("languages")),
        ("Calendar", calendar_label(data.get("calendar"))),
        ("Closed System or Open System?", f"{system[0]} ({system[1]})" if system[1] else system[0]),
        ("Spawn Location", value("spawn_location")),
        ("Cities", value("cities", "To be added")),
    ]
    if start_year is not None:
        lines.insert(7, ("Start Year", str(start_year)))
    return "\n".join(f"**{label}** - {text}" for label, text in lines)


# Roles -----------------------------------------------------------------------

def role_plan(current_ids: Iterable[int], settings: Any, system: str, extra_ids: Iterable[int] = (),
              include_temp: bool = True) -> tuple[list[int], list[int]]:
    """Roles to add and remove; unrelated roles are left untouched."""
    current = set(current_ids)
    wanted = [settings.player_role_id]
    if include_temp:
        wanted.append(settings.temp_role_id)
    wanted.append(settings.system_role_id(system))
    wanted.extend(extra_ids)
    add: list[int] = []
    for role_id in wanted:
        if role_id not in current and role_id not in add:
            add.append(role_id)
    other = settings.open_role_id if system == "closed" else settings.closed_role_id
    remove = [other] if other in current else []
    return add, remove


def is_staff(member: Any, staff_role_id: int) -> bool:
    perms = getattr(member, "guild_permissions", None)
    if perms is not None and getattr(perms, "administrator", False):
        return True
    return any(getattr(role, "id", None) == staff_role_id for role in getattr(member, "roles", []) or [])


# Custom IDs and diffs ---------------------------------------------------------

def make_custom_id(kind: str, action: str, app_id: str, revision: int) -> str:
    return f"{CUSTOM_ID_PREFIX}:{kind}:{action}:{app_id}:{revision}"


def parse_custom_id(custom_id: str | None) -> tuple[str, str, str, int] | None:
    if not custom_id:
        return None
    parts = custom_id.split(":")
    if len(parts) != 5 or parts[0] != CUSTOM_ID_PREFIX:
        return None
    try:
        return parts[1], parts[2], parts[3], int(parts[4])
    except ValueError:
        return None


def flatten(data: dict) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key in list(FIELDS) + ["calendar", "system"]:
        flat[key] = data.get(key) if key in ("calendar", "system") else clean(data.get(key))
    for purpose in UPLOAD_PURPOSES:
        flat[f"files.{purpose}"] = (data.get("files") or {}).get(purpose)
    return flat


def diff_fields(old: dict, new: dict) -> list[str]:
    before, after = flatten(old or {}), flatten(new or {})
    return [key for key in after if before.get(key) != after.get(key)]


def field_label(key: str) -> str:
    if key.startswith("files."):
        return UPLOAD_PURPOSES[key.split(".", 1)[1]]
    if key in FIELDS:
        return FIELDS[key].label.replace(" (optional)", "")
    return STEP_TITLES.get(key, key.replace("_", " ").title())


def merge_fields(base: dict, source: dict, keys: Iterable[str]) -> dict:
    """Copy the given flattened keys from source into a copy of base."""
    merged = dict(base)
    merged["files"] = dict(base.get("files") or {})
    for key in keys:
        if key.startswith("files."):
            purpose = key.split(".", 1)[1]
            value = (source.get("files") or {}).get(purpose)
            if value:
                merged["files"][purpose] = value
            else:
                merged["files"].pop(purpose, None)
        elif source.get(key) in (None, ""):
            merged.pop(key, None)
        else:
            merged[key] = source[key]
    return merged
