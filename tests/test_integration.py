import pytest
import json
import tempfile
import os
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime
import discord
from discord import Interaction, Client, User, ButtonStyle

# Import the modules to test
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from views import AddCalendar
from approval_views import ApprovalView, create_approval_embed

class TestCalendarApprovalIntegration:
    """Integration tests for the complete calendar approval workflow"""
    
    @pytest.fixture
    def temp_test_files(self):
        """Create temporary test files that won't affect real config"""
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
    
    @pytest.fixture
    def mock_discord_environment(self):
        """Create a complete mock Discord environment"""
        class MockDiscordEnv:
            def __init__(self):
                # Create mock interaction
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
                
                # Create mock client
                self.client = AsyncMock(spec=Client)
                self.client.fetch_user = AsyncMock()
                
                # Create mock user for DM
                self.user = AsyncMock(spec=User)
                self.user.id = 123456789
                self.user.display_name = "TestUser"
                self.user.send = AsyncMock()
                
                # Create mock approval user
                self.approval_user = AsyncMock(spec=User)
                self.approval_user.id = 322487124102479873
                self.approval_user.send = AsyncMock()
        
        return MockDiscordEnv()
    
    @pytest.mark.asyncio
    async def test_complete_approval_workflow_success(self, temp_test_files, mock_discord_environment):
        """Test the complete workflow: submit -> approve -> verify"""
        config_path, pending_path = temp_test_files
        env = mock_discord_environment
        
        # Step 1: Submit a calendar
        modal = AddCalendar()
        modal.name.value = "Integration Test Calendar"
        modal.key.value = "itc"
        modal.current_year.value = "500"
        modal.hours_per_year.value = "72"
        modal.is_staff_years.value = "N"
        
        # Mock file operations for submission
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
            env.interaction.response.send_message = AsyncMock()
            env.interaction.client.fetch_user = AsyncMock()
            env.interaction.channel.send = AsyncMock()
            
            # Submit the calendar
            await modal.on_submit(env.interaction)
            
            # Verify submission was successful
            env.interaction.response.send_message.assert_called_once()
            call_args = env.interaction.response.send_message.call_args
            message = call_args[0][0]
            assert "✅ Calendar submission **Integration Test Calendar** has been submitted for approval!" in message
        
        # Step 2: Create approval view and approve
        calendar_data = {
            "name": "Integration Test Calendar",
            "key": "itc",
            "hours_per_year": 72.0,
            "current_year": 500,
            "is_staff_years": False
        }
        
        approval_view = ApprovalView(
            submission_id="test-uuid-456",
            calendar_data=calendar_data,
            submitter_id=123456789
        )
        
        # Mock file operations for approval
        with patch('builtins.open') as mock_open:
            # Mock reading config
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "channel": 123456789,
                "calendars": []
            })
            
            # Mock reading pending data
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "pending_submissions": [
                    {
                        "submission_id": "test-uuid-456",
                        "submitter_id": 123456789,
                        "calendar_data": calendar_data
                    }
                ]
            })
            
            # Mock the interaction
            env.interaction.response.edit_message = AsyncMock()
            env.interaction.client.fetch_user = AsyncMock()
            
            # Approve the calendar
            await approval_view.approve_calendar(env.interaction, MagicMock())
            
            # Verify approval was successful
            env.interaction.response.edit_message.assert_called_once()
            call_args = env.interaction.response.edit_message.call_args
            embed = call_args[1]['embed']
            assert embed.title == "✅ Calendar Approved"
            assert "Integration Test Calendar" in embed.description
    
    @pytest.mark.asyncio
    async def test_complete_approval_workflow_denial(self, temp_test_files, mock_discord_environment):
        """Test the complete workflow: submit -> deny -> verify"""
        config_path, pending_path = temp_test_files
        env = mock_discord_environment
        
        # Step 1: Submit a calendar
        modal = AddCalendar()
        modal.name.value = "Denial Test Calendar"
        modal.key.value = "dtc"
        modal.current_year.value = "300"
        modal.hours_per_year.value = "48"
        modal.is_staff_years.value = "Y"
        
        # Mock file operations for submission
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
            env.interaction.response.send_message = AsyncMock()
            env.interaction.client.fetch_user = AsyncMock()
            env.interaction.channel.send = AsyncMock()
            
            # Submit the calendar
            await modal.on_submit(env.interaction)
            
            # Verify submission was successful
            env.interaction.response.send_message.assert_called_once()
        
        # Step 2: Create approval view and deny
        calendar_data = {
            "name": "Denial Test Calendar",
            "key": "dtc",
            "hours_per_year": 48.0,
            "current_year": 300,
            "is_staff_years": True
        }
        
        approval_view = ApprovalView(
            submission_id="test-uuid-789",
            calendar_data=calendar_data,
            submitter_id=123456789
        )
        
        # Mock file operations for denial
        with patch('builtins.open') as mock_open:
            # Mock reading pending data
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "pending_submissions": [
                    {
                        "submission_id": "test-uuid-789",
                        "submitter_id": 123456789,
                        "calendar_data": calendar_data
                    }
                ]
            })
            
            # Mock the interaction
            env.interaction.response.edit_message = AsyncMock()
            env.interaction.client.fetch_user = AsyncMock()
            
            # Deny the calendar
            await approval_view.deny_calendar(env.interaction, MagicMock())
            
            # Verify denial was successful
            env.interaction.response.edit_message.assert_called_once()
            call_args = env.interaction.response.edit_message.call_args
            embed = call_args[1]['embed']
            assert embed.title == "❌ Calendar Denied"
            assert "Denial Test Calendar" in embed.description
    
    @pytest.mark.asyncio
    async def test_dm_notification_workflow(self, mock_discord_environment):
        """Test DM notification workflow for both approval and denial"""
        env = mock_discord_environment
        
        calendar_data = {
            "name": "DM Test Calendar",
            "key": "dmc",
            "hours_per_year": 96.0,
            "current_year": 200,
            "is_staff_years": False
        }
        
        approval_view = ApprovalView(
            submission_id="test-uuid-dm",
            calendar_data=calendar_data,
            submitter_id=123456789
        )
        
        # Test approval notification
        env.client.fetch_user.return_value = env.user
        
        await approval_view._notify_submitter(env.client, "approved")
        
        # Verify DM was sent
        env.client.fetch_user.assert_called_once_with(123456789)
        env.user.send.assert_called_once()
        
        # Verify the embed content
        call_args = env.user.send.call_args
        embed = call_args[0][0]
        assert embed.title == "✅ Calendar Submission Approved"
        assert "DM Test Calendar" in embed.description
        assert embed.color == discord.Color.green()
        
        # Reset mocks
        env.client.fetch_user.reset_mock()
        env.user.send.reset_mock()
        
        # Test denial notification
        await approval_view._notify_submitter(env.client, "denied")
        
        # Verify DM was sent
        env.client.fetch_user.assert_called_once_with(123456789)
        env.user.send.assert_called_once()
        
        # Verify the embed content
        call_args = env.user.send.call_args
        embed = call_args[0][0]
        assert embed.title == "❌ Calendar Submission Denied"
        assert "DM Test Calendar" in embed.description
        assert embed.color == discord.Color.red()
    
    @pytest.mark.asyncio
    async def test_approval_embed_creation(self):
        """Test approval embed creation with various calendar types"""
        # Test regular calendar
        calendar_data = {
            "name": "Regular Calendar",
            "key": "rc",
            "hours_per_year": 96.0,
            "current_year": 100,
            "is_staff_years": False
        }
        
        embed = create_approval_embed(calendar_data, 123456789, "test-uuid")
        
        assert embed.title == "📅 New Calendar Submission"
        assert embed.color == discord.Color.blue()
        
        # Check fields
        field_names = [field.name for field in embed.fields]
        assert "Calendar Details" in field_names
        assert "Submitted by" in field_names
        assert "Submission ID" in field_names
        
        # Check calendar details
        details_field = next(f for f in embed.fields if f.name == "Calendar Details")
        assert "Regular Calendar" in details_field.value
        assert "rc" in details_field.value
        assert "100" in details_field.value
        assert "96.0" in details_field.value
        assert "No" in details_field.value  # Is Staff Years
        
        # Test staff years calendar
        staff_calendar_data = {
            "name": "Staff Years",
            "key": "sy",
            "hours_per_year": 96.0,
            "current_year": 527,
            "is_staff_years": True
        }
        
        staff_embed = create_approval_embed(staff_calendar_data, 123456789, "test-uuid")
        
        # Check staff years details
        staff_details_field = next(f for f in staff_embed.fields if f.name == "Calendar Details")
        assert "Yes" in staff_details_field.value  # Is Staff Years
    
    @pytest.mark.asyncio
    async def test_permission_checks(self, mock_discord_environment):
        """Test permission checks for approval and denial"""
        env = mock_discord_environment
        
        calendar_data = {
            "name": "Permission Test Calendar",
            "key": "ptc",
            "hours_per_year": 96.0,
            "current_year": 100,
            "is_staff_years": False
        }
        
        approval_view = ApprovalView(
            submission_id="test-uuid-perm",
            calendar_data=calendar_data,
            submitter_id=123456789
        )
        
        # Test approval without permission
        env.interaction.user.guild_permissions.moderate_members = False
        
        await approval_view.approve_calendar(env.interaction, MagicMock())
        
        env.interaction.response.send_message.assert_called_once_with(
            "You don't have permission to approve calendar submissions.",
            ephemeral=True
        )
        
        # Reset mock
        env.interaction.response.send_message.reset_mock()
        
        # Test denial without permission
        await approval_view.deny_calendar(env.interaction, MagicMock())
        
        env.interaction.response.send_message.assert_called_once_with(
            "You don't have permission to deny calendar submissions.",
            ephemeral=True
        )
    
    @pytest.mark.asyncio
    async def test_duplicate_prevention_integration(self, temp_test_files, mock_discord_environment):
        """Test duplicate prevention in the full workflow"""
        config_path, pending_path = temp_test_files
        env = mock_discord_environment
        
        # Set up existing calendar in config
        existing_config = {
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
        
        # Test duplicate name
        modal = AddCalendar()
        modal.name.value = "Existing Calendar"  # Duplicate name
        modal.key.value = "new_key"
        modal.current_year.value = "200"
        modal.hours_per_year.value = "48"
        modal.is_staff_years.value = "N"
        
        with patch('builtins.open') as mock_open:
            # Mock reading config with existing calendar
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(existing_config)
            
            await modal.on_submit(env.interaction)
            
            env.interaction.response.send_message.assert_called_once_with(
                "A calendar with the name 'Existing Calendar' already exists.",
                ephemeral=True
            )
        
        # Reset mock
        env.interaction.response.send_message.reset_mock()
        
        # Test duplicate key
        modal.name.value = "New Calendar"
        modal.key.value = "ec"  # Duplicate key
        
        with patch('builtins.open') as mock_open:
            # Mock reading config with existing calendar
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(existing_config)
            
            await modal.on_submit(env.interaction)
            
            env.interaction.response.send_message.assert_called_once_with(
                "A calendar with the key 'ec' already exists.",
                ephemeral=True
            ) 