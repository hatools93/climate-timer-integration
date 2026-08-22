import { describe, it, expect, vi, beforeEach } from "vitest";
import * as fc from "fast-check";
import { ClimateTimerCardEditor } from "../components/climate-timer-card-editor";
import { ClimateTimerCardConfig } from "../types";
import { HomeAssistant } from "../ha-types";

if (!customElements.get("climate-timer-card-editor")) {
  customElements.define("climate-timer-card-editor", ClimateTimerCardEditor);
}

function createMockHass(entities: Record<string, any> = {}): HomeAssistant {
  return {
    states: entities,
    callService: vi.fn().mockResolvedValue(undefined),
    connection: {},
  };
}

const entityArb = fc.stringMatching(/^climate\.[a-z_]{1,20}$/);
const maxDurationArb = fc.oneof(fc.constant(undefined), fc.constant("4h"), fc.constant("2h"), fc.constant("240m"));
const stepArb = fc.oneof(fc.constant(undefined), fc.constant("15m"), fc.constant("30m"), fc.constant("5m"));
const showNameArb = fc.oneof(fc.constant(undefined), fc.constant(true), fc.constant(false));
const showStateArb = fc.oneof(fc.constant(undefined), fc.constant(true), fc.constant(false));
const existingUiModeArb = fc.oneof(fc.constant(undefined), fc.constant("rotary" as const), fc.constant("simple" as const));
const newUiModeArb = fc.oneof(fc.constant("rotary" as const), fc.constant("simple" as const));

const configArb = fc.record({
  type: fc.constant("custom:climate-timer-card"),
  entity: entityArb,
  max_duration: maxDurationArb,
  step: stepArb,
  show_name: showNameArb,
  show_state: showStateArb,
  ui_mode: existingUiModeArb,
}).map((rec) => {
  const config: Record<string, any> = { type: rec.type, entity: rec.entity };
  if (rec.max_duration !== undefined) config.max_duration = rec.max_duration;
  if (rec.step !== undefined) config.step = rec.step;
  if (rec.show_name !== undefined) config.show_name = rec.show_name;
  if (rec.show_state !== undefined) config.show_state = rec.show_state;
  if (rec.ui_mode !== undefined) config.ui_mode = rec.ui_mode;
  return config as ClimateTimerCardConfig;
});

describe("Property: Editor Config-Changed Event Completeness", () => {
  let editor: ClimateTimerCardEditor;

  beforeEach(() => {
    editor = new ClimateTimerCardEditor();
    editor.hass = createMockHass({
      "climate.test": { entity_id: "climate.test", state: "off", attributes: { friendly_name: "Test" } },
    });
  });

  it("config-changed event contains all original properties plus ui_mode set to selected value", () => {
    fc.assert(
      fc.property(configArb, newUiModeArb, (config, newMode) => {
        editor.setConfig(config);

        const handler = vi.fn();
        editor.addEventListener("config-changed", handler as EventListener);

        (editor as any)._uiModeChanged({ target: { value: newMode } } as any);

        expect(handler).toHaveBeenCalledTimes(1);
        const event = handler.mock.calls[0][0] as CustomEvent;
        const resultConfig = event.detail.config;

        expect(resultConfig.type).toBe(config.type);
        expect(resultConfig.entity).toBe(config.entity);
        if (config.max_duration !== undefined) expect(resultConfig.max_duration).toBe(config.max_duration);
        if (config.step !== undefined) expect(resultConfig.step).toBe(config.step);
        if (config.show_name !== undefined) expect(resultConfig.show_name).toBe(config.show_name);
        if (config.show_state !== undefined) expect(resultConfig.show_state).toBe(config.show_state);
        expect(resultConfig.ui_mode).toBe(newMode);

        editor.removeEventListener("config-changed", handler as EventListener);
      }),
      { numRuns: 100 }
    );
  });

  it("config-changed event has bubbles: true and composed: true", () => {
    fc.assert(
      fc.property(configArb, newUiModeArb, (config, newMode) => {
        editor.setConfig(config);

        const handler = vi.fn();
        editor.addEventListener("config-changed", handler as EventListener);

        (editor as any)._uiModeChanged({ target: { value: newMode } } as any);

        const event = handler.mock.calls[0][0] as CustomEvent;
        expect(event.bubbles).toBe(true);
        expect(event.composed).toBe(true);

        editor.removeEventListener("config-changed", handler as EventListener);
      }),
      { numRuns: 100 }
    );
  });

  it("config-changed event config does not lose any keys from original config", () => {
    fc.assert(
      fc.property(configArb, newUiModeArb, (config, newMode) => {
        editor.setConfig(config);

        const handler = vi.fn();
        editor.addEventListener("config-changed", handler as EventListener);

        (editor as any)._uiModeChanged({ target: { value: newMode } } as any);

        const event = handler.mock.calls[0][0] as CustomEvent;
        const resultConfig = event.detail.config;

        for (const key of Object.keys(config)) {
          if (key === "ui_mode") {
            expect(resultConfig.ui_mode).toBe(newMode);
          } else {
            expect(resultConfig[key]).toEqual((config as any)[key]);
          }
        }
        expect(resultConfig).toHaveProperty("ui_mode");
        expect(resultConfig.ui_mode).toBe(newMode);

        editor.removeEventListener("config-changed", handler as EventListener);
      }),
      { numRuns: 100 }
    );
  });
});
