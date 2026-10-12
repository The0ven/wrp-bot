import sqlite3

import discord

import registration_logic as logic
import registration_store as rs
from cogs import registration_cog as rc


def options(command):
    return {o.name: o for o in command.options}


def test_upload_command_has_attachment_and_purpose_choices():
    opts = options(rc.RegistrationCog.registration_upload)
    assert opts["file"].input_type == discord.SlashCommandOptionType.attachment
    assert opts["purpose"].input_type == discord.SlashCommandOptionType.string
    assert {c.value for c in opts["purpose"].choices} == set(logic.UPLOAD_PURPOSES)


def test_staff_commands_use_typed_options():
    commands = {c.name: c for c in rc.RegistrationCog.registrations.subcommands}
    for name in ("status", "retry", "withdraw", "link", "release"):
        assert options(commands[name])["member"].input_type == discord.SlashCommandOptionType.user
    assert options(commands["roles_add"])["role"].input_type == discord.SlashCommandOptionType.role
    assert options(commands["roles_add"])["group"].choices


def test_store_adds_new_columns_to_existing_database(tmp_path):
    path = str(tmp_path / "old.db")
    schema = rs.SCHEMA.replace(",\n    wizard_message_id INTEGER", "")
    assert "wizard_message_id" not in schema
    old = sqlite3.connect(path)
    old.executescript(schema)
    old.close()
    store = rs.RegistrationStore(path)
    try:
        app = store.create(1, 2)
        assert store.update(app.id, wizard_message_id=5)
        assert store.get(app.id).wizard_message_id == 5
    finally:
        store.close()
