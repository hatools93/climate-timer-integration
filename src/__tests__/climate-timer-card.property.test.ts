import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fc from "fast-check";
import "../components/climate-timer-card";
import type { ClimateTimerCard } from "../components/climate-timer-card";
import type { HomeAssistant } from "../ha-types";
import { minutesToHADuration } from "../utils/duration-utils";

function createMockHass(overrides?: Partial<any>): HomeAssistant {
  return {
    states: {
      "climate.test_ac": {
        entity_id: "climate.test_ac",
        state: "off",
        attributes: {
          friendly_name: "Test AC",
          hvac_modes: ["off", "heat", "cool", "dry", "fan_only"],
          temperature: 24,
          current_temperature: 25,
        },
      },
      "timer.climate_timer_climate_test_ac": {
        entity_id: "timer.climate_timer_climate_test_ac",
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

describe("Property: Start calls climate_timer.start with correct entity and duration", () => {
  let el: ClimateTimerCard;

  beforeEach(() => {
    el = createCard();
    document.body.appendChild(el);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    el.remove();
  });

  it("should call climate_timer.start with entity_id and formatted duration for any valid duration", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 240 }),
        async (durationMinutes) => {
          vi.restoreAllMocks();
          const callService = vi.fn().mockResolvedValue(undefined);

          el.hass = createMockHass({ callService });
          await el.updateComplete;

          (el as any)._selectedDuration = durationMinutes;
          await el.updateComplete;

          const startBtn = el.shadowRoot!.querySelector(".start-btn") as HTMLButtonElement;
          expect(startBtn).not.toBeNull();
          startBtn.click();

          await vi.waitFor(() => {
            expect(callService).toHaveBeenCalledTimes(1);
          });

          const expectedDuration = minutesToHADuration(durationMinutes);
          expect(callService).toHaveBeenCalledWith(
            "climate_timer",
            "start",
            { entity_id: "climate.test_ac", duration: expectedDuration }
          );
          expect(expectedDuration).toMatch(/^\d{2}:\d{2}:00$/);
        }
      ),
      { numRuns: 50 }
    );
  });

  it("should call climate_timer.start regardless of climate entity state", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.constantFrom("off", "heat", "cool", "dry", "fan_only"),
        fc.integer({ min: 1, max: 240 }),
        async (climateState, durationMinutes) => {
          vi.restoreAllMocks();
          const callService = vi.fn().mockResolvedValue(undefined);

          el.hass = createMockHass({
            states: {
              "climate.test_ac": {
                entity_id: "climate.test_ac",
                state: climateState,
                attributes: { friendly_name: "Test AC", hvac_modes: ["off", "heat", "cool", "dry", "fan_only"], temperature: 24, current_temperature: 25 },
              },
              "timer.climate_timer_climate_test_ac": {
                entity_id: "timer.climate_timer_climate_test_ac",
                state: "idle",
                attributes: { duration: "00:30:00", remaining: "00:00:00", finishes_at: "", friendly_name: "Climate Timer", restore: true },
              },
            },
            callService,
          });
          await el.updateComplete;

          (el as any)._selectedDuration = durationMinutes;
          await el.updateComplete;

          const startBtn = el.shadowRoot!.querySelector(".start-btn") as HTMLButtonElement;
          expect(startBtn).not.toBeNull();
          startBtn.click();

          await vi.waitFor(() => {
            expect(callService).toHaveBeenCalledTimes(1);
          });

          expect(callService).toHaveBeenCalledWith(
            "climate_timer",
            "start",
            { entity_id: "climate.test_ac", duration: minutesToHADuration(durationMinutes) }
          );

          // No legacy climate service calls
          const climateCalls = callService.mock.calls.filter((call: any[]) => call[0] === "climate");
          expect(climateCalls).toHaveLength(0);
        }
      ),
      { numRuns: 50 }
    );
  });
});

describe("Property: Cancel calls climate_timer.cancel with correct entity", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("should call climate_timer.cancel with entity_id when timer is active", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.constantFrom("heat", "cool", "dry", "fan_only"),
        async (activeMode) => {
          vi.restoreAllMocks();
          const callService = vi.fn().mockResolvedValue(undefined);

          const card = document.createElement("climate-timer-integration-card") as ClimateTimerCard;
          card.setConfig({ type: "custom:climate-timer-integration-card", entity: "climate.test_ac" });
          document.body.appendChild(card);

          try {
            const finishesAt = new Date(Date.now() + 15 * 60 * 1000).toISOString();
            card.hass = createMockHass({
              states: {
                "climate.test_ac": {
                  entity_id: "climate.test_ac",
                  state: activeMode,
                  attributes: { friendly_name: "Test AC", hvac_modes: ["off", "heat", "cool", "dry", "fan_only"], temperature: 24, current_temperature: 25 },
                },
                "timer.climate_timer_climate_test_ac": {
                  entity_id: "timer.climate_timer_climate_test_ac",
                  state: "active",
                  attributes: { duration: "00:30:00", remaining: "00:15:00", finishes_at: finishesAt, friendly_name: "Climate Timer", restore: true },
                },
              },
              callService,
            });
            await card.updateComplete;

            const cancelBtn = card.shadowRoot!.querySelector(".cancel-btn") as HTMLButtonElement;
            expect(cancelBtn).not.toBeNull();
            cancelBtn.click();

            await vi.waitFor(() => {
              expect(callService).toHaveBeenCalledTimes(1);
            });

            expect(callService).toHaveBeenCalledWith("climate_timer", "cancel", { entity_id: "climate.test_ac" });
          } finally {
            card.remove();
          }
        }
      ),
      { numRuns: 20 }
    );
  });
});

describe("Property: Managed timer entity naming convention", () => {
  it("should derive managed timer entity from climate entity using naming convention", async () => {
    const entities = ["climate.living_room_ac", "climate.bedroom_heater", "climate.test_ac"];

    for (const entityId of entities) {
      const card = document.createElement("climate-timer-integration-card") as ClimateTimerCard;
      card.setConfig({ type: "custom:climate-timer-integration-card", entity: entityId });
      document.body.appendChild(card);

      const expected = `timer.climate_timer_${entityId.replace(".", "_")}`;
      card.hass = {
        states: {
          [entityId]: { entity_id: entityId, state: "off", attributes: { friendly_name: "Test", hvac_modes: ["off"], temperature: 24, current_temperature: 25 } },
          [expected]: { entity_id: expected, state: "idle", attributes: { duration: "00:30:00", remaining: "00:00:00", finishes_at: "", friendly_name: "Climate Timer", restore: true } },
        },
        callService: vi.fn().mockResolvedValue(undefined),
        connection: {},
      };
      await card.updateComplete;

      expect((card as any)._managedTimerEntity).toBe(expected);
      card.remove();
    }
  });
});
