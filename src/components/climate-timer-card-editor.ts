import { LitElement, html, css } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { HomeAssistant } from "../ha-types";
import { ClimateTimerCardConfig } from "../types";
import { filterClimateEntities } from "../utils/entity-utils";
import { validateDurationConfig } from "../utils/duration-utils";

/**
 * Visual configuration editor for the Climate Timer Card.
 * Shown in HA's card editor panel.
 *
 * Only requires selecting a climate entity — the integration handles
 * timer management and HVAC mode persistence automatically.
 */
@customElement("climate-timer-card-editor")
export class ClimateTimerCardEditor extends LitElement {
  @property({ attribute: false })
  hass!: HomeAssistant;

  @state()
  private _config!: ClimateTimerCardConfig;

  setConfig(config: ClimateTimerCardConfig): void {
    this._config = { ...config };
  }

  static styles = css`
    :host {
      display: block;
    }

    .editor-row {
      display: flex;
      flex-direction: column;
      margin-bottom: 16px;
    }

    label {
      font-weight: 500;
      margin-bottom: 4px;
      color: var(--primary-text-color, #333);
    }

    select {
      padding: 8px;
      border: 1px solid var(--divider-color, #ccc);
      border-radius: 4px;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color, #333);
      font-size: 1rem;
    }

    .error {
      color: var(--error-color, #db4437);
      font-size: 0.85rem;
      margin-top: 4px;
    }

    input {
      padding: 8px;
      border: 1px solid var(--divider-color, #ccc);
      border-radius: 4px;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color, #333);
      font-size: 1rem;
      width: 100px;
    }

    .help-text {
      font-size: 0.75rem;
      color: var(--secondary-text-color, #666);
      margin-top: 2px;
    }

    .integration-note {
      font-size: 0.85rem;
      color: var(--success-color, #4caf50);
      font-weight: 500;
    }

    .integration-warning {
      font-size: 0.85rem;
      color: var(--warning-color, #ff9800);
    }

    .toggle-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
    }

    .toggle-row label {
      margin-bottom: 0;
    }

    .toggle-switch {
      position: relative;
      width: 40px;
      height: 22px;
    }

    .toggle-switch input {
      opacity: 0;
      width: 0;
      height: 0;
    }

    .toggle-slider {
      position: absolute;
      cursor: pointer;
      inset: 0;
      background: var(--divider-color, #ccc);
      border-radius: 22px;
      transition: background 0.2s;
    }

    .toggle-slider::before {
      content: "";
      position: absolute;
      width: 16px;
      height: 16px;
      left: 3px;
      bottom: 3px;
      background: white;
      border-radius: 50%;
      transition: transform 0.2s;
    }

    .toggle-switch input:checked + .toggle-slider {
      background: var(--primary-color, #03a9f4);
    }

    .toggle-switch input:checked + .toggle-slider::before {
      transform: translateX(18px);
    }
  `;

  protected render() {
    if (!this.hass || !this._config) {
      return html``;
    }

    const climateEntities = filterClimateEntities(this.hass.states);
    const entityError = this._getEntityError();
    const hasManagedTimer = this._hasManagedTimer();

    return html`
      <div class="editor-row">
        <label for="entity">Climate Entity</label>
        <select
          id="entity"
          .value=${this._config.entity || ""}
          @change=${this._entityChanged}
        >
          <option value="">-- Select climate entity --</option>
          ${climateEntities.map(
            (entityId) => html`
              <option
                value=${entityId}
                ?selected=${entityId === this._config.entity}
              >
                ${this.hass.states[entityId]?.attributes?.friendly_name || entityId}
              </option>
            `
          )}
        </select>
        ${entityError ? html`<span class="error">${entityError}</span>` : ""}
      </div>

      ${this._config.entity
        ? html`<div class="editor-row">
            ${hasManagedTimer
              ? html`<span class="integration-note">&#10003; Managed by Climate Timer integration</span>`
              : html`<span class="integration-warning">&#9888; Add this entity in Settings &gt; Devices &amp; Services &gt; Climate Timer</span>`
            }
          </div>`
        : ""}

      <div class="editor-row">
        <label for="max_duration">Max Duration</label>
        <input
          id="max_duration"
          type="text"
          .value=${this._config.max_duration || "4h"}
          @change=${this._maxDurationChanged}
          placeholder="4h"
        />
        <span class="help-text">e.g. "4h", "240m", "2h30m"</span>
      </div>

      <div class="editor-row">
        <label for="step">Step</label>
        <input
          id="step"
          type="text"
          .value=${this._config.step || "15m"}
          @change=${this._stepChanged}
          placeholder="15m"
        />
        <span class="help-text">e.g. "15m", "30m", "1h"</span>
      </div>

      <div class="toggle-row">
        <label>Show Name</label>
        <label class="toggle-switch">
          <input
            type="checkbox"
            .checked=${this._config.show_name !== false}
            @change=${this._showNameChanged}
          />
          <span class="toggle-slider"></span>
        </label>
      </div>

      <div class="toggle-row">
        <label>Show State</label>
        <label class="toggle-switch">
          <input
            type="checkbox"
            .checked=${this._config.show_state !== false}
            @change=${this._showStateChanged}
          />
          <span class="toggle-slider"></span>
        </label>
      </div>

      <div class="editor-row">
        <label for="ui_mode">UI Mode</label>
        <select
          id="ui_mode"
          .value=${this._config.ui_mode || "rotary"}
          @change=${this._uiModeChanged}
        >
          <option
            value="rotary"
            ?selected=${(this._config.ui_mode || "rotary") === "rotary"}
          >
            Rotary
          </option>
          <option
            value="simple"
            ?selected=${this._config.ui_mode === "simple"}
          >
            Simple
          </option>
        </select>
      </div>

      ${this._getDurationConfigError()
        ? html`<div class="editor-row"><span class="error">${this._getDurationConfigError()}</span></div>`
        : ""}
    `;
  }

  private _hasManagedTimer(): boolean {
    if (!this._config?.entity || !this.hass) return false;
    const slug = this._config.entity.replace(/\./g, "_");
    const managed = `timer.climate_timer_${slug}`;
    return !!this.hass.states[managed];
  }

  private _getEntityError(): string | null {
    const entity = this._config.entity;
    if (!entity) return null;

    if (!this.hass.states[entity]) {
      return `Entity "${entity}" not found`;
    }

    if (!entity.startsWith("climate.")) {
      return `Entity "${entity}" is not a climate domain entity`;
    }

    return null;
  }

  private _entityChanged(e: Event): void {
    const target = e.target as HTMLSelectElement;
    this._config = { ...this._config, entity: target.value };
    this._fireConfigChanged();
  }

  private _maxDurationChanged(e: Event): void {
    const target = e.target as HTMLInputElement;
    this._config = { ...this._config, max_duration: target.value.trim() };
    this._fireConfigChanged();
  }

  private _stepChanged(e: Event): void {
    const target = e.target as HTMLInputElement;
    this._config = { ...this._config, step: target.value.trim() };
    this._fireConfigChanged();
  }

  private _showNameChanged(e: Event): void {
    const target = e.target as HTMLInputElement;
    this._config = { ...this._config, show_name: target.checked };
    this._fireConfigChanged();
  }

  private _showStateChanged(e: Event): void {
    const target = e.target as HTMLInputElement;
    this._config = { ...this._config, show_state: target.checked };
    this._fireConfigChanged();
  }

  private _uiModeChanged(e: Event): void {
    const target = e.target as HTMLSelectElement;
    this._config = {
      ...this._config,
      ui_mode: target.value as "rotary" | "simple",
    };
    this._fireConfigChanged();
  }

  private _getDurationConfigError(): string | null {
    const maxDuration = this._config.max_duration || "4h";
    const step = this._config.step || "15m";
    return validateDurationConfig(maxDuration, step);
  }

  private _fireConfigChanged(): void {
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: { ...this._config } },
        bubbles: true,
        composed: true,
      })
    );
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "climate-timer-card-editor": ClimateTimerCardEditor;
  }
}
