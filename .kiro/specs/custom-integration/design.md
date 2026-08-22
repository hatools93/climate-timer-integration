# Design Document: Climate Timer Integration

## Overview

A Home Assistant custom integration (`climate_timer`) that provides a complete climate timer solution: auto-creates timer helpers, manages HVAC mode persistence server-side, handles climate shutdown on timer finish, and embeds a Lovelace card that auto-registers itself.

The card is minimal — it only needs a `entity` config field. All logic (mode resolution, turn-on, rollback, turn-off) lives in the integration.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ Home Assistant Frontend                                             │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Climate Timer Card (JS)                                    │   │
│  │                                                             │   │
│  │  Discovers timer via: timer.climate_timer_{entity_slug}     │   │
│  │  Calls: climate_timer.start(entity_id, duration)            │   │
│  │  Calls: climate_timer.cancel(entity_id)                     │   │
│  │  Reads: timer state from hass.states for countdown display  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                          │                                          │
│          callService     │                                          │
│                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Custom Integration (Python) — "climate_timer"              │   │
│  │                                                             │   │
│  │  Config Flow: user picks climate entity                     │   │
│  │                                                             │   │
│  │  Timer Manager:                                             │   │
│  │    • Creates timer.climate_timer_{slug}                     │   │
│  │    • Deletes on config entry removal                        │   │
│  │                                                             │   │
│  │  Services:                                                  │   │
│  │    • climate_timer.start: resolve mode → turn on → timer    │   │
│  │    • climate_timer.cancel: cancel timer → turn off          │   │
│  │                                                             │   │
│  │  Event Listener:                                            │   │
│  │    • timer.finished → climate.turn_off                      │   │
│  │                                                             │   │
│  │  HVAC Mode Storage:                                         │   │
│  │    • Tracks climate state changes                           │   │
│  │    • Persists last-active mode to .storage/                 │   │
│  │    • Resolves mode on start (attrs → stored → fallback)     │   │
│  │                                                             │   │
│  │  Frontend Serving:                                          │   │
│  │    • Serves card JS at /climate-timer/                      │   │
│  │    • Auto-registers as Lovelace resource                    │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Integration Structure

```
custom_components/climate_timer/
├── __init__.py            # Setup, services, event listener, HVAC tracking
├── manifest.json          # HA metadata (deps: frontend, http, timer)
├── config_flow.py         # UI config flow (pick climate entity)
├── const.py               # Constants, naming convention helper
├── timer_manager.py       # Timer creation/deletion
├── services.yaml          # Service schemas
├── strings.json           # UI strings
├── translations/
│   └── en.json
└── frontend/
    ├── __init__.py        # JSModuleRegistration
    └── climate-timer-card.js  # Built card JS
```

## Key Design Decisions

### 1. Naming Convention for Managed Timers

`timer.climate_timer_{entity_slug}` where slug = entity_id with dots → underscores.

Example: `climate.living_room_ac` → `timer.climate_timer_climate_living_room_ac`

Deterministic naming enables card auto-discovery without any API.

### 2. Full-Lifecycle Services

`climate_timer.start(entity_id, duration)` handles:
1. Check if climate entity is off
2. If off → resolve HVAC mode → turn on with mode (or generic turn_on)
3. Start managed timer
4. Roll back (turn off) if timer start fails

`climate_timer.cancel(entity_id)` handles:
1. Cancel managed timer
2. Turn off climate entity

The card just calls these — no climate logic on the frontend.

### 3. HVAC Mode Persistence (Server-Side)

Uses `homeassistant.helpers.storage.Store` with key `climate_timer.modes`.

Resolution priority in start service:
1. `attributes.last_mode` (some climate integrations expose this)
2. `attributes.hvac_mode` (retained by some when off)
3. Integration's stored last-active mode
4. Fallback: `climate.turn_on` without mode

State tracking: listens for climate state changes, persists active modes.

### 4. Embedded Frontend

The integration serves the card JS at `/climate-timer/climate-timer-card.js` and auto-registers it as a Lovelace resource (storage mode). Users install one HACS integration and get the card automatically.

### 5. Card Simplicity

Card config:
```yaml
type: custom:climate-timer-card
entity: climate.living_room_ac
# Optional: max_duration, step, show_name, show_state, ui_mode
```

The card:
- Derives timer entity from naming convention (no config needed)
- Calls `climate_timer.start` / `climate_timer.cancel` (no climate logic)
- Reads timer state from `hass.states` for countdown display
- No mode resolution, no rollback, no mode_helper

## Data Flow

### Setup Flow
1. User installs integration via HACS
2. Adds integration in Settings → Devices & Services
3. Config flow: picks climate entity
4. Integration creates managed timer
5. Frontend JS auto-registered
6. User adds card with just `entity: climate.living_room_ac`

### Start Flow
1. User presses Start → card calls `climate_timer.start`
2. Integration checks if climate is off → resolves mode → turns on
3. Integration starts managed timer
4. Timer goes active → card reads state, shows countdown

### Timer Finish Flow
1. Timer fires `timer.finished`
2. Integration's event listener → `climate.turn_off`
3. Timer goes idle → card resets to duration selection

### Cancel Flow
1. User presses Cancel → card calls `climate_timer.cancel`
2. Integration cancels timer → turns off climate
3. Timer goes idle → card resets

## Error Handling

| Scenario | Behavior |
|---|---|
| Timer creation fails on setup | Config entry setup fails, user retries |
| climate_timer.start for unconfigured entity | ServiceValidationError raised |
| Climate turn-on fails in start | Error raised, timer not started |
| Timer start fails after turn-on | Rollback: climate.turn_off, error raised |
| climate.turn_off fails on finish | Warning logged, no exception |
| Timer deletion fails on unload | Warning logged, unload completes |
| Card can't find managed timer | Shows instructional message |

## Repository Structure

```
climate-timer-integration/
├── custom_components/climate_timer/  ← Python integration
├── dist/climate-timer-card.js        ← Build output
├── src/                              ← Card TypeScript source
├── hacs.json                         ← HACS integration type
├── package.json                      ← Build: rollup + copy to frontend/
└── README.md
```

Build: `npm run build` compiles card and copies to `custom_components/climate_timer/frontend/`.
