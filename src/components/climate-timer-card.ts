import { LitElement, html, css, nothing, PropertyValues } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { HomeAssistant } from "../ha-types";
import { ClimateTimerCardConfig } from "../types";
import { minutesToHADuration, parseDurationString, MAX_DURATION, STEP, resolveUiMode } from "../utils/duration-utils";
import "./timer-selector";
import "./simple-timer-selector";
import "./timer-display";

/**
 * ClimateTimerCard - Main card component for the Climate Timer Card.
 *
 * Requires the Climate Timer integration to be installed. The integration
 * manages timer helpers, HVAC mode persistence, and climate shutdown
 * automatically. The card discovers the managed timer by naming convention
 * and delegates start/cancel to integration services.
 */
@customElement("climate-timer-integration-card")
export class ClimateTimerCard extends LitElement {
  // HA injected properties
  @property({ attribute: false })
  hass!: HomeAssistant;

  @state()
  private _config!: ClimateTimerCardConfig;

  // Internal state
  @state()
  private _selectedDuration = 30;

  @state()
  private _errorMessage: string | null = null;

  private _displayIntervalId: number | null = null;

  // Track previous timer state for transition detection
  private _previousTimerState: string | undefined;

  // Track previous climate state for external change detection
  private _previousClimateState: string | undefined;

  // --- HA Custom Card Interface ---

  static getConfigElement(): HTMLElement {
    return document.createElement("climate-timer-integration-card-editor");
  }

  static getStubConfig(): ClimateTimerCardConfig {
    return {
      type: "custom:climate-timer-integration-card",
      entity: "",
    };
  }

  setConfig(config: ClimateTimerCardConfig): void {
    if (!config.entity) {
      throw new Error("Please define entity in the card configuration.");
    }
    this._config = config;
  }

  getCardSize(): number {
    return 3;
  }

  getLayoutOptions() {
    return {
      grid_columns: 2,
      grid_min_columns: 2,
      grid_rows: 3,
      grid_min_rows: 2,
    };
  }

  // --- Computed Getters ---

  /**
   * Discovers the managed timer entity using the integration's naming convention.
   * Pattern: sensor.climate_timer_{entity_slug}
   */
  private get _managedTimerEntity(): string | null {
    if (!this._config?.entity) return null;
    const slug = this._config.entity.replace(/\./g, "_");
    const managed = `sensor.climate_timer_${slug}`;
    if (this.hass?.states[managed]) {
      return managed;
    }
    return null;
  }

  private get _isTimerActive(): boolean {
    const timerEntity = this._managedTimerEntity;
    if (!timerEntity) return false;
    return this.hass?.states[timerEntity]?.state === "active";
  }

  private get _timerFinishesAt(): string | null {
    const timerEntity = this._managedTimerEntity;
    if (!timerEntity) return null;
    return this.hass?.states[timerEntity]?.attributes?.finishes_at ?? null;
  }

  private get _timerDuration(): string {
    const timerEntity = this._managedTimerEntity;
    if (!timerEntity) return "00:30:00";
    return this.hass?.states[timerEntity]?.attributes?.duration ?? "00:30:00";
  }

  private get _isClimateUnavailable(): boolean {
    const state = this._climateState;
    return state === "unavailable" || state === undefined;
  }

  private get _isTimerUnavailable(): boolean {
    const timerEntity = this._managedTimerEntity;
    if (!timerEntity) return true;
    const timerState = this.hass?.states[timerEntity];
    return !timerState || timerState.state === "unavailable";
  }

  private get _climateFriendlyName(): string {
    return (
      this.hass?.states[this._config?.entity]?.attributes?.friendly_name ||
      this._config?.entity ||
      "Climate"
    );
  }

  private get _climateState(): string | undefined {
    return this.hass?.states[this._config?.entity]?.state;
  }

  private get _configMaxDuration(): number {
    if (this._config?.max_duration) {
      const parsed = parseDurationString(this._config.max_duration);
      if (parsed !== null) return parsed;
    }
    return MAX_DURATION;
  }

  private get _configStep(): number {
    if (this._config?.step) {
      const parsed = parseDurationString(this._config.step);
      if (parsed !== null) return parsed;
    }
    return STEP;
  }

  // --- Lifecycle ---

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this._stopDisplayInterval();
  }

  connectedCallback(): void {
    super.connectedCallback();
    if (this._isTimerActive) {
      this._startDisplayInterval();
    }
  }

  protected updated(changedProperties: PropertyValues): void {
    super.updated(changedProperties);

    const timerEntity = this._managedTimerEntity;

    // Detect timer active/idle transitions
    const currentTimerState = timerEntity
      ? this.hass?.states[timerEntity]?.state
      : undefined;

    if (this._previousTimerState !== currentTimerState) {
      if (currentTimerState === "active" && this._previousTimerState !== "active") {
        this._startDisplayInterval();
      } else if (currentTimerState !== "active" && this._previousTimerState === "active") {
        this._stopDisplayInterval();
      }
      this._previousTimerState = currentTimerState;
    }

    // Detect climate entity state changes for external change handling
    const currentClimateState = this.hass?.states[this._config?.entity]?.state;
    if (this._previousClimateState !== currentClimateState) {
      // Climate turned off externally during active countdown
      if (
        this._isTimerActive &&
        currentClimateState === "off" &&
        this._previousClimateState !== "off"
      ) {
        this._handleExternalClimateOff();
      }

      // Climate became unavailable during active countdown
      if (
        this._isTimerActive &&
        (currentClimateState === "unavailable" || !currentClimateState) &&
        this._previousClimateState !== "unavailable" &&
        this._previousClimateState !== undefined
      ) {
        this._handleClimateUnavailableDuringCountdown();
      }

      this._previousClimateState = currentClimateState;
    }
  }

  // --- External Change Handlers ---

  private _handleExternalClimateOff(): void {
    if (!this.hass || !this._managedTimerEntity) return;
    this.hass
      .callService("climate_timer", "cancel", { entity_id: this._config.entity })
      .catch(() => { /* best-effort */ });
    this._stopDisplayInterval();
  }

  private _handleClimateUnavailableDuringCountdown(): void {
    if (!this.hass || !this._managedTimerEntity) return;
    this._stopDisplayInterval();
    this.hass
      .callService("climate_timer", "cancel", { entity_id: this._config.entity })
      .catch(() => { /* best-effort */ });
  }

  // --- Display Interval Management ---

  private _startDisplayInterval(): void {
    this._stopDisplayInterval();
    this._displayIntervalId = window.setInterval(() => {
      this.requestUpdate();
    }, 1000);
  }

  private _stopDisplayInterval(): void {
    if (this._displayIntervalId !== null) {
      window.clearInterval(this._displayIntervalId);
      this._displayIntervalId = null;
    }
  }

  // --- Action Handlers ---

  private async _handleStart(): Promise<void> {
    this._errorMessage = null;
    try {
      const duration = minutesToHADuration(this._selectedDuration);
      await this.hass.callService('climate_timer', 'start', {
        entity_id: this._config.entity,
        duration,
      });
    } catch (e) {
      this._showError('Failed to start climate timer');
    }
  }

  private async _handleCancel(): Promise<void> {
    this._errorMessage = null;
    try {
      await this.hass.callService('climate_timer', 'cancel', {
        entity_id: this._config.entity,
      });
    } catch (e) {
      this._showError('Failed to cancel climate timer');
    }
  }

  private _showError(message: string): void {
    this._errorMessage = message;
    setTimeout(() => {
      this._errorMessage = null;
    }, 5000);
  }

  private _handleDurationChange(e: CustomEvent): void {
    this._selectedDuration = e.detail.duration;
  }

  // --- Rendering ---

  static styles = css`
    :host {
      display: block;
    }

    .card-content {
      padding: 0 16px 16px 16px;
      display: flex;
      flex-direction: column;
      align-items: center;
    }

    .header {
      text-align: center;
      width: 100%;
      padding-top: 16px;
      margin-bottom: 12px;
    }

    .entity-name {
      font-size: 1.1rem;
      font-weight: 500;
      color: var(--primary-text-color);
    }

    .entity-state {
      font-size: 0.85rem;
      color: var(--secondary-text-color);
      text-transform: capitalize;
    }

    .start-btn {
      padding: 12px 32px;
      background: var(--primary-color, #03a9f4);
      color: white;
      border-radius: 24px;
      border: none;
      font-size: 1rem;
      cursor: pointer;
      margin-top: 12px;
    }

    .start-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .cancel-btn {
      padding: 12px 32px;
      background: var(--error-color, #db4437);
      color: white;
      border-radius: 24px;
      border: none;
      font-size: 1rem;
      cursor: pointer;
      margin-top: 12px;
    }

    .error {
      color: var(--error-color);
      font-size: 0.85rem;
      text-align: center;
    }

    .unavailable {
      font-size: 0.8rem;
      color: var(--error-color);
      text-align: center;
    }

    .config-message {
      padding: 16px;
      text-align: center;
      color: var(--secondary-text-color);
      font-size: 0.9rem;
    }
  `;

  protected render() {
    if (!this._config) {
      return nothing;
    }

    if (!this._config.entity) {
      return html`
        <ha-card>
          <div class="config-message">
            Select a climate entity to configure this card.
          </div>
        </ha-card>
      `;
    }

    if (!this._config.entity.startsWith("climate.")) {
      return html`
        <ha-card>
          <div class="card-content">
            <div class="error">Invalid entity: ${this._config.entity} is not a climate entity.</div>
          </div>
        </ha-card>
      `;
    }

    if (!this._managedTimerEntity) {
      return html`
        <ha-card>
          <div class="config-message">
            No managed timer found for ${this._config.entity}.<br>
            Please add this climate entity in the Climate Timer integration settings.
          </div>
        </ha-card>
      `;
    }

    return html`
      <ha-card>
        <div class="card-content">
          ${this._config.show_name !== false || this._config.show_state !== false
            ? html`<div class="header">
                ${this._config.show_name !== false ? html`<div class="entity-name">${this._climateFriendlyName}</div>` : nothing}
                ${this._config.show_state !== false ? html`<div class="entity-state">${this._climateState ?? ""}</div>` : nothing}
              </div>`
            : nothing}

          ${resolveUiMode(this._config) === "simple"
            ? html`<cti-simple-timer-selector
                .duration=${this._selectedDuration}
                .disabled=${this._isTimerActive}
                .maxDuration=${this._configMaxDuration}
                .stepSize=${this._configStep}
                .finishesAt=${this._timerFinishesAt}
                .durationStr=${this._timerDuration}
                .timerActive=${this._isTimerActive}
                @duration-changed=${this._handleDurationChange}
              ></cti-simple-timer-selector>`
            : html`<cti-timer-selector
                .duration=${this._selectedDuration}
                .disabled=${this._isTimerActive}
                .maxDuration=${this._configMaxDuration}
                .stepSize=${this._configStep}
                .finishesAt=${this._timerFinishesAt}
                .durationStr=${this._timerDuration}
                .timerActive=${this._isTimerActive}
                @duration-changed=${this._handleDurationChange}
              ></cti-timer-selector>`}

          ${this._errorMessage ? html`<div class="error">${this._errorMessage}</div>` : nothing}

          ${!this._isTimerActive
            ? html`
                <button
                  class="start-btn"
                  @click=${this._handleStart}
                  ?disabled=${this._isClimateUnavailable || this._isTimerUnavailable}
                >
                  Start
                </button>
              `
            : html`
                <button class="cancel-btn" @click=${this._handleCancel}>
                  Cancel
                </button>
              `}

          ${this._isClimateUnavailable ? html`<div class="unavailable">Entity unavailable</div>` : nothing}
        </div>
      </ha-card>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "climate-timer-integration-card": ClimateTimerCard;
  }
}
