import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import "../components/climate-timer-card";
import type { ClimateTimerCard } from "../components/climate-timer-card";
import type { HomeAssistant } from "../ha-types";

/**
 * Integration tests for the ClimateTimerCard full lifecycle.
 *
 * The card now works exclusively with the Climate Timer integration.
 * - Config only has `entity` (no `timer_entity` or `mode_helper`)
 * - Timer is discovered via naming convention: sensor.climate_timer_{entity.replace('.', '_')}
 * - Start calls `climate_timer.start` with { entity_id, duration }
 * - Cancel calls `climate_timer.cancel` with { entity_id }
 * - No client-side HVAC mode resolution or rollback (handled server-side)
 */

function createMockHass(overrides?: Partial<any>): HomeAssistant {
  return {
    states: {
      "climate.test_ac": {
        entity_id: "climate.test_ac",
        state: "off",
        attributes: {
          friendly_name: "Test AC",
          hvac_modes: ["off", "cool"],
          temperature: 24,
          current_temperature: 25,
        },
      },
      "sensor.climate_timer_climate_test_ac": {
        entity_id: "sensor.climate_timer_climate_test_ac",
        state: "idle",
        attributes: {
          duration: "00:30:00",
          remaining: "00:00:00",
          finishes_at: "",
          friendly_name: "Climate Timer",
          restore: true,
        },
      },
      ...overrides?.states,
    },
    callService: vi.fn().mockResolvedValue(undefined),
    connection: {},
    ...overrides,
  };
}

function createCard(): ClimateTimerCard {
  const el = document.createElement("climate-timer-integration-card") as ClimateTimerCard;
  el.setConfig({
    type: "custom:climate-timer-integration-card",
    entity: "climate.test_ac",
  });
  return el;
}

describe("ClimateTimerCard Integration", () => {
  let el: ClimateTimerCard;

  beforeEach(async () => {
    el = createCard();
    document.body.appendChild(el);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    el.remove();
  });

  describe("Full start flow", () => {
    it("press start → climate_timer.start called → card shows countdown", async () => {
      el.hass = createMockHass();
      await el.updateComplete;

      const startBtn = el.shadowRoot!.querySelector(".start-btn") as HTMLButtonElement;
      expect(startBtn).not.toBeNull();
      expect(startBtn.disabled).toBe(false);

      startBtn.click();

      await vi.waitFor(() => {
        expect(el.hass.callService).toHaveBeenCalledTimes(1);
      });

      expect(el.hass.callService).toHaveBeenNthCalledWith(
        1,
        "climate_timer",
        "start",
        { entity_id: "climate.test_ac", duration: "00:30:00" }
      );

      // Simulate HA state update: timer is now active
      const now = Date.now();
      const finishesAt = new Date(now + 30 * 60 * 1000).toISOString();
      el.hass = createMockHass({
        states: {
          "climate.test_ac": {
            entity_id: "climate.test_ac",
            state: "cool",
            attributes: { friendly_name: "Test AC", hvac_modes: ["off", "cool"], temperature: 24, current_temperature: 25 },
          },
          "sensor.climate_timer_climate_test_ac": {
            entity_id: "sensor.climate_timer_climate_test_ac",
            state: "active",
            attributes: { duration: "00:30:00", remaining: "00:30:00", finishes_at: finishesAt, friendly_name: "Climate Timer", restore: true },
          },
        },
      });
      await el.updateComplete;

      const cancelBtn = el.shadowRoot!.querySelector(".cancel-btn");
      const startBtnAfter = el.shadowRoot!.querySelector(".start-btn");
      expect(cancelBtn).not.toBeNull();
      expect(startBtnAfter).toBeNull();
    });
  });

  describe("Cancel flow", () => {
    it("press cancel → climate_timer.cancel called → card returns to idle", async () => {
      const now = Date.now();
      const finishesAt = new Date(now + 15 * 60 * 1000).toISOString();
      el.hass = createMockHass({
        states: {
          "climate.test_ac": {
            entity_id: "climate.test_ac",
            state: "cool",
            attributes: { friendly_name: "Test AC", hvac_modes: ["off", "cool"], temperature: 24, current_temperature: 25 },
          },
          "sensor.climate_timer_climate_test_ac": {
            entity_id: "sensor.climate_timer_climate_test_ac",
            state: "active",
            attributes: { duration: "00:30:00", remaining: "00:15:00", finishes_at: finishesAt, friendly_name: "Climate Timer", restore: true },
          },
        },
      });
      await el.updateComplete;

      const cancelBtn = el.shadowRoot!.querySelector(".cancel-btn") as HTMLButtonElement;
      expect(cancelBtn).not.toBeNull();

      cancelBtn.click();

      await vi.waitFor(() => {
        expect(el.hass.callService).toHaveBeenCalledTimes(1);
      });

      expect(el.hass.callService).toHaveBeenNthCalledWith(
        1,
        "climate_timer",
        "cancel",
        { entity_id: "climate.test_ac" }
      );

      // Simulate timer going idle
      el.hass = createMockHass();
      await el.updateComplete;

      expect(el.shadowRoot!.querySelector(".start-btn")).not.toBeNull();
      expect(el.shadowRoot!.querySelector(".cancel-btn")).toBeNull();
    });
  });

  describe("Timer finish flow", () => {
    it("timer entity transitions to idle → card resets", async () => {
      const now = Date.now();
      const finishesAt = new Date(now + 5 * 60 * 1000).toISOString();
      el.hass = createMockHass({
        states: {
          "climate.test_ac": {
            entity_id: "climate.test_ac",
            state: "cool",
            attributes: { friendly_name: "Test AC", hvac_modes: ["off", "cool"], temperature: 24, current_temperature: 25 },
          },
          "sensor.climate_timer_climate_test_ac": {
            entity_id: "sensor.climate_timer_climate_test_ac",
            state: "active",
            attributes: { duration: "00:30:00", remaining: "00:05:00", finishes_at: finishesAt, friendly_name: "Climate Timer", restore: true },
          },
        },
      });
      await el.updateComplete;

      expect(el.shadowRoot!.querySelector(".cancel-btn")).not.toBeNull();

      // Timer finishes
      el.hass = createMockHass();
      await el.updateComplete;

      expect(el.shadowRoot!.querySelector(".start-btn")).not.toBeNull();
      expect(el.shadowRoot!.querySelector(".cancel-btn")).toBeNull();
    });
  });

  describe("Unavailable handling", () => {
    it("entity becomes unavailable → start button disabled", async () => {
      el.hass = createMockHass({
        states: {
          "climate.test_ac": {
            entity_id: "climate.test_ac",
            state: "unavailable",
            attributes: { friendly_name: "Test AC", hvac_modes: ["off", "cool"], temperature: 24, current_temperature: 25 },
          },
          "sensor.climate_timer_climate_test_ac": {
            entity_id: "sensor.climate_timer_climate_test_ac",
            state: "idle",
            attributes: { duration: "00:30:00", remaining: "00:00:00", finishes_at: "", friendly_name: "Climate Timer", restore: true },
          },
        },
      });
      await el.updateComplete;

      const startBtn = el.shadowRoot!.querySelector(".start-btn") as HTMLButtonElement;
      expect(startBtn).not.toBeNull();
      expect(startBtn.disabled).toBe(true);

      const unavailableIndicator = el.shadowRoot!.querySelector(".unavailable");
      expect(unavailableIndicator).not.toBeNull();
    });
  });

  describe("Managed timer entity discovery", () => {
    it("discovers managed timer via naming convention", async () => {
      el.hass = createMockHass();
      await el.updateComplete;

      const managedTimerEntity = (el as any)._managedTimerEntity;
      expect(managedTimerEntity).toBe("sensor.climate_timer_climate_test_ac");
    });
  });
});


describe("ClimateTimerCard - UI Mode Rendering", () => {
  let el: ClimateTimerCard;

  function createCardWithMode(uiMode?: string): ClimateTimerCard {
    const card = document.createElement("climate-timer-integration-card") as ClimateTimerCard;
    const config: any = { type: "custom:climate-timer-integration-card", entity: "climate.test_ac" };
    if (uiMode !== undefined) config.ui_mode = uiMode;
    card.setConfig(config);
    return card;
  }

  afterEach(() => {
    if (el) el.remove();
    vi.restoreAllMocks();
  });

  it("renders <timer-selector> when ui_mode is 'rotary'", async () => {
    el = createCardWithMode("rotary");
    document.body.appendChild(el);
    el.hass = createMockHass();
    await el.updateComplete;

    expect(el.shadowRoot!.querySelector("cti-timer-selector")).not.toBeNull();
    expect(el.shadowRoot!.querySelector("cti-simple-timer-selector")).toBeNull();
  });

  it("renders <timer-selector> when ui_mode is undefined (not set)", async () => {
    el = createCardWithMode(undefined);
    document.body.appendChild(el);
    el.hass = createMockHass();
    await el.updateComplete;

    expect(el.shadowRoot!.querySelector("cti-timer-selector")).not.toBeNull();
    expect(el.shadowRoot!.querySelector("cti-simple-timer-selector")).toBeNull();
  });

  it("renders <simple-timer-selector> when ui_mode is 'simple'", async () => {
    el = createCardWithMode("simple");
    document.body.appendChild(el);
    el.hass = createMockHass();
    await el.updateComplete;

    expect(el.shadowRoot!.querySelector("cti-simple-timer-selector")).not.toBeNull();
    expect(el.shadowRoot!.querySelector("cti-timer-selector")).toBeNull();
  });

  it("renders <timer-selector> when ui_mode is an invalid value (fallback)", async () => {
    el = createCardWithMode("invalid-value");
    document.body.appendChild(el);
    el.hass = createMockHass();
    await el.updateComplete;

    expect(el.shadowRoot!.querySelector("cti-timer-selector")).not.toBeNull();
    expect(el.shadowRoot!.querySelector("cti-simple-timer-selector")).toBeNull();
  });
});
