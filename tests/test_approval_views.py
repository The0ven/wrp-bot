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

from approval_views import ApprovalView, create_approval_embed

class TestApprovalView:
    """Test cases for ApprovalView class"""
    
    @pytest.fixture
    def approval_view(self, sample_calendar_data):
        """Create an ApprovalView instance for testing"""
        return ApprovalView(
            submission_id="test-uuid-123",
            calendar_data=sample_calendar_data,
            submitter_id=123456789
        )
    
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
            "pending_submissions": [
                {
                    "submission_id": "test-uuid-123",
                    "submitter_id": 123456789,
                    "submitter_name": "TestUser",
                    "submission_timestamp": datetime.now().isoformat(),
                    "calendar_data": {
                        "name": "Test Calendar",
                        "key": "tc",
                        "hours_per_year": 96.0,
                        "current_year": 100,
                        "is_staff_years": False
                    }
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(pending_data, f)
            pending_path = f.name
        
        yield config_path, pending_path
        
        # Cleanup
        os.unlink(config_path)
        os.unlink(pending_path)
    
    def test_approval_view_initialization(self, approval_view, sample_calendar_data):
        """Test ApprovalView initialization"""
        assert approval_view.submission_id == "test-uuid-123"
        assert approval_view.calendar_data == sample_calendar_data
        assert approval_view.submitter_id == 123456789
        assert approval_view.timeout is None  # No timeout for approval buttons
    
    def test_format_calendar_details(self, approval_view):
        """Test calendar details formatting"""
        details = approval_view._format_calendar_details()
        expected = (
            "**Name:** Test Calendar\n"
            "**Key:** tc\n"
            "**Current Year:** 100\n"
            "**Hours Per Year:** 96.0\n"
            "**Is Staff Years:** No"
        )
        assert details == expected
    
    @pytest.mark.asyncio
    async def test_approve_calendar_success(self, approval_view, temp_files, mock_interaction):
        """Test successful calendar approval"""
        config_path, pending_path = temp_files
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading config
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "channel": 123456789,
                "calendars": []
            })
            
            # Mock the interaction
            mock_interaction.user.guild_permissions.moderate_members = True
            mock_interaction.response.edit_message = AsyncMock()
            mock_interaction.client.fetch_user = AsyncMock()
            
            # Test approval
            await approval_view.approve_calendar(mock_interaction, MagicMock())
            
            # Verify edit_message was called
            mock_interaction.response.edit_message.assert_called_once()
            
            # Verify the embed was created correctly
            call_args = mock_interaction.response.edit_message.call_args
            embed = call_args[1]['embed']
            assert embed.title == "✅ Calendar Approved"
            assert "Test Calendar" in embed.description
            assert embed.color == discord.Color.green()
    
    @pytest.mark.asyncio
    async def test_approve_calendar_no_permission(self, approval_view, mock_interaction):
        """Test approval rejection due to insufficient permissions"""
        mock_interaction.user.guild_permissions.moderate_members = False
        
        await approval_view.approve_calendar(mock_interaction, MagicMock())
        
        mock_interaction.response.send_message.assert_called_once_with(
            "You don't have permission to approve calendar submissions.",
            ephemeral=True
        )
    
    @pytest.mark.asyncio
    async def test_deny_calendar_success(self, approval_view, temp_files, mock_interaction):
        """Test successful calendar denial"""
        config_path, pending_path = temp_files
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading pending data
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "pending_submissions": []
            })
            
            # Mock the interaction
            mock_interaction.user.guild_permissions.moderate_members = True
            mock_interaction.response.edit_message = AsyncMock()
            mock_interaction.client.fetch_user = AsyncMock()
            
            # Test denial
            await approval_view.deny_calendar(mock_interaction, MagicMock())
            
            # Verify edit_message was called
            mock_interaction.response.edit_message.assert_called_once()
            
            # Verify the embed was created correctly
            call_args = mock_interaction.response.edit_message.call_args
            embed = call_args[1]['embed']
            assert embed.title == "❌ Calendar Denied"
            assert "Test Calendar" in embed.description
            assert embed.color == discord.Color.red()
    
    @pytest.mark.asyncio
    async def test_deny_calendar_no_permission(self, approval_view, mock_interaction):
        """Test denial rejection due to insufficient permissions"""
        mock_interaction.user.guild_permissions.moderate_members = False
        
        await approval_view.deny_calendar(mock_interaction, MagicMock())
        
        mock_interaction.response.send_message.assert_called_once_with(
            "You don't have permission to deny calendar submissions.",
            ephemeral=True
        )
    
    @pytest.mark.asyncio
    async def test_remove_from_pending_success(self, approval_view, temp_files):
        """Test successful removal from pending submissions"""
        config_path, pending_path = temp_files
        
        # Mock file operations
        with patch('builtins.open') as mock_open:
            # Mock reading pending data
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "pending_submissions": [
                    {
                        "submission_id": "test-uuid-123",
                        "submitter_id": 123456789,
                        "calendar_data": {"name": "Test"}
                    },
                    {
                        "submission_id": "other-uuid",
                        "submitter_id": 987654321,
                        "calendar_data": {"name": "Other"}
                    }
                ]
            })
            
            await approval_view._remove_from_pending()
            
            # Verify file was opened for writing
            assert mock_open.call_count >= 2  # At least read and write
    
    @pytest.mark.asyncio
    async def test_notify_submitter_approved(self, approval_view, mock_client):
        """Test DM notification for approved submission"""
        # Mock user fetch
        mock_user = AsyncMock()
        mock_user.send = AsyncMock()
        mock_client.fetch_user.return_value = mock_user
        
        await approval_view._notify_submitter(mock_client, "approved")
        
        # Verify user was fetched and DM was sent
        mock_client.fetch_user.assert_called_once_with(123456789)
        mock_user.send.assert_called_once()
        
        # Verify the embed was created correctly
        call_args = mock_user.send.call_args
        embed = call_args[0][0]  # First argument should be the embed
        assert embed.title == "✅ Calendar Submission Approved"
        assert "Test Calendar" in embed.description
        assert embed.color == discord.Color.green()
    
    @pytest.mark.asyncio
    async def test_notify_submitter_denied(self, approval_view, mock_client):
        """Test DM notification for denied submission"""
        # Mock user fetch
        mock_user = AsyncMock()
        mock_user.send = AsyncMock()
        mock_client.fetch_user.return_value = mock_user
        
        await approval_view._notify_submitter(mock_client, "denied")
        
        # Verify user was fetched and DM was sent
        mock_client.fetch_user.assert_called_once_with(123456789)
        mock_user.send.assert_called_once()
        
        # Verify the embed was created correctly
        call_args = mock_user.send.call_args
        embed = call_args[0][0]  # First argument should be the embed
        assert embed.title == "❌ Calendar Submission Denied"
        assert "Test Calendar" in embed.description
        assert embed.color == discord.Color.red()
    
    @pytest.mark.asyncio
    async def test_notify_submitter_user_not_found(self, approval_view, mock_client):
        """Test DM notification when user cannot be fetched"""
        mock_client.fetch_user.return_value = None
        
        # Should not raise an exception
        await approval_view._notify_submitter(mock_client, "approved")
        
        # Verify user was fetched but no DM was sent
        mock_client.fetch_user.assert_called_once_with(123456789)

class TestCreateApprovalEmbed:
    """Test cases for create_approval_embed function"""
    
    def test_create_approval_embed(self, sample_calendar_data):
        """Test approval embed creation"""
        embed = create_approval_embed(sample_calendar_data, 123456789, "test-uuid-123")
        
        assert embed.title == "📅 New Calendar Submission"
        assert "A new calendar has been submitted and requires approval." in embed.description
        assert embed.color == discord.Color.blue()
        
        # Check fields
        field_names = [field.name for field in embed.fields]
        assert "Calendar Details" in field_names
        assert "Submitted by" in field_names
        assert "Submission ID" in field_names
        
        # Check calendar details field
        details_field = next(f for f in embed.fields if f.name == "Calendar Details")
        assert "Test Calendar" in details_field.value
        assert "tc" in details_field.value
        assert "100" in details_field.value
        assert "96.0" in details_field.value
        assert "No" in details_field.value  # Is Staff Years
    
    def test_create_approval_embed_staff_years(self):
        """Test approval embed creation for staff years calendar"""
        calendar_data = {
            "name": "Staff Years",
            "key": "sy",
            "hours_per_year": 96.0,
            "current_year": 527,
            "is_staff_years": True
        }
        
        embed = create_approval_embed(calendar_data, 123456789, "test-uuid-123")
        
        # Check calendar details field
        details_field = next(f for f in embed.fields if f.name == "Calendar Details")
        assert "Yes" in details_field.value  # Is Staff Years 