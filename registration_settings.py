"""Environment-driven settings for the nation registration flow."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _ids(name: str, default: str = "") -> tuple[int, ...]:
    raw = os.getenv(name, default)
    return tuple(int(part) for part in raw.replace(" ", "").split(",") if part)


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RegistrationSettings:
    enabled: bool = False
    guild_ids: tuple[int, ...] = ()
    channel_id: int = 1090089906073784400
    staff_role_id: int = 929039388434898964
    population_approver_id: int = 322487124102479873
    player_role_id: int = 596718382661894149
    temp_role_id: int = 1396225120376324208
    closed_role_id: int = 1394778351322923109
    open_role_id: int = 1394778385586196642
    calendar_guide_channel_id: int = 1142543965854380064
    claim_check_channel_ids: tuple[int, ...] = (1090770743203217539, 1085304167553310810)
    temp_role_days: int = 14
    db_path: str = "registrations.db"
    upload_dir: str = "registration_uploads"
    max_upload_mb: int = 8
    tracker_url: str = ""
    tracker_token: str = ""

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def system_role_id(self, system: str) -> int:
        return self.closed_role_id if system == "closed" else self.open_role_id


def load_settings() -> RegistrationSettings:
    base = RegistrationSettings()
    return RegistrationSettings(
        enabled=_bool("REGISTRATION_ENABLED", False),
        guild_ids=_ids("REGISTRATION_GUILD_IDS"),
        channel_id=_int("REGISTRATION_CHANNEL_ID", base.channel_id),
        staff_role_id=_int("REGISTRATION_STAFF_ROLE_ID", base.staff_role_id),
        population_approver_id=_int("POPULATION_APPROVER_ID", base.population_approver_id),
        player_role_id=_int("PLAYER_ROLE_ID", base.player_role_id),
        temp_role_id=_int("TEMP_ROLE_ID", base.temp_role_id),
        closed_role_id=_int("CLOSED_SYSTEM_ROLE_ID", base.closed_role_id),
        open_role_id=_int("OPEN_SYSTEM_ROLE_ID", base.open_role_id),
        calendar_guide_channel_id=_int("CALENDAR_GUIDE_CHANNEL_ID", base.calendar_guide_channel_id),
        claim_check_channel_ids=_ids(
            "CLAIM_CHECK_CHANNEL_IDS",
            ",".join(str(i) for i in base.claim_check_channel_ids),
        ),
        temp_role_days=_int("TEMP_ROLE_DAYS", base.temp_role_days),
        db_path=os.getenv("REGISTRATION_DB_PATH", base.db_path).strip() or base.db_path,
        upload_dir=os.getenv("REGISTRATION_UPLOAD_DIR", base.upload_dir).strip() or base.upload_dir,
        max_upload_mb=_int("REGISTRATION_MAX_UPLOAD_MB", base.max_upload_mb),
        tracker_url=os.getenv("WRP_POPS_URL", "").strip().rstrip("/"),
        tracker_token=os.getenv("WRP_POPS_TOKEN", "").strip(),
    )
