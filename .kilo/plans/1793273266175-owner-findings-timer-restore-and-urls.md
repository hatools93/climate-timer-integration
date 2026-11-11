# Plan: Address Owner Findings — Dead Links, Timer Restore, entity_id Override

Branch: `bugfix/restore-timer-and-entity-id` (workflow rule: never commit to `main`; bump `manifest.json` version on the branch; run `npm run test:run` before finishing).

## Findings (verified against code)

1. **Dead links** — `manifest.json:13,16` (`documentation`, `issue_tracker`) and `README.md:53` point at dead `melanga/*` repos. Owner also confirmed (in interview) to update `manifest.json:5` `"codeowners": ["@melanga"]` → `@hatools93`.
2. **Timer never restored** — `ClimateTimerSensor` is not a `RestoreEntity`. On HA restart or entry reload while active, `async_will_remove_from_hass` cancels the scheduled finish and nothing reschedules it → climate stays on forever. The `restore: True` attribute is cosmetic.
3. **`entity_id` override breaks renames** — `sensor.py:98-106` overrides `entity_id` with a no-op setter, so registry renames are never applied and the old id keeps receiving state (renamed entity shows unavailable). The owner's cited line numbers (268-276, 301, 417-419) don't match the current 275-line file, but the described code exists at the lines above.

4. **HA version floor too low** — `hacs.json` declares `"homeassistant": "2024.1.0"`, but the code is broken on anything older than **2024.7**: `frontend/__init__.py:61-63` uses `hass.http.async_register_static_paths` + `StaticPathConfig`, which first ship in HA 2024.7.0 (verified: absent in 2024.2/2024.3/2024.4/2024.5/2024.6 tags, present in 2024.7.0; the old sync `register_static_path` was deprecated in 2024.7 with removal announced for 2025.7). Additionally `__init__.py:37` uses the PEP 695 `type ClimateTimerConfigEntry = ConfigEntry` statement, a SyntaxError on Python 3.11 — HA 2024.4.0 is the first release requiring Python 3.12 (verified `requires-python` in the 2024.3.0 vs 2024.4.0 tags). `ConfigFlowResult` (earliest core usages merged March 2024) and `ServiceValidationError` (present in 2024.4.0) are both subsumed. On HA ≤ 2024.6 the integration fails at setup (`AttributeError` inside `async_setup`), so the floor documents reality rather than dropping working installs.

Extra defect found during analysis (must fix alongside #2): `__init__.py:85-91` registers the internal `climate_timer_timer_finished` listener **after** `async_forward_entry_setups`, so a finish event fired from `async_added_to_hass` during startup would be missed.

## Decisions

- **Codeowners** → `@hatools93` (user-confirmed).
- **Card discovery**: attribute-first — scan `hass.states` for a `sensor.*` whose `attributes.climate_entity` equals the configured climate entity; keep the naming-convention id (`sensor.climate_timer_climate_<slug>`) as a fallback for robustness (covers `unavailable` states and matches existing installs). Sensor keeps exposing `climate_entity` (already present, `sensor.py:126-133`).
- **Expired-at-restore**: if `finishes_at` is in the past (or missing/unparseable while state was `active`), treat as finished → fire the internal event so the existing listener turns the climate off and fires the public `climate_timer_finished` event (single code path, logbook included). If `finishes_at` is in the future, reschedule normally. Malformed timestamps count as expired (the integration's promise is auto-off).
- **Startup ordering**: register the event listener **before** forwarding to the sensor platform; when firing the expired event, wait until `CoreState.running` (listen once for `EVENT_HOMEASSISTANT_STARTED`) so `climate.turn_off` isn't aimed at an unloaded domain.
- **Registry continuity**: keep `unique_id = f"{TIMER_PREFIX}{slug}"` unchanged; setting `self.entity_id` in `__init__` acts only as the suggested id, so existing installs don't migrate.
- **HA floor**: `hacs.json` `"homeassistant"` → `"2024.7.0"` (driven by `async_register_static_paths`/`StaticPathConfig`, introduced in 2024.7; the Python 3.12 requirement from the PEP 695 type alias is subsumed). Do not fall back to the deprecated `register_static_path` — it is slated for removal in 2025.7.
- **Version bump**: `1.4.4` → `1.5.0` (restore behavior + card discovery are user-visible changes).

## Tasks

1. **Link + metadata fixes**
   - `manifest.json`: `documentation` → `https://github.com/hatools93/climate-timer-integration`, `issue_tracker` → `.../issues`, `codeowners` → `["@hatools93"]`.
   - `README.md:53`: link → `https://github.com/hatools93/climate-timer` (text stays "Climate Timer Card").
   - `hacs.json`: `"homeassistant": "2024.1.0"` → `"2024.7.0"`.

2. **`sensor.py` — RestoreEntity + entity_id fix**
   - `from homeassistant.helpers.restore_state import RestoreEntity`; `class ClimateTimerSensor(RestoreEntity, SensorEntity)`.
   - Delete the `entity_id` property/setter override (lines 98-106). In `__init__`: `self.entity_id = get_timer_entity_id(climate_entity)` (reuse the helper from `const.py`; currently unused — also switch `unique_id` construction to stay DRY).
   - Add `async_added_to_hass`: `await super()...`, `state = await self.async_get_last_state()`; restore `duration` from attributes always (preserves last-used duration); then:
     - `active` + parseable future `finishes_at` → set `_timer_state/_end_time/_finishes_at/_remaining`, reschedule via `async_track_point_in_utc_time`, `async_write_ha_state`.
     - `active` + expired/missing/unparseable → reset to idle, write state, then fire `climate_timer_timer_finished` (data `entity_id`, `timer_entity_id`) — immediately if `hass.state == CoreState.running`, otherwise via `hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, …)`.
     - `paused` → restore `_pause_remaining` from `remaining` attribute (defensive; no current service sets it).
     - `idle`/no state → idle defaults (duration preserved).
   - Keep `async_will_remove_from_hass` cancelling the scheduled tracker (RestoreEntity storage persists state independently).

3. **`__init__.py` — listener ordering**
   - Move `_async_register_event_listener(hass)` above `async_forward_entry_setups(entry, PLATFORMS)` so the finish path is armed before the sensor (possibly restored) is added. Registration stays idempotent.

4. **Card discovery (`src/components/climate-timer-card.ts`, `src/types.ts`)**
   - `types.ts`: add `climate_entity?: string` to `TimerEntityState.attributes`.
   - `_managedTimerEntity`: attribute scan over `this.hass.states` (domain `sensor.`, `attributes.climate_entity === config.entity`), falling back to `sensor.climate_timer_${slug}` if no attribute match exists.

5. **Tests (`src/__tests__/`)**
   - `climate-timer-card.test.ts`: include `climate_entity` in the mock sensor attributes; add a case where the sensor id is renamed (e.g. `sensor.my_renamed_timer`) and is still discovered; keep/adjust the convention-id test to exercise the fallback; update the discovery comment at line 11.
   - `climate-timer-card.property.test.ts` (~line 214): rewrite the discovery property — discovery succeeds for any sensor entity_id carrying the right `climate_entity`, and via the convention id as fallback.

6. **Build + version + docs**
   - `npm run build` and commit the rebuilt `custom_components/climate_timer/frontend/climate-timer-integration-card.js` (POSIX `cp` in the script — run from Git Bash on Windows).
   - `manifest.json` version → `1.5.0`.
   - Update `AGENTS.md`: naming-contract section now describes attribute-first discovery with the convention as suggested id/fallback; remove/replace the "no-op setter preserves the contract" gotcha with the new rename behavior.

## Suggested commits (Conventional Commits)

- `fix: point manifest and README links to hatools93 repositories`
- `fix: raise minimum Home Assistant version to 2024.7` (hacs.json)
- `fix: restore running timers across restarts and respect entity registry renames`
- `fix: discover timer sensor via climate_entity attribute` (card, tests, rebuilt bundle)
- `chore: bump version to 1.5.0`

## Validation

- `npx tsc --noEmit` and `npm run test:run` (hard gate; Python has no automated tests here).
- Manual HA checklist for the Python side (document in PR):
  1. Start a 5-minute timer, restart HA mid-countdown → timer resumes, countdown continues, climate turns off at expiry.
  2. Same but let the timer expire while HA is down → climate turned off shortly after startup; `climate_timer_finished` event + logbook entry appear.
  3. Reload the config entry mid-timer → same as (1).
  4. Rename the sensor entity id in the registry → state updates under the new id; card still controls the climate; old id stops receiving state.
  5. Normal start/cancel regression; card still shows "No managed timer found" when the sensor is absent.
- CI runs HACS validation + hassfest on the PR to `main` (no Python tests configured in-repo); the raised `hacs.json` floor needs no code changes and cannot fail hassfest (custom integrations may not declare `homeassistant` in `manifest.json` — `hacs.json` is the correct place).
