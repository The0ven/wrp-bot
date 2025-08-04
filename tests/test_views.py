import pytest
import json
import tempfile
import os
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime
import discord
from discord import Interaction, Client, User, TextStyle

# Import the modules to test
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from views import AddCalendar

class TestAddCalendar:
    """Test cases for AddCalendar modal"""
    
    @pytest.fixture
    def add_calendar_modal(self):
        """Create an AddCalendar modal instance for testing"""
        return AddCalendar()
    
    @pytest.fixture
    def temp_files(self):
        """Create temporary config and pending files"""
        # Create temp config file
        config_data = {
            "channel": 123456789,
            "calendars": [
                {
                    "name": "Existing Calendar",
                    "key": "ec",
                    "hours_per_year": 96,
                    "current_year": 100,
                    "is_staff_years": False
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = f.name
        
        # Create temp pending file
        pending_data = {
            "pending_submissions": []
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(pending_data, f)
            pending_path = f.name
        
        yield config_path, pending_path
        
        # Cleanup
        os.unlink(config_path)
        os.unlink(pending_path)
    
    def test_modal_initialization(self, add_calendar_modal):
        """Test AddCalendar modal initialization"""
        assert add_calendar_modal.title == "Create/Update Calendar"
        assert hasattr(add_calendar_modal, 'name')
        assert hasattr(add_calendar_modal, 'key')
        assert hasattr(add_calendar_modal, 'current_year')
        assert hasattr(add_calendar_modal, 'hours_per_year')
        assert hasattr(add_calendar_modal, 'is_staff_years')
        
        # Check text input properties
        assert isinstance(add_calendar_modal.name, discord.ui.TextInput)
        assert isinstance(add_calendar_modal.key, discord.ui.TextInput)
        assert isinstance(add_calendar_modal.current_year, discord.ui.TextInput)
        assert isinstance(add_calendar_modal.hours_per_year, discord.ui.TextInput)
        assert isinstance(add_calendar_modal.is_staff_years, discord.ui.TextInput)
    
    @pytest.mark.asyncio
    async def test_on_submit_success(self, add_calendar_modal, temp_files, mock_interaction):
        """Test successful calendar submission"""
        config_path, pending_path = temp_files
        
        # Set up modal values
        add_calendar_modal.name.value = "New Test Calendar"
        add_calendar_modal.key.value = "ntc"
        add_calendar_modal.current_year.value = "200"
        add_calendar_modal.hours_per_year.value = "48"
        add_calendar_modal.is_staff_years.value = "N"
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading config
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "channel": 123456789,
                "calendars": []
            })
            
            # Mock reading pending data
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "pending_submissions": []
            })
            
            # Mock the interaction
            mock_interaction.response.send_message = AsyncMock()
            mock_interaction.client.fetch_user = AsyncMock()
            mock_interaction.channel.send = AsyncMock()
            
            # Test submission
            await add_calendar_modal.on_submit(mock_interaction)
            
            # Verify success message was sent
            mock_interaction.response.send_message.assert_called_once()
            call_args = mock_interaction.response.send_message.call_args
            message = call_args[0][0]  # First argument should be the message
            assert "✅ Calendar submission **New Test Calendar** has been submitted for approval!" in message
            assert "New Test Calendar" in message
            assert "ntc" in message
            assert "200" in message
            assert "48" in message
            assert "No" in message  # Is Staff Years
    
    @pytest.mark.asyncio
    async def test_on_submit_empty_name(self, add_calendar_modal, mock_interaction):
        """Test submission rejection due to empty name"""
        add_calendar_modal.name.value = ""
        add_calendar_modal.key.value = "test"
        add_calendar_modal.current_year.value = "100"
        add_calendar_modal.hours_per_year.value = "96"
        add_calendar_modal.is_staff_years.value = "N"
        
        await add_calendar_modal.on_submit(mock_interaction)
        
        mock_interaction.response.send_message.assert_called_once_with(
            "Calendar name cannot be empty.",
            ephemeral=True
        )
    
    @pytest.mark.asyncio
    async def test_on_submit_empty_key(self, add_calendar_modal, mock_interaction):
        """Test submission rejection due to empty key"""
        add_calendar_modal.name.value = "Test Calendar"
        add_calendar_modal.key.value = ""
        add_calendar_modal.current_year.value = "100"
        add_calendar_modal.hours_per_year.value = "96"
        add_calendar_modal.is_staff_years.value = "N"
        
        await add_calendar_modal.on_submit(mock_interaction)
        
        mock_interaction.response.send_message.assert_called_once_with(
            "Calendar key cannot be empty.",
            ephemeral=True
        )
    
    @pytest.mark.asyncio
    async def test_on_submit_duplicate_name(self, add_calendar_modal, temp_files, mock_interaction):
        """Test submission rejection due to duplicate calendar name"""
        config_path, pending_path = temp_files
        
        add_calendar_modal.name.value = "Existing Calendar"  # Duplicate name
        add_calendar_modal.key.value = "new_key"
        add_calendar_modal.current_year.value = "100"
        add_calendar_modal.hours_per_year.value = "96"
        add_calendar_modal.is_staff_years.value = "N"
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading config with existing calendar
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "channel": 123456789,
                "calendars": [
                    {
                        "name": "Existing Calendar",
                        "key": "ec",
                        "hours_per_year": 96,
                        "current_year": 100,
                        "is_staff_years": False
                    }
                ]
            })
            
            await add_calendar_modal.on_submit(mock_interaction)
            
            mock_interaction.response.send_message.assert_called_once_with(
                "A calendar with the name 'Existing Calendar' already exists.",
                ephemeral=True
            )
    
    @pytest.mark.asyncio
    async def test_on_submit_duplicate_key(self, add_calendar_modal, temp_files, mock_interaction):
        """Test submission rejection due to duplicate calendar key"""
        config_path, pending_path = temp_files
        
        add_calendar_modal.name.value = "New Calendar"
        add_calendar_modal.key.value = "ec"  # Duplicate key
        add_calendar_modal.current_year.value = "100"
        add_calendar_modal.hours_per_year.value = "96"
        add_calendar_modal.is_staff_years.value = "N"
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading config with existing calendar
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "channel": 123456789,
                "calendars": [
                    {
                        "name": "Existing Calendar",
                        "key": "ec",
                        "hours_per_year": 96,
                        "current_year": 100,
                        "is_staff_years": False
                    }
                ]
            })
            
            await add_calendar_modal.on_submit(mock_interaction)
            
            mock_interaction.response.send_message.assert_called_once_with(
                "A calendar with the key 'ec' already exists.",
                ephemeral=True
            )
    
    @pytest.mark.asyncio
    async def test_on_submit_invalid_hours_per_year(self, add_calendar_modal, temp_files, mock_interaction):
        """Test submission rejection due to invalid hours per year"""
        config_path, pending_path = temp_files
        
        add_calendar_modal.name.value = "Test Calendar"
        add_calendar_modal.key.value = "tc"
        add_calendar_modal.current_year.value = "100"
        add_calendar_modal.hours_per_year.value = "invalid"
        add_calendar_modal.is_staff_years.value = "N"
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading config
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "channel": 123456789,
                "calendars": []
            })
            
            await add_calendar_modal.on_submit(mock_interaction)
            
            mock_interaction.response.send_message.assert_called_once_with(
                "Hours per year must be a valid number.",
                ephemeral=True
            )
    
    @pytest.mark.asyncio
    async def test_on_submit_negative_hours_per_year(self, add_calendar_modal, temp_files, mock_interaction):
        """Test submission rejection due to negative hours per year"""
        config_path, pending_path = temp_files
        
        add_calendar_modal.name.value = "Test Calendar"
        add_calendar_modal.key.value = "tc"
        add_calendar_modal.current_year.value = "100"
        add_calendar_modal.hours_per_year.value = "-10"
        add_calendar_modal.is_staff_years.value = "N"
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading config
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "channel": 123456789,
                "calendars": []
            })
            
            await add_calendar_modal.on_submit(mock_interaction)
            
            mock_interaction.response.send_message.assert_called_once_with(
                "Hours per year must be a positive number.",
                ephemeral=True
            )
    
    @pytest.mark.asyncio
    async def test_on_submit_invalid_current_year(self, add_calendar_modal, temp_files, mock_interaction):
        """Test submission rejection due to invalid current year"""
        config_path, pending_path = temp_files
        
        add_calendar_modal.name.value = "Test Calendar"
        add_calendar_modal.key.value = "tc"
        add_calendar_modal.current_year.value = "invalid"
        add_calendar_modal.hours_per_year.value = "96"
        add_calendar_modal.is_staff_years.value = "N"
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading config
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "channel": 123456789,
                "calendars": []
            })
            
            await add_calendar_modal.on_submit(mock_interaction)
            
            mock_interaction.response.send_message.assert_called_once_with(
                "Current year must be a valid integer.",
                ephemeral=True
            )
    
    @pytest.mark.asyncio
    async def test_on_submit_negative_current_year(self, add_calendar_modal, temp_files, mock_interaction):
        """Test submission rejection due to negative current year"""
        config_path, pending_path = temp_files
        
        add_calendar_modal.name.value = "Test Calendar"
        add_calendar_modal.key.value = "tc"
        add_calendar_modal.current_year.value = "-10"
        add_calendar_modal.hours_per_year.value = "96"
        add_calendar_modal.is_staff_years.value = "N"
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading config
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "channel": 123456789,
                "calendars": []
            })
            
            await add_calendar_modal.on_submit(mock_interaction)
            
            mock_interaction.response.send_message.assert_called_once_with(
                "Current year must be a non-negative number.",
                ephemeral=True
            )
    
    @pytest.mark.asyncio
    async def test_on_submit_invalid_staff_years(self, add_calendar_modal, temp_files, mock_interaction):
        """Test submission rejection due to invalid staff years input"""
        config_path, pending_path = temp_files
        
        add_calendar_modal.name.value = "Test Calendar"
        add_calendar_modal.key.value = "tc"
        add_calendar_modal.current_year.value = "100"
        add_calendar_modal.hours_per_year.value = "96"
        add_calendar_modal.is_staff_years.value = "maybe"
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading config
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "channel": 123456789,
                "calendars": []
            })
            
            await add_calendar_modal.on_submit(mock_interaction)
            
            mock_interaction.response.send_message.assert_called_once_with(
                "Is Staff Years must be Y/N, Yes/No.",
                ephemeral=True
            )
    
    @pytest.mark.asyncio
    async def test_on_submit_staff_years_yes(self, add_calendar_modal, temp_files, mock_interaction):
        """Test successful submission with staff years set to yes"""
        config_path, pending_path = temp_files
        
        add_calendar_modal.name.value = "Staff Calendar"
        add_calendar_modal.key.value = "sc"
        add_calendar_modal.current_year.value = "100"
        add_calendar_modal.hours_per_year.value = "96"
        add_calendar_modal.is_staff_years.value = "Y"
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading config
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "channel": 123456789,
                "calendars": []
            })
            
            # Mock reading pending data
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "pending_submissions": []
            })
            
            # Mock the interaction
            mock_interaction.response.send_message = AsyncMock()
            mock_interaction.client.fetch_user = AsyncMock()
            mock_interaction.channel.send = AsyncMock()
            
            # Test submission
            await add_calendar_modal.on_submit(mock_interaction)
            
            # Verify success message was sent
            mock_interaction.response.send_message.assert_called_once()
            call_args = mock_interaction.response.send_message.call_args
            message = call_args[0][0]  # First argument should be the message
            assert "Yes" in message  # Is Staff Years should be Yes
    
    @pytest.mark.asyncio
    async def test_on_submit_staff_years_no(self, add_calendar_modal, temp_files, mock_interaction):
        """Test successful submission with staff years set to no"""
        config_path, pending_path = temp_files
        
        add_calendar_modal.name.value = "Regular Calendar"
        add_calendar_modal.key.value = "rc"
        add_calendar_modal.current_year.value = "100"
        add_calendar_modal.hours_per_year.value = "96"
        add_calendar_modal.is_staff_years.value = "N"
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading config
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "channel": 123456789,
                "calendars": []
            })
            
            # Mock reading pending data
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "pending_submissions": []
            })
            
            # Mock the interaction
            mock_interaction.response.send_message = AsyncMock()
            mock_interaction.client.fetch_user = AsyncMock()
            mock_interaction.channel.send = AsyncMock()
            
            # Test submission
            await add_calendar_modal.on_submit(mock_interaction)
            
            # Verify success message was sent
            mock_interaction.response.send_message.assert_called_once()
            call_args = mock_interaction.response.send_message.call_args
            message = call_args[0][0]  # First argument should be the message
            assert "No" in message  # Is Staff Years should be No 