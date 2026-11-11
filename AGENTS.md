# AGENTS.md

Guidance for AI coding agents working on this repository. The project was built with Kiro using spec-driven development (`.kiro/`); this file summarizes the codebase and the rules that must be followed.

## Project Overview

**Climate Timer** (`climate_timer`) is a Home Assistant custom integration, distributed via HACS, that runs any `climate.*` entity for a set duration and turns it off when the timer expires. Backend and frontend ship together:

- `custom_components/climate_timer/` — Python integration (config flow, timer sensor entity, services, HVAC mode persistence, logbook, frontend auto-registration)
- `src/` — TypeScript + Lit Lovelace card, built with Rollup and copied into the integration's `frontend/` folder
- `.kiro/specs/custom-integration/` — spec-driven artifacts: `requirements.md` (EARS-style acceptance criteria), `design.md`, `tasks.md`
- `.kiro/steering/workflow.md` — binding workflow rules (see "Workflow Rules" below)

There is no card-only/legacy mode: the card **requires** the integration. The card config only needs `entity`; all logic (mode resolution, turn-on, rollback, turn-off) lives server-side.

Minimum supported Home Assistant is **2024.7** (declared in `hacs.json`): the integration uses `hass.http.async_register_static_paths`/`StaticPathConfig` (2024.7) and the PEP 695 `type` alias in `__init__.py`, which requires Python 3.12 (guaranteed by HA ≥ 2024.4). Do not lower the floor or fall back to the deprecated `register_static_path`.

## Commands

| Task | Command |
|---|---|
| Install deps | `npm install` |
| Build card + copy into integration | `npm run build` |
| Build card only (Rollup) | `npm run build:card` |
| Watch build | `npm run watch` |
| Run tests once | `npm run test:run` |
| Tests in watch mode | `npm test` |
| Coverage | `npm run test:coverage` |
| Typecheck | `npx tsc --noEmit` |

Notes:
- `npm run build` uses POSIX `cp` in its script; on Windows run it from Git Bash/WSL, or copy `dist/climate-timer-integration-card.js` to `custom_components/climate_timer/frontend/` manually.
- There is no JS/TS linter configured; TypeScript `strict` mode is enforced (tsconfig.json).
- The Python side has **no automated tests** in this repo. CI (`.github/workflows/validate.yml`) runs HACS validation and hassfest on pushes/PRs to `main`.
- Releases are manual: trigger `release.yml` via `workflow_dispatch` with a version string; it tests, builds, bumps `manifest.json`, commits to `main`, tags `vX.Y.Z`, and publishes a GitHub Release zip. Never hand-create releases.

## Architecture

Two halves connected by a strict naming contract and service calls:

```
Lovelace card (src/, Lit)  ──callService──▶  Integration (Python)
        ▲                                          │
        └──── reads timer sensor state ────────────┘
```

### Python integration (`custom_components/climate_timer/`)

- `__init__.py` — entry setup/unload, registers services (`climate_timer.start`, `climate_timer.cancel`), listens for the internal `climate_timer_timer_finished` event and turns the climate off, tracks climate state changes to persist HVAC modes, raises `ServiceValidationError` for unconfigured entities.
- `sensor.py` — `ClimateTimerSensor`: a custom timer **sensor** entity (state `idle`/`active`/`paused`, attributes `duration`, `remaining`, `finishes_at`, `climate_entity`, `restore`). Schedules expiry with `async_track_point_in_utc_time`, fires `climate_timer_timer_finished` on expiry. It is a `RestoreEntity`: on restart/reload an active timer reschedules its finish, and a timer that already expired resets to idle and turns the climate off (deferred until `homeassistant_started` if HA is still booting). Its entity_id defaults to the naming-convention id (suggested in `__init__`); the registry may rename it.
- `config_flow.py` — single-step UI flow; unique_id = the climate entity_id (prevents duplicates); validates the entity exists and is in the `climate` domain.
- `const.py` — domain, `get_timer_entity_id()` naming helper, `URL_BASE`, `JSMODULES` (version read from `manifest.json` at runtime for cache busting), storage key `climate_timer.modes`, public event names.
- `frontend/__init__.py` — serves the card JS at `/climate-timer-integration/…` via `StaticPathConfig` and auto-registers/updates the Lovelace resource in storage mode (cleans up legacy `/climate-timer/` URLs; warns in YAML mode).
- `logbook.py` — describes the three public events for the Logbook.
- `services.yaml`, `strings.json`, `translations/en.json`, `manifest.json` — HA metadata, schemas, UI strings.

**Key flows:**
- `start`: find config entry → if climate is off, resolve HVAC mode (`attributes.last_mode` → `attributes.hvac_mode` → integration-stored mode → generic `turn_on`) → turn on → start timer sensor → **rollback** (`turn_off`) if timer start fails → fire `climate_timer_started`.
- `cancel`: cancel timer sensor → `turn_off` → fire `climate_timer_cancelled`.
- Timer finish: sensor fires internal event → listener turns climate off → fires public `climate_timer_finished`.
- Public events (usable in automations): `climate_timer_started` (data: `entity_id`, `duration`), `climate_timer_finished`, `climate_timer_cancelled` (data: `entity_id`).

### Frontend card (`src/`)

- `main.ts` — imports components and pushes into `window.customCards` for the card picker.
- `components/climate-timer-card.ts` — element `climate-timer-integration-card`. Discovers the timer sensor via its `climate_entity` attribute (naming convention as fallback), reads its state/attributes for the countdown, delegates start/cancel to the services, handles external climate-off/unavailable during countdown (cancels the timer), 1-second `requestUpdate` interval while active.
- `components/climate-timer-card-editor.ts` — visual editor (entity + display options).
- `components/timer-selector.ts` — rotary dial UI (drag/scroll/swipe).
- `components/simple-timer-selector.ts` — capsule button UI (`ui_mode: simple`).
- `components/timer-display.ts` — countdown display.
- `utils/duration-utils.ts` — clamping/snapping/parsing (minutes ↔ `HH:MM:SS`, human strings like `"2h30m"`). Defaults: min 15, max 240, step 15; hard ceiling 24h.
- `utils/timer-utils.ts` — remaining-ms and elapsed-fraction from `finishes_at`.
- `utils/format-utils.ts` — idle duration text (`1h 30m`) and `MM:SS` countdown.
- `utils/entity-utils.ts` — domain filters for entity pickers.
- `ha-types.ts` — minimal hand-rolled HA type stubs (do not import `homeassistant` packages).

Card config (`types.ts`): `entity` (required), `max_duration` (default `"4h"`), `step` (default `"15m"`), `show_name`, `show_state`, `ui_mode` (`rotary` default | `simple`).

## The Naming Contract (critical)

The integration manages one timer **sensor** per configured climate entity. The sensor's *suggested* entity_id is deterministic, defined in `const.py::get_timer_entity_id()`:

```
climate.<slug>  →  sensor.climate_timer_climate_<slug>
```

Example: `climate.living_room_ac` → `sensor.climate_timer_climate_living_room_ac`. The entity registry may still rename the sensor (users can rename entities), so the card must not rely on the id alone:

- Primary discovery: the sensor whose `climate_entity` attribute equals the configured climate entity (`src/components/climate-timer-card.ts::_managedTimerEntity`).
- Fallback: the convention id above.
- The Python side keeps `unique_id = climate_timer_climate_<slug>` stable so registry renames persist, and the sensor attribute shape (`duration`, `remaining`, `finishes_at`, `state: idle|active|paused`) must stay compatible with `types.ts` and the tests.

> Note: `.kiro/specs/.../design.md` still describes a `timer.climate_timer_*` helper — the implementation evolved to a custom sensor entity (see `sensor.py` docstring). The code and `const.py` are the source of truth.

## Workflow Rules (from `.kiro/steering/workflow.md` — binding)

1. **Never commit or push directly to `main`.** Create a `feature/...` or `bugfix/...` branch, push, and open a PR.
2. **Always run `npm run test:run` after changes** and fix failures before committing/finishing.
3. **Bump `custom_components/climate_timer/manifest.json` `version`** when making changes on a feature/bugfix branch (the release workflow rewrites it at release time; this keeps branches traceable).

Commit message style (observed): Conventional Commits — `feat:`, `fix:`, `docs:`, `chore:`.

## Testing Conventions

- Vitest with `globals: true`, `jsdom` environment, `pool: "forks"`; tests live in `src/__tests__/` and must match `*.{test,spec}.ts`.
- Unit tests: `src/__tests__/<module>.test.ts`.
- Property-based tests: `src/__tests__/<module>.property.test.ts` using **fast-check** (100 runs typical). Keep the header comments tracing each property to spec requirements (e.g., `**Validates: Requirements 2.2, 2.3**`) — this preserves the spec-driven traceability.
- Card/component tests build a full mock `hass` via a `createMockHass(overrides)` helper including both the climate entity and the managed timer sensor under its convention-derived id; they mount the element with `setConfig(...)` + `document.body.appendChild`. Follow this pattern for new component tests.
- Tests must run under `strict` TypeScript with no new `any` leaks where practical.

## Code Style

- **TypeScript:** strict mode; Lit 3 with `@customElement`/`@property`/`@state` decorators; shadow DOM with `css` tagged templates; HA theming via CSS custom properties (`--primary-color`, `--primary-text-color`, …). `useDefineForClassFields: false` and `experimentalDecorators` are set — do not "modernize" the tsconfig casually.
- **Python:** Home Assistant custom-integration style — `from __future__ import annotations`, full type hints, `_LOGGER`, async/`@callback` separation, voluptuous schemas, `ServiceValidationError` for user-facing errors, warnings (not exceptions) for best-effort cleanup paths. New files start with a module docstring.
- Keep the card "dumb": no HVAC logic, no mode resolution, no rollbacks in frontend code — call the services.

## Gotchas

- The built card JS is **committed** to `custom_components/climate_timer/frontend/climate-timer-integration-card.js` (HACS ships it from the repo). After frontend changes, run `npm run build` so the committed bundle matches the source. `dist/` itself is gitignored.
- Bumping `manifest.json` version changes the Lovelace resource URL query (`?v=…`) used for cache busting — that's intentional (`const.py::JSMODULES`).
- `sensor.py` only *suggests* the convention entity_id (set once in `__init__`); the entity registry may rename it, and the card still finds the sensor via its `climate_entity` attribute.
- In `__init__.py`, the internal `climate_timer_timer_finished` listener must stay registered **before** `async_forward_entry_setups` — a restored timer that already expired fires its finish event while the sensor entity is being added.
- Timer restore defers the finish event until Home Assistant is running (`EVENT_HOMEASSISTANT_STARTED`) so `climate.turn_off` is not aimed at an unloaded domain during boot.
- Frontend registration only succeeds in Lovelace **storage mode**; YAML-mode installs get a warning telling users to add the resource manually. Don't "fix" this by removing the warning.
- The internal event `climate_timer_timer_finished` (sensor → integration) is distinct from the public `climate_timer_finished` event. Don't conflate or rename them.
- CI only validates on `main` pushes/PRs — running `npm run test:run` locally is the only test gate for branches.
