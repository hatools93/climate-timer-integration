# Implementation Plan: Climate Timer Integration

## Overview

A single-install Home Assistant integration that auto-creates timer helpers, manages HVAC mode persistence, handles climate shutdown on timer finish, and embeds a Lovelace card. No legacy mode — the card requires the integration.

## Tasks

- [x] 1. Create integration skeleton and constants
  - [x] 1.1 Create directory structure and manifest.json
  - [x] 1.2 Create const.py with domain constants and naming convention helper

- [x] 2. Implement config flow
  - [x] 2.1 Create config_flow.py (climate entity picker, duplicate check)
  - [x] 2.2 Create strings.json and translations/en.json

- [x] 3. Implement timer manager
  - [x] 3.1 Create timer_manager.py (create/remove timer helpers)

- [x] 4. Implement integration setup and services
  - [x] 4.1 Create __init__.py with entry setup/unload
  - [x] 4.2 Implement climate_timer.start with HVAC mode resolution and rollback
  - [x] 4.3 Create services.yaml
  - [x] 4.4 Implement timer.finished event listener
  - [x] 4.5 Implement HVAC mode state tracking and storage

- [x] 5. Implement embedded frontend serving
  - [x] 5.1 Create frontend/__init__.py (static path + Lovelace resource registration)

- [x] 6. Implement card (integration-only)
  - [x] 6.1 Update types.ts (only entity required, no timer_entity/mode_helper)
  - [x] 6.2 Rewrite climate-timer-card.ts (discover timer by convention, call climate_timer services)
  - [x] 6.3 Rewrite climate-timer-card-editor.ts (only entity + display options)

- [x] 7. Update build pipeline
  - [x] 7.1 Update hacs.json for integration type
  - [x] 7.2 Update package.json build to copy JS to frontend/
  - [x] 7.3 Update .gitignore

- [x] 8. Clean up and verify
  - [x] 8.1 Remove all legacy code (timer_entity, mode_helper, _resolveHvacMode)
  - [x] 8.2 Update tests for integration-only architecture
  - [x] 8.3 Verify build passes
  - [x] 8.4 Verify all tests pass (153 tests, 15 files)
