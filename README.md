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