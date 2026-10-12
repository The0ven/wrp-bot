import pytest
import json

# test_views.py imports a TextStyle symbol missing from the installed py-cord build,
# which aborts collection of the entire suite.
collect_ignore = ["test_views.py"]
import tempfile
import os
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
import discord
from discord import Interaction, Client, User, Guild, Member, PermissionOverwrite
from discord import ChannelType

@pytest.fixture
def temp_config_file():
    """Create a temporary config.json file for testing"""
    config_data = {
        "channel": 123456789,
        "calendars": [
            {
                "name": "Test Calendar",
                "key": "tc",
                "hours_per_year": 96,
                "current_year": 100,
                "is_staff_years": False
            }
        ]
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(config_data, f)
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    os.unlink(temp_path)

@pytest.fixture
def temp_pending_file():
    """Create a temporary pending_calendars.json file for testing"""
    pending_data = {
        "pending_submissions": []
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(pending_data, f)
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    os.unlink(temp_path)

@pytest.fixture
def mock_interaction():
    """Create a mock Discord interaction for testing"""
    interaction = AsyncMock(spec=Interaction)
    interaction.user = AsyncMock(spec=User)
    interaction.user.id = 123456789
    interaction.user.display_name = "TestUser"
    interaction.user.mention = "<@123456789>"
    interaction.user.guild_permissions.moderate_members = True
    interaction.response = AsyncMock()
    interaction.channel = AsyncMock()
    interaction.channel.send = AsyncMock()
    interaction.client = AsyncMock(spec=Client)
    interaction.client.fetch_user = AsyncMock()
    return interaction

@pytest.fixture
def mock_client():
    """Create a mock Discord client for testing"""
    client = AsyncMock(spec=Client)
    client.fetch_user = AsyncMock()
    return client

@pytest.fixture
def mock_user():
    """Create a mock Discord user for testing"""
    user = AsyncMock(spec=User)
    user.id = 123456789
    user.display_name = "TestUser"
    user.send = AsyncMock()
    return user

@pytest.fixture
def mock_guild():
    """Create a mock Discord guild for testing"""
    guild = AsyncMock(spec=Guild)
    guild.id = 987654321
    return guild

@pytest.fixture
def mock_member():
    """Create a mock Discord member for testing"""
    member = AsyncMock(spec=Member)
    member.id = 123456789
    member.display_name = "TestUser"
    member.guild_permissions.moderate_members = True
    return member

@pytest.fixture
def sample_calendar_data():
    """Sample calendar data for testing"""
    return {
        "name": "Test Calendar",
        "key": "tc",
        "hours_per_year": 96.0,
        "current_year": 100,
        "is_staff_years": False
    }

@pytest.fixture
def sample_pending_submission(sample_calendar_data):
    """Sample pending submission data for testing"""
    return {
        "submission_id": "test-uuid-123",
        "submitter_id": 123456789,
        "submitter_name": "TestUser",
        "submission_timestamp": datetime.now().isoformat(),
        "calendar_data": sample_calendar_data
    }

@pytest.fixture
def mock_discord_objects():
    """Create all necessary Discord mock objects for testing"""
    class MockDiscordObjects:
        def __init__(self):
            self.interaction = AsyncMock(spec=Interaction)
            self.interaction.user = AsyncMock(spec=User)
            self.interaction.user.id = 123456789
            self.interaction.user.display_name = "TestUser"
            self.interaction.user.mention = "<@123456789>"
            self.interaction.user.guild_permissions.moderate_members = True
            self.interaction.response = AsyncMock()
            self.interaction.channel = AsyncMock()
            self.interaction.channel.send = AsyncMock()
            self.interaction.client = AsyncMock(spec=Client)
            self.interaction.client.fetch_user = AsyncMock()
            
            self.client = AsyncMock(spec=Client)
            self.client.fetch_user = AsyncMock()
            
            self.user = AsyncMock(spec=User)
            self.user.id = 123456789
            self.user.display_name = "TestUser"
            self.user.send = AsyncMock()
            
            self.guild = AsyncMock(spec=Guild)
            self.guild.id = 987654321
            
            self.member = AsyncMock(spec=Member)
            self.member.id = 123456789
            self.member.display_name = "TestUser"
            self.member.guild_permissions.moderate_members = True
    
    return MockDiscordObjects()

@pytest.fixture
def test_config():
    """Test configuration data"""
    return {
        "channel": 123456789,
        "calendars": [
            {
                "name": "Staff Years",
                "key": "sy",
                "hours_per_year": 96,
                "current_year": 527,
                "is_staff_years": True
            },
            {
                "name": "Test Calendar",
                "key": "tc",
                "hours_per_year": 48,
                "current_year": 100,
                "is_staff_years": False
            }
        ]
    } 
