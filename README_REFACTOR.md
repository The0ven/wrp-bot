# WRP Bot - Refactored Version

This is a refactored version of the WRP Bot that uses modern pycord syntax and Cogs for better organization.

## Structure

```
wrp-bot/
├── main.py                 # Main entry point
├── cogs/                   # Command cogs
│   ├── __init__.py
│   ├── calendar_cog.py     # Calendar management commands
│   ├── admin_cog.py        # Administrative commands
│   └── query_cog.py        # Calendar querying commands
├── tasks/                  # Background tasks
│   ├── __init__.py
│   └── new_year_task.py    # New year calculation task
├── views.py                # UI components (updated syntax)
├── approval_views.py       # Approval system (updated syntax)
├── config.json             # Configuration file
├── history.jsonl           # Calendar history
└── pending_calendars.json  # Pending calendar submissions
```

## Key Changes

### 1. Modern Pycord Syntax
- Updated all imports to use modern pycord syntax
- Removed deprecated `Interaction[Client]` type hints
- Updated UI component syntax

### 2. Cog-based Architecture
- **CalendarCog**: Handles calendar configuration and management
  - `/configure` - Initialize calendar tracking
  - `/add_calendar` - Add a new calendar
  - `/list_calendars` - List all configured calendars

- **AdminCog**: Handles administrative functions
  - `/pending_calendars` - View pending submissions
  - `/test_approval` - Test the approval system
  - `/clear_pending` - Clear all pending submissions

- **QueryCog**: Handles calendar queries
  - `/when` - Get calendar year for a specific date

### 3. Separated Background Tasks
- **NewYearTask**: Handles the periodic new year calculations
- Runs every 30 minutes
- Automatically posts new year announcements

## Running the Bot

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up your environment variables:
```bash
# Create a .env file
TOKEN=your_discord_bot_token_here
```

3. Run the bot:
```bash
python main.py
```

## Commands

### Calendar Management
- `/configure` - Initialize calendar tracking (requires manage_channels permission)
- `/add_calendar` - Add a new calendar (requires moderate_members permission)
- `/list_calendars` - List all configured calendars

### Administrative
- `/pending_calendars` - View pending calendar submissions (requires moderate_members permission)
- `/test_approval` - Test the approval system (requires moderate_members permission)
- `/clear_pending` - Clear all pending submissions (requires moderate_members permission)

### Queries
- `/when <date> [calendar]` - Get calendar year for a specific date

## Benefits of the Refactored Structure

1. **Better Organization**: Commands are grouped by functionality
2. **Easier Maintenance**: Each cog can be modified independently
3. **Modern Syntax**: Uses current pycord best practices
4. **Scalability**: Easy to add new cogs and commands
5. **Separation of Concerns**: Background tasks are separate from commands

## Migration from Old Version

The refactored version maintains all the same functionality as the original `app.py` but with better organization. The main changes are:

- Commands are now organized into cogs
- Background tasks are separated into their own module
- Updated to use modern pycord syntax
- Better error handling and type hints

All existing configuration files (`config.json`, `history.jsonl`, `pending_calendars.json`) remain compatible. 