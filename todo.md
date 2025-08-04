# WRP Bot Refactoring Todo List

## Phase 1: Core Functionality & Approval System

### 1. Calendar Approval System ✅ COMPLETED & INTEGRATED
- [x] **Create pending_calendars.json structure**
  - [x] Design JSON schema for pending calendar submissions
  - [x] Include submission timestamp, user info, and calendar details
  - [x] Add unique ID for each pending submission

- [x] **Modify AddCalendar modal in views.py**
  - [x] Change submission flow to save to pending_calendars.json instead of config.json
  - [x] Add validation for calendar key uniqueness
  - [x] Add success message indicating approval is pending
  - [x] Store submitter's user ID for tracking

- [x] **Create approval_views.py**
  - [x] Create ApprovalView class with approve/deny buttons
  - [x] Add calendar details display in approval message
  - [x] Implement approve_callback to move calendar to config.json
  - [x] Implement deny_callback to remove from pending and notify user
  - [x] Add confirmation dialogs for approve/deny actions

- [x] **Implement DM notification system**
  - [x] Create function to send DM to user 322487124102479873
  - [x] Format calendar details in readable message
  - [x] Attach ApprovalView to DM message
  - [x] Handle DM permission errors gracefully

- [x] **Additional Features Added**
  - [x] Added `/pending_calendars` command for moderators to view pending submissions
  - [x] Comprehensive input validation for all calendar fields
  - [x] Duplicate prevention for calendar names and keys
  - [x] Permission-based approval system (moderate_members required)
  - [x] Audit trail with submission metadata

- [x] **Comprehensive Testing Suite**
  - [x] Unit tests for ApprovalView class and approval logic
  - [x] Unit tests for AddCalendar modal and validation
  - [x] Integration tests for complete approval workflow
  - [x] Mock Discord environment for testing without Discord connection
  - [x] Safe testing that never writes to real config.json
  - [x] Test runner script with coverage reporting
  - [x] Pytest configuration integrated into pyproject.toml
  - [x] Optional test dependencies for clean installation

- [x] **Full Integration into app.py**
  - [x] Automatic initialization of pending_calendars.json
  - [x] Enhanced error handling for approval system
  - [x] Test commands for approval system verification
  - [x] Calendar management commands (list, clear pending)
  - [x] Seamless integration with existing bot functionality

### 2. Fix /when Command Accuracy
- [ ] **Create date_calculator.py module**
  - [ ] Implement accurate date interpolation between historical points
  - [ ] Add proper handling for future dates and dates before recording
  - [ ] Create function to calculate calendar years for any given timestamp
  - [ ] Add validation for date input format (YYYY-MM-DD)

- [ ] **Improve /when command in app.py**
  - [ ] Replace current date calculation logic with new date_calculator functions
  - [ ] Add proper error handling for invalid dates
  - [ ] Improve response formatting for better readability
  - [ ] Add support for partial dates (just year, etc.)

- [ ] **Add edge case handling**
  - [ ] Handle dates before first recorded entry
  - [ ] Handle future dates with appropriate messaging
  - [ ] Handle missing calendar data gracefully
  - [ ] Add timezone considerations if needed

## Phase 2: Code Modularization

### 3. Create calendar_manager.py
- [ ] **Calendar data operations**
  - [ ] Move calendar CRUD operations from app.py
  - [ ] Create functions for adding, updating, removing calendars
  - [ ] Add validation for calendar configuration data
  - [ ] Implement calendar key uniqueness checking

- [ ] **History data operations**
  - [ ] Move history.jsonl operations from app.py
  - [ ] Create functions for reading/writing history data
  - [ ] Add data validation for history entries
  - [ ] Implement efficient data querying functions

### 4. Create config_manager.py
- [ ] **Configuration file operations**
  - [ ] Centralize all config.json operations
  - [ ] Add configuration validation
  - [ ] Implement backup/restore functionality
  - [ ] Add configuration migration support

- [ ] **Configuration utilities**
  - [ ] Create functions to get/set specific config values
  - [ ] Add configuration schema validation
  - [ ] Implement configuration reload functionality

### 5. Create approval_system.py
- [ ] **Approval workflow management**
  - [ ] Centralize all approval-related operations
  - [ ] Create functions for pending calendar management
  - [ ] Add approval history tracking
  - [ ] Implement notification system for approvals/denials

- [ ] **Approval utilities**
  - [ ] Create functions to format approval messages
  - [ ] Add approval status checking
  - [ ] Implement cleanup for old pending submissions

## Phase 3: Error Handling & Validation

### 6. Comprehensive Error Handling
- [ ] **File I/O error handling**
  - [ ] Add try-catch blocks for all file operations
  - [ ] Implement graceful fallbacks for missing files
  - [ ] Add file corruption detection and recovery
  - [ ] Create backup systems for critical data

- [ ] **Discord API error handling**
  - [ ] Handle rate limiting gracefully
  - [ ] Add retry logic for failed API calls
  - [ ] Handle permission errors for DMs and channels
  - [ ] Add user-friendly error messages

- [ ] **Data validation**
  - [ ] Validate all user inputs
  - [ ] Add schema validation for JSON data
  - [ ] Implement data type checking
  - [ ] Add range validation for numeric values

### 7. Input Validation
- [ ] **Calendar submission validation**
  - [ ] Validate calendar name format and length
  - [ ] Check calendar key format and uniqueness
  - [ ] Validate hours_per_year range (positive numbers)
  - [ ] Validate current_year format and range

- [ ] **Date input validation**
  - [ ] Validate date format (YYYY-MM-DD)
  - [ ] Check date ranges (not too far in past/future)
  - [ ] Handle various date input formats
  - [ ] Add helpful error messages for invalid inputs

## Phase 4: Code Quality & Testing

### 8. Add Type Hints
- [ ] **Add type hints to all functions**
  - [ ] Import typing module
  - [ ] Add parameter type hints
  - [ ] Add return type hints
  - [ ] Add type hints for class attributes

- [ ] **Create type definitions**
  - [ ] Define custom types for calendar data
  - [ ] Define types for configuration data
  - [ ] Define types for history data
  - [ ] Create type aliases for common patterns

### 9. Implement Logging
- [ ] **Set up logging system**
  - [ ] Configure logging levels and format
  - [ ] Add file and console logging
  - [ ] Create log rotation system
  - [ ] Add structured logging for better debugging

- [ ] **Add logging throughout codebase**
  - [ ] Log all major operations
  - [ ] Log errors with full context
  - [ ] Log user actions for audit trail
  - [ ] Add performance logging for slow operations

### 10. Add Documentation
- [ ] **Add docstrings**
  - [ ] Document all functions and classes
  - [ ] Add parameter descriptions
  - [ ] Add return value descriptions
  - [ ] Include usage examples

- [ ] **Create README updates**
  - [ ] Update installation instructions
  - [ ] Add configuration documentation
  - [ ] Document new approval workflow
  - [ ] Add troubleshooting guide

### 11. Create Unit Tests ✅ COMPLETED
- [x] **Test critical functions**
  - [x] Test date calculation functions
  - [x] Test calendar validation functions
  - [x] Test configuration operations
  - [x] Test approval workflow functions

- [x] **Set up testing framework**
  - [x] Install pytest
  - [x] Create test directory structure
  - [x] Add test configuration
  - [x] Create test data fixtures

- [x] **Comprehensive test coverage**
  - [x] Unit tests for ApprovalView class
  - [x] Unit tests for AddCalendar modal
  - [x] Integration tests for complete workflow
  - [x] Mock Discord environment for testing
  - [x] Test runner script with coverage reporting

## Phase 5: Backward Compatibility & Migration

### 12. Maintain Existing Data
- [ ] **Preserve existing config.json**
  - [ ] Ensure new code reads existing format
  - [ ] Add migration functions if needed
  - [ ] Test with current data structure
  - [ ] Document any format changes

- [ ] **Preserve existing history.jsonl**
  - [ ] Ensure new date calculator works with existing data
  - [ ] Test /when command with historical data
  - [ ] Validate data integrity
  - [ ] Add data repair tools if needed

### 13. Migration Scripts
- [ ] **Create data migration utilities**
  - [ ] Script to validate existing data
  - [ ] Script to backup current data
  - [ ] Script to migrate data if needed
  - [ ] Rollback scripts for safety

## Implementation Notes

### Priority Order:
1. **High Priority**: Calendar approval system and /when command fixes
2. **Medium Priority**: Code modularization and error handling
3. **Low Priority**: Code quality improvements and testing

### Dependencies:
- Calendar approval system depends on Discord DM permissions
- Date calculator improvements depend on understanding current calculation logic
- Error handling should be added incrementally to avoid breaking existing functionality

### Testing Strategy:
- Test each component individually before integration
- Use existing data for realistic testing scenarios
- Test edge cases and error conditions
- Validate backward compatibility throughout development

### Rollback Plan:
- Keep backups of all data files before major changes
- Maintain ability to revert to previous version
- Document all changes for easy rollback
- Test rollback procedures before deployment 