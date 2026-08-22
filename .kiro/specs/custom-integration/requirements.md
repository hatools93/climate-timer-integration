# Requirements Document

## Introduction

The Climate Timer Integration is a Home Assistant custom integration (`climate_timer`) that provides a complete climate timer solution in a single install. It automatically creates and manages timer helpers, persists HVAC mode server-side, handles climate shutdown on timer finish, and embeds a Lovelace card for user interaction.

The card requires only a `entity` config field — everything else is managed by the integration.

## Glossary

- **Custom_Integration**: The Python-based Home Assistant integration (`climate_timer`) that manages the full timer lifecycle
- **Config_Entry**: A Home Assistant configuration entry created through the UI config flow, representing one climate entity pairing
- **Managed_Timer**: A timer helper entity automatically created and managed by the integration (naming convention: `timer.climate_timer_{entity_slug}`)
- **Timer_Manager**: The internal module responsible for creating, tracking, and cleaning up managed timer entities
- **Config_Flow**: The HA UI-based setup wizard for adding the integration

## Requirements

### Requirement 1: Integration Setup via Config Flow

**User Story:** As a Home Assistant user, I want to add the Climate Timer integration through the UI and select my climate entity, so that the system is set up without editing YAML or creating helpers manually.

#### Acceptance Criteria

1. THE Custom_Integration SHALL register a config flow accessible from Settings > Devices & Services > Add Integration
2. THE config flow SHALL present a single step with a climate entity selector showing all `climate.*` entities
3. WHEN the user selects a climate entity and submits, THE Custom_Integration SHALL create a Config_Entry for that pairing
4. IF a Config_Entry already exists for the selected climate entity, THE config flow SHALL reject the submission with an "already configured" error
5. THE Custom_Integration SHALL support multiple Config_Entries (one per climate entity)
6. THE config flow SHALL display the integration name as "Climate Timer"

### Requirement 2: Automatic Timer Entity Creation

**User Story:** As a Home Assistant user, I want the integration to automatically create a timer helper for my climate entity, so I don't have to create one manually.

#### Acceptance Criteria

1. WHEN a Config_Entry is set up, THE Custom_Integration SHALL create a Managed_Timer entity with the naming convention `timer.climate_timer_{entity_slug}` where `{entity_slug}` is the climate entity_id with dots replaced by underscores
2. THE Managed_Timer SHALL be configured with `restore: true` to survive HA restarts
3. THE Managed_Timer SHALL have a default duration of 00:30:00
4. IF the Managed_Timer already exists, THE Custom_Integration SHALL reuse it without creating a duplicate
5. WHEN a Config_Entry is removed, THE Custom_Integration SHALL delete the associated Managed_Timer entity

### Requirement 3: Integrated Timer Lifecycle Services

**User Story:** As a Climate Timer Card, I want the integration to expose start and cancel services that handle the full climate+timer lifecycle, so the card can delegate all logic with a single service call.

#### Acceptance Criteria

1. THE Custom_Integration SHALL register a `climate_timer.start` service accepting `entity_id` (climate entity) and `duration` (HH:MM:SS string)
2. THE Custom_Integration SHALL register a `climate_timer.cancel` service accepting `entity_id` (climate entity)
3. WHEN `climate_timer.start` is called AND the climate entity is off, THE Custom_Integration SHALL resolve the last-active HVAC mode and turn on the climate entity with that mode before starting the timer
4. WHEN `climate_timer.start` is called AND the climate entity is already on, THE Custom_Integration SHALL start the Managed_Timer without modifying the climate entity state
5. IF the climate entity fails to turn on, THE Custom_Integration SHALL NOT start the timer and SHALL raise an error
6. IF the timer fails to start after the climate entity was turned on, THE Custom_Integration SHALL roll back by calling `climate.turn_off`
7. WHEN `climate_timer.cancel` is called, THE Custom_Integration SHALL cancel the Managed_Timer and call `climate.turn_off` on the associated climate entity
8. IF `climate_timer.start` or `climate_timer.cancel` is called with a climate entity that has no Config_Entry, THE service SHALL raise a ServiceValidationError
9. THE services SHALL be callable from the frontend card via `hass.callService`

### Requirement 4: Automatic Climate Shutdown on Timer Finish

**User Story:** As a Home Assistant user, I want the integration to automatically turn off my climate entity when the timer finishes, so I don't need a separate automation.

#### Acceptance Criteria

1. THE Custom_Integration SHALL listen for `timer.finished` events matching any Managed_Timer
2. WHEN a Managed_Timer fires `timer.finished`, THE Custom_Integration SHALL call `climate.turn_off` on the associated climate entity
3. IF `climate.turn_off` fails, THE Custom_Integration SHALL log a warning but not raise an exception
4. THE automatic shutdown SHALL work regardless of whether the browser or frontend is open

### Requirement 5: HVAC Mode Persistence and Resolution

**User Story:** As a Home Assistant user, I want the integration to remember the last-active HVAC mode for my climate entity and restore it when the timer starts, so it always resumes in the correct mode.

#### Acceptance Criteria

1. THE Custom_Integration SHALL track state changes of each configured climate entity
2. WHEN a climate entity transitions to an active HVAC mode (not "off", not "unavailable"), THE Custom_Integration SHALL persist that mode internally using HA storage
3. WHEN `climate_timer.start` is called and the climate entity is off, THE Custom_Integration SHALL resolve the HVAC mode using the following priority:
   - Priority 1: Climate entity `attributes.last_mode` (if available and not "off"/"unavailable")
   - Priority 2: Climate entity `attributes.hvac_mode` (if available and not "off"/"unavailable")
   - Priority 3: Integration's internally persisted last-active mode
   - Priority 4: Call `climate.turn_on` without specifying a mode (let HA decide)
4. THE persisted mode SHALL survive Home Assistant restarts
5. THE persisted mode SHALL be shared across all clients/devices (server-side storage)

### Requirement 6: Card Configuration and Display

**User Story:** As a Home Assistant user, I want a Lovelace card that only requires selecting a climate entity, with the timer management handled transparently by the integration.

#### Acceptance Criteria

1. THE card SHALL require only an `entity` field in its configuration
2. THE card SHALL discover the Managed_Timer using the naming convention `timer.climate_timer_{entity_slug}`
3. THE card SHALL call `climate_timer.start` with `entity_id` and `duration` when the user presses Start
4. THE card SHALL call `climate_timer.cancel` with `entity_id` when the user presses Cancel
5. THE card SHALL display countdown progress by reading the managed timer's state from `hass.states`
6. THE Card_Editor SHALL show only: climate entity selector, max duration, step, show name, show state, UI mode
7. IF the managed timer is not found in `hass.states`, THE card SHALL show a message instructing the user to add the entity in the integration settings

### Requirement 7: Embedded Frontend Distribution

**User Story:** As a Home Assistant user, I want to install a single HACS integration that gives me both the backend and the card, so setup is a one-step process.

#### Acceptance Criteria

1. THE integration SHALL embed the compiled card JS file and serve it via a registered static HTTP path
2. THE integration SHALL automatically register the card JS as a Lovelace resource on setup (for storage mode)
3. THE user SHALL NOT need to manually add the card as a Lovelace resource when the integration is installed
4. THE integration SHALL include a valid `manifest.json` with `"dependencies": ["frontend", "http", "timer"]`
5. FOR users in YAML Lovelace mode, THE integration SHALL still serve the JS file at a known static path, documented in README for manual resource addition

### Requirement 8: Integration Cleanup and Uninstall

**User Story:** As a Home Assistant user, I want removing the integration to clean up all managed timer entities, so no orphaned helpers remain.

#### Acceptance Criteria

1. WHEN a Config_Entry is removed via the UI, THE Custom_Integration SHALL delete the associated Managed_Timer entity
2. WHEN the entire integration is uninstalled, ALL Managed_Timer entities SHALL be deleted
3. IF a Managed_Timer deletion fails, THE Custom_Integration SHALL log a warning but complete the unload without error
