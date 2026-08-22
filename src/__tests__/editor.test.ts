import { describe, it, expect, vi, beforeEach } from "vitest";
import { ClimateTimerCardEditor } from "../components/climate-timer-card-editor";
import { ClimateTimerCard } from "../components/climate-timer-card";
import { HomeAssistant } from "../ha-types";
import { ClimateTimerCardConfig } from "../types";
import { filterClimateEntities } from "../utils/entity-utils";

if (!customElements.get("climate-timer-card-editor")) {
  customElements.define("climate-timer-card-editor", ClimateTimerCardEditor);
}
if (!customElements.get("climate-timer-card")) {
  customElements.define("climate-timer-card", ClimateTimerCard);
}

function createMockHass(entities: Record<string, any> = {}): HomeAssistant {
  return {
    states: entities,
    callService: vi.fn().mockResolvedValue(undefined),
    connection: {},
  };
}

function createMockConfig(
  overrides: Partial<ClimateTimerCardConfig> = {}
): ClimateTimerCardConfig {
  return {
    type: "custom:climate-timer-card",
    entity: "climate.living_room_ac",
    ...overrides,
  };
}

describe("ClimateTimerCardEditor", () => {
  let editor: ClimateTimerCardEditor;

  beforeEach(() => {
    editor = new ClimateTimerCardEditor();
  });

  describe("setConfig", () => {
    it("stores the provided config", () => {
      const config = createMockConfig();
      editor.setConfig(config);
      expect((editor as any)._config).toEqual(config);
    });

    it("creates a copy of the config (does not mutate original)", () => {
      const config = createMockConfig();
      editor.setConfig(config);
      config.entity = "climate.changed";
      expect((editor as any)._config.entity).toBe("climate.living_room_ac");
    });
  });

  describe("entity validation", () => {
    it("returns error when entity does not exist in hass.states", () => {
      editor.hass = createMockHass({
        "climate.bedroom": { entity_id: "climate.bedroom", state: "off", attributes: { friendly_name: "Bedroom AC" } },
      });
      editor.setConfig(createMockConfig({ entity: "climate.nonexistent" }));
      const error = (editor as any)._getEntityError();
      expect(error).toBe('Entity "climate.nonexistent" not found');
    });

    it("returns error when entity is not in climate domain", () => {
      editor.hass = createMockHass({
        "switch.fan": { entity_id: "switch.fan", state: "off", attributes: { friendly_name: "Fan" } },
      });
      editor.setConfig(createMockConfig({ entity: "switch.fan" }));
      const error = (editor as any)._getEntityError();
      expect(error).toBe('Entity "switch.fan" is not a climate domain entity');
    });

    it("returns null when entity is valid", () => {
      editor.hass = createMockHass({
        "climate.living_room_ac": { entity_id: "climate.living_room_ac", state: "off", attributes: { friendly_name: "Living Room AC" } },
      });
      editor.setConfig(createMockConfig());
      const error = (editor as any)._getEntityError();
      expect(error).toBeNull();
    });

    it("returns null when entity is empty (not yet selected)", () => {
      editor.hass = createMockHass({});
      editor.setConfig(createMockConfig({ entity: "" }));
      const error = (editor as any)._getEntityError();
      expect(error).toBeNull();
    });
  });

  describe("config-changed event", () => {
    it("fires config-changed when climate entity changes", () => {
      editor.hass = createMockHass({
        "climate.living_room_ac": { entity_id: "climate.living_room_ac", state: "off", attributes: { friendly_name: "Living Room AC" } },
        "climate.bedroom": { entity_id: "climate.bedroom", state: "off", attributes: { friendly_name: "Bedroom AC" } },
      });
      editor.setConfig(createMockConfig());

      const handler = vi.fn();
      editor.addEventListener("config-changed", handler as EventListener);

      (editor as any)._entityChanged({ target: { value: "climate.bedroom" } } as any);

      expect(handler).toHaveBeenCalledTimes(1);
      const event = handler.mock.calls[0][0] as CustomEvent;
      expect(event.detail.config.entity).toBe("climate.bedroom");
    });

    it("fires config-changed with bubbles and composed", () => {
      editor.hass = createMockHass({});
      editor.setConfig(createMockConfig());

      const handler = vi.fn();
      editor.addEventListener("config-changed", handler as EventListener);

      (editor as any)._entityChanged({ target: { value: "climate.new" } } as any);

      const event = handler.mock.calls[0][0] as CustomEvent;
      expect(event.bubbles).toBe(true);
      expect(event.composed).toBe(true);
    });
  });

  describe("UI mode control", () => {
    it("renders exactly two options ('Rotary' and 'Simple')", async () => {
      editor.hass = createMockHass({
        "climate.living_room_ac": { entity_id: "climate.living_room_ac", state: "off", attributes: { friendly_name: "Living Room AC" } },
      });
      editor.setConfig(createMockConfig());
      document.body.appendChild(editor);
      await editor.updateComplete;

      const uiModeSelect = editor.shadowRoot!.querySelector("#ui_mode") as HTMLSelectElement;
      expect(uiModeSelect).not.toBeNull();
      const options = uiModeSelect.querySelectorAll("option");
      expect(options.length).toBe(2);
      expect(options[0].value).toBe("rotary");
      expect(options[1].value).toBe("simple");

      document.body.removeChild(editor);
    });

    it("defaults selection to 'rotary' when ui_mode is undefined", async () => {
      editor.hass = createMockHass({
        "climate.living_room_ac": { entity_id: "climate.living_room_ac", state: "off", attributes: { friendly_name: "Living Room AC" } },
      });
      editor.setConfig(createMockConfig());
      document.body.appendChild(editor);
      await editor.updateComplete;

      const uiModeSelect = editor.shadowRoot!.querySelector("#ui_mode") as HTMLSelectElement;
      expect(uiModeSelect.value).toBe("rotary");

      document.body.removeChild(editor);
    });

    it("reflects 'simple' when config has ui_mode set to 'simple'", async () => {
      editor.hass = createMockHass({
        "climate.living_room_ac": { entity_id: "climate.living_room_ac", state: "off", attributes: { friendly_name: "Living Room AC" } },
      });
      editor.setConfig(createMockConfig({ ui_mode: "simple" }));
      document.body.appendChild(editor);
      await editor.updateComplete;

      const uiModeSelect = editor.shadowRoot!.querySelector("#ui_mode") as HTMLSelectElement;
      expect(uiModeSelect.value).toBe("simple");

      document.body.removeChild(editor);
    });

    it("fires config-changed with correct ui_mode when selection changes", () => {
      editor.hass = createMockHass({
        "climate.living_room_ac": { entity_id: "climate.living_room_ac", state: "off", attributes: { friendly_name: "Living Room AC" } },
      });
      editor.setConfig(createMockConfig());

      const handler = vi.fn();
      editor.addEventListener("config-changed", handler as EventListener);

      (editor as any)._uiModeChanged({ target: { value: "simple" } } as any);

      expect(handler).toHaveBeenCalledTimes(1);
      const event = handler.mock.calls[0][0] as CustomEvent;
      expect(event.detail.config.ui_mode).toBe("simple");
      expect(event.detail.config.entity).toBe("climate.living_room_ac");
    });
  });

  describe("entity dropdown filtering", () => {
    it("only lists climate entities in the climate dropdown", () => {
      editor.hass = createMockHass({
        "climate.ac": { entity_id: "climate.ac", state: "off", attributes: { friendly_name: "AC" } },
        "light.lamp": { entity_id: "light.lamp", state: "on", attributes: { friendly_name: "Lamp" } },
        "climate.heater": { entity_id: "climate.heater", state: "heat", attributes: { friendly_name: "Heater" } },
        "timer.my_timer": { entity_id: "timer.my_timer", state: "idle", attributes: { friendly_name: "My Timer" } },
      });
      editor.setConfig(createMockConfig({ entity: "" }));

      const result = filterClimateEntities(editor.hass.states);
      expect(result).toEqual(["climate.ac", "climate.heater"]);
    });
  });
});
