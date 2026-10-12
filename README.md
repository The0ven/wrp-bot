# WRP Bot

A Discord bot built with Python.

## Setup with uv

This project uses [uv](https://github.com/astral-sh/uv) for dependency management.

### Prerequisites

1. Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Python 3.11+ (specified in `.python-version`)

### Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   uv sync
   ```

### Development

- Activate the virtual environment: `uv shell`
- Install dependencies: `uv sync`
- Add a new dependency: `uv add package-name`
- Remove a dependency: `uv remove package-name`
- Run the application: `uv run python main.py`

### Project Structure

- `main.py` - Main application entry point (using bridge commands)
- `views.py` - Discord bot views/components
- `config.json` - Configuration file
- `pyproject.toml` - Project metadata and dependencies
- `requirements.txt` - Dependencies for uv 

## Nation registration

Registrants run `/register` to open a private, saved wizard covering every template section,
and `/registration_upload` to attach the flag, claim map and optional city map. Any field can
be saved partially. The first save opens a draft thread in the registration channel with a
status message listing what is still needed; it never pings anyone. Submitting is only allowed
once every required item is filled in, and that is what posts the full template and pings
staff once.

1. Staff click **Review and approve** in the thread, choose the tracker region and optional
   faith and continent roles, or request changes / reject with a reason.
2. The population approver gets a DM with **Assign population** (population and start year).
3. The bot creates the nation in wrp-pops, grants the player, temporary and system roles plus
   any group roles, and posts the result in the thread. The temporary role is removed after
   `TEMP_ROLE_DAYS`.
4. Proposed calendars go through the existing calendar approval flow independently.

Staff tools live under `/registrations` (`queue`, `status`, `retry`, `resend_population`,
`reopen_review`, `withdraw`, `link`, `release`). Administrators manage which roles staff can
grant with `roles_add`, `roles_remove` and `roles_list`.

Configuration is in `.env.example`. Set `WRP_POPS_URL` and `WRP_POPS_TOKEN` (equal to
`DISCORD_INTEGRATION_TOKEN` in wrp-pops). The bot needs Manage Roles (its role above every role
it grants), permission to create threads and attach files in the registration channel, and
permission to mention the staff role. Registration state is stored in `REGISTRATION_DB_PATH`
and uploads in `REGISTRATION_UPLOAD_DIR`; back both up.
