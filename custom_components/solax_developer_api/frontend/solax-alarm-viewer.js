class SolaxAlarmViewerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._connected = false;
    this._entryId = undefined;
    this._name = "SolaX Alarms";
    this._maxPages = 20;
    this._plants = [];
    this._devices = [];
    this._targetsLoaded = false;
    this._loadingTargets = false;
    this._fetching = false;
    this._selectedPlantKey = "all";
    this._selectedDeviceKey = "";
    this._alarmState = "all";
    this._records = [];
    this._lastFetchAt = undefined;
    this._lastMeta = {};
    this._lastError = undefined;
  }

  setConfig(config) {
    const cfg = config || {};
    const nextEntryId = this._cleanString(cfg.entry_id);
    if (nextEntryId !== this._entryId) {
      this._targetsLoaded = false;
      this._plants = [];
      this._devices = [];
      this._selectedPlantKey = "all";
      this._selectedDeviceKey = "";
    }
    this._entryId = nextEntryId;
    this._name = this._cleanString(cfg.name) || "SolaX Alarms";
    this._maxPages = this._toInt(cfg.max_pages, 20, 1, 100);
    this._render();
  }

  set hass(hass) {
    const hadHass = Boolean(this._hass);
    this._hass = hass;
    if (this._connected && !hadHass) {
      this._loadTargets();
      this._render();
    }
  }

  connectedCallback() {
    this._connected = true;
    this._loadTargets();
    this._render();
  }

  disconnectedCallback() {
    this._connected = false;
  }

  getCardSize() {
    return 5;
  }

  getGridOptions() {
    return {
      columns: "full",
      min_columns: 6,
    };
  }

  _cleanString(raw) {
    return typeof raw === "string" && raw.trim() ? raw.trim() : undefined;
  }

  _toInt(raw, fallback, min, max) {
    const parsed = Number.parseInt(raw, 10);
    if (!Number.isFinite(parsed)) {
      return fallback;
    }
    return Math.max(min, Math.min(max, parsed));
  }

  _servicePayload(extra = {}) {
    return this._entryId ? { entry_id: this._entryId, ...extra } : extra;
  }

  async _callService(service, payload) {
    if (this._hass?.connection?.sendMessagePromise) {
      const response = await this._hass.connection.sendMessagePromise({
        type: "call_service",
        domain: "solax_developer_api",
        service,
        service_data: payload || {},
        return_response: true,
      });
      return response?.response ?? response;
    }

    const response = await this._hass.callService(
      "solax_developer_api",
      service,
      payload,
      undefined,
      true,
      true
    );
    if (response === undefined) {
      throw new Error(
        "Home Assistant did not return service response data. Update Home Assistant or reload the dashboard resource."
      );
    }
    return response;
  }

  async _loadTargets() {
    if (!this._hass || this._loadingTargets || this._targetsLoaded) {
      return;
    }
    this._loadingTargets = true;
    this._lastError = undefined;
    this._render();
    try {
      const response = await this._callService("list_alarm_targets", this._servicePayload());
      const entries = Array.isArray(response?.entries) ? response.entries : [];
      if (entries.length === 0) {
        this._lastError = this._entryId
          ? `No loaded SolaX Developer API integration matches entry_id "${this._entryId}". Remove entry_id from the card or use the exact config entry id.`
          : "No loaded SolaX Developer API integration is available yet.";
        this._plants = [];
        this._devices = [];
        this._targetsLoaded = false;
        return;
      }
      this._plants = Array.isArray(response?.plants) ? response.plants : [];
      this._devices = Array.isArray(response?.devices) ? response.devices : [];
      this._targetsLoaded = true;
      this._ensureSelectionStillValid();
    } catch (err) {
      this._lastError = err?.message || String(err);
      this._plants = [];
      this._devices = [];
    } finally {
      this._loadingTargets = false;
      this._render();
    }
  }

  _ensureSelectionStillValid() {
    const plantKeys = new Set(["all", ...this._plants.map((plant) => this._plantKey(plant))]);
    if (!plantKeys.has(this._selectedPlantKey)) {
      this._selectedPlantKey = "all";
    }
    const deviceKeys = new Set(["", ...this._devicesForSelectedPlant().map((device) => this._deviceKey(device))]);
    if (!deviceKeys.has(this._selectedDeviceKey)) {
      this._selectedDeviceKey = "";
    }
  }

  _plantKey(plant) {
    return [
      plant.entry_id || this._entryId || "",
      plant.plant_id,
      plant.business_type,
    ].join("|");
  }

  _deviceKey(device) {
    return [
      device.entry_id || this._entryId || "",
      device.plant_id,
      device.device_sn,
      device.business_type,
    ].join("|");
  }

  _selectedPlant() {
    if (this._selectedPlantKey === "all") {
      return undefined;
    }
    return this._plants.find((plant) => this._plantKey(plant) === this._selectedPlantKey);
  }

  _selectedDevice() {
    if (!this._selectedDeviceKey) {
      return undefined;
    }
    return this._devices.find((device) => this._deviceKey(device) === this._selectedDeviceKey);
  }

  _devicesForSelectedPlant() {
    const plant = this._selectedPlant();
    if (!plant) {
      return this._devices;
    }
    return this._devices.filter((device) => String(device.plant_id) === String(plant.plant_id));
  }

  async _fetchAlarms() {
    if (!this._hass || this._fetching) {
      return;
    }
    this._fetching = true;
    this._lastError = undefined;
    this._render();
    try {
      const plant = this._selectedPlant();
      const device = this._selectedDevice();
      const payload = {
        alarm_state: this._alarmState,
        max_pages: this._maxPages,
      };
      if (plant) {
        payload.plant_id = plant.plant_id;
        payload.business_type = Number(plant.business_type);
      }
      if (device) {
        payload.device_sn = device.device_sn;
        if (!plant) {
          payload.plant_id = device.plant_id;
          payload.business_type = Number(device.business_type);
        }
      }
      const response = await this._callService(
        "fetch_alarm_information",
        this._servicePayload(payload)
      );
      this._records = Array.isArray(response?.records) ? response.records : [];
      this._lastMeta = response || {};
      this._lastFetchAt = new Date();
    } catch (err) {
      this._lastError = err?.message || String(err);
      this._records = [];
      this._lastMeta = {};
    } finally {
      this._fetching = false;
      this._render();
    }
  }

  _formatDate(raw) {
    if (!raw) {
      return "None";
    }
    const text = String(raw);
    const timestamp = Date.parse(text.replace(" ", "T"));
    if (!Number.isFinite(timestamp)) {
      return text;
    }
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(timestamp));
  }

  _stateLabel(value) {
    const state = Number(value);
    if (state === 1) {
      return "Ongoing";
    }
    if (state === 0) {
      return "Closed";
    }
    return "Unknown";
  }

  _stateClass(value) {
    const state = Number(value);
    if (state === 1) {
      return "ongoing";
    }
    if (state === 0) {
      return "closed";
    }
    return "unknown";
  }

  _shortSerial(raw) {
    const text = String(raw || "").trim();
    if (!text) {
      return "Unknown device";
    }
    if (text.length <= 12) {
      return text;
    }
    return `${text.slice(0, 5)}...${text.slice(-5)}`;
  }

  _mappedValue(rawValue, mappedValue) {
    const raw = rawValue ?? "Unknown";
    const mapped = String(mappedValue || "").trim();
    if (!mapped || mapped === String(raw)) {
      return String(raw);
    }
    return `${mapped} (${raw})`;
  }

  _escape(raw) {
    return String(raw ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  _summaryValue(key, fallback = 0) {
    const value = this._lastMeta?.state_counts?.[key];
    return Number.isFinite(Number(value)) ? Number(value) : fallback;
  }

  _targetLabel() {
    const plant = this._selectedPlant();
    const device = this._selectedDevice();
    if (device) {
      return device.label || device.device_sn;
    }
    if (plant) {
      return plant.label || plant.plant_id;
    }
    return "All plants";
  }

  _lastFetchLabel() {
    if (!this._lastFetchAt) {
      return "Never";
    }
    return new Intl.DateTimeFormat(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(this._lastFetchAt);
  }

  _render() {
    if (!this.shadowRoot) {
      return;
    }
    const statusClass = this._lastError ? "error" : this._fetching ? "loading" : "ready";
    const statusLabel = this._lastError ? "Error" : this._fetching ? "Fetching" : "Ready";
    const plantOptions = [
      `<option value="all"${this._selectedPlantKey === "all" ? " selected" : ""}>All plants</option>`,
      ...this._plants.map(
        (plant) =>
          `<option value="${this._escape(this._plantKey(plant))}"${
            this._selectedPlantKey === this._plantKey(plant) ? " selected" : ""
          }>${this._escape(plant.label || plant.plant_id)}</option>`
      ),
    ].join("");
    const deviceOptions = [
      `<option value=""${this._selectedDeviceKey === "" ? " selected" : ""}>All devices</option>`,
      ...this._devicesForSelectedPlant().map(
        (device) =>
          `<option value="${this._escape(this._deviceKey(device))}"${
            this._selectedDeviceKey === this._deviceKey(device) ? " selected" : ""
          }>${this._escape(device.label || device.device_sn)}</option>`
      ),
    ].join("");

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 100%;
          --solax-alarm-accent: #f2aa00;
          --solax-alarm-blue: #1d63c4;
          --solax-alarm-danger: #ff5548;
          --solax-alarm-good: #45b84c;
          --solax-alarm-card: color-mix(in srgb, var(--ha-card-background, #202020) 90%, transparent);
          --solax-alarm-border: color-mix(in srgb, var(--primary-text-color, #f2f2f2) 16%, transparent);
          --solax-alarm-muted: color-mix(in srgb, var(--secondary-text-color, #a9a9a9) 88%, transparent);
        }
        ha-card {
          width: 100%;
          max-width: none;
          overflow: hidden;
          border-radius: 28px;
          border: 1px solid var(--solax-alarm-border);
          background:
            radial-gradient(circle at 8% 8%, color-mix(in srgb, var(--solax-alarm-accent) 28%, transparent), transparent 34%),
            radial-gradient(circle at 88% 18%, color-mix(in srgb, var(--solax-alarm-blue) 20%, transparent), transparent 36%),
            linear-gradient(135deg, color-mix(in srgb, var(--ha-card-background, #202020) 94%, #000 6%), var(--ha-card-background, #202020));
          color: var(--primary-text-color);
          box-shadow: var(--ha-card-box-shadow, 0 18px 40px rgba(0, 0, 0, 0.22));
        }
        .wrap {
          padding: 28px;
          display: grid;
          gap: 22px;
        }
        .header {
          display: grid;
          grid-template-columns: auto 1fr auto;
          gap: 18px;
          align-items: start;
        }
        .icon {
          width: 74px;
          height: 74px;
          border-radius: 24px;
          border: 2px solid color-mix(in srgb, var(--solax-alarm-accent) 70%, transparent);
          display: grid;
          place-items: center;
          color: var(--solax-alarm-accent);
          background: color-mix(in srgb, var(--solax-alarm-accent) 12%, transparent);
        }
        .icon svg {
          width: 42px;
          height: 42px;
        }
        h2 {
          margin: 0;
          font-size: clamp(24px, 3vw, 34px);
          line-height: 1.05;
          font-weight: 800;
        }
        .subtitle {
          margin-top: 8px;
          color: var(--solax-alarm-muted);
          font-size: 18px;
          line-height: 1.35;
        }
        .status {
          justify-self: end;
          display: inline-flex;
          align-items: center;
          gap: 10px;
          padding: 12px 18px;
          border-radius: 999px;
          border: 1px solid var(--solax-alarm-border);
          background: color-mix(in srgb, var(--ha-card-background, #202020) 70%, transparent);
          text-transform: uppercase;
          font-weight: 800;
          letter-spacing: .04em;
        }
        .status::before {
          content: "";
          width: 16px;
          height: 16px;
          border-radius: 999px;
          background: var(--solax-alarm-good);
          box-shadow: 0 0 0 8px color-mix(in srgb, var(--solax-alarm-good) 18%, transparent);
        }
        .status.loading::before {
          background: var(--solax-alarm-accent);
          box-shadow: 0 0 0 8px color-mix(in srgb, var(--solax-alarm-accent) 18%, transparent);
        }
        .status.error::before {
          background: var(--solax-alarm-danger);
          box-shadow: 0 0 0 8px color-mix(in srgb, var(--solax-alarm-danger) 18%, transparent);
        }
        .controls {
          display: grid;
          grid-template-columns: minmax(180px, 1.3fr) minmax(180px, 1.3fr) minmax(140px, .8fr) auto;
          gap: 16px;
          align-items: end;
        }
        label {
          display: grid;
          gap: 9px;
          color: var(--solax-alarm-muted);
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: .05em;
        }
        select,
        button {
          min-height: 58px;
          border-radius: 18px;
          border: 1px solid var(--solax-alarm-border);
          color: var(--primary-text-color);
          font: inherit;
          font-weight: 800;
        }
        select {
          padding: 0 16px;
          background: color-mix(in srgb, var(--ha-card-background, #202020) 82%, #000 18%);
        }
        button {
          padding: 0 28px;
          border-color: color-mix(in srgb, var(--solax-alarm-blue) 70%, transparent);
          background: linear-gradient(135deg, #2275dd, #0f4ca8);
          color: #fff;
          cursor: pointer;
        }
        button[disabled] {
          cursor: wait;
          opacity: .7;
        }
        .summary {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 16px;
        }
        .tile,
        .records,
        .error-box,
        .empty {
          border: 1px solid var(--solax-alarm-border);
          background: color-mix(in srgb, var(--ha-card-background, #202020) 76%, transparent);
          border-radius: 22px;
        }
        .tile {
          padding: 20px;
        }
        .tile .label {
          color: var(--solax-alarm-muted);
          font-weight: 800;
        }
        .tile .value {
          margin-top: 9px;
          font-size: 28px;
          font-weight: 900;
        }
        .tile .hint {
          margin-top: 5px;
          color: var(--solax-alarm-muted);
        }
        .error-box {
          padding: 18px 22px;
          color: var(--solax-alarm-danger);
          border-color: color-mix(in srgb, var(--solax-alarm-danger) 50%, transparent);
          background: color-mix(in srgb, var(--solax-alarm-danger) 12%, transparent);
          font-weight: 800;
        }
        .empty {
          padding: 30px;
          text-align: center;
          color: var(--solax-alarm-muted);
          font-size: 18px;
        }
        .records {
          padding: 18px;
          display: grid;
          gap: 14px;
        }
        .record {
          padding: 18px;
          border-radius: 18px;
          border: 1px solid color-mix(in srgb, var(--primary-text-color) 10%, transparent);
          background: color-mix(in srgb, var(--ha-card-background, #202020) 82%, transparent);
        }
        .record-head {
          display: grid;
          grid-template-columns: 1fr auto;
          gap: 12px;
          align-items: start;
        }
        .record-title {
          font-size: 19px;
          font-weight: 900;
        }
        .pill {
          display: inline-flex;
          align-items: center;
          padding: 8px 12px;
          border-radius: 999px;
          font-weight: 900;
          text-transform: uppercase;
          letter-spacing: .04em;
          font-size: 12px;
        }
        .pill.ongoing {
          color: #fff;
          background: color-mix(in srgb, var(--solax-alarm-danger) 78%, #000 22%);
        }
        .pill.closed {
          color: #fff;
          background: color-mix(in srgb, var(--solax-alarm-good) 70%, #000 30%);
        }
        .pill.unknown {
          color: var(--primary-text-color);
          background: color-mix(in srgb, var(--primary-text-color) 14%, transparent);
        }
        .record-grid {
          margin-top: 14px;
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 12px;
        }
        .kv {
          min-width: 0;
        }
        .kv span {
          display: block;
          color: var(--solax-alarm-muted);
          font-size: 13px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: .04em;
        }
        .kv strong {
          display: block;
          margin-top: 4px;
          overflow-wrap: anywhere;
        }
        details {
          margin-top: 14px;
          color: var(--solax-alarm-muted);
        }
        summary {
          cursor: pointer;
          font-weight: 800;
        }
        .field-list {
          margin-top: 12px;
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 8px 16px;
        }
        .field-row {
          display: grid;
          grid-template-columns: minmax(110px, .8fr) minmax(0, 1.2fr);
          gap: 10px;
          padding: 8px 0;
          border-bottom: 1px solid color-mix(in srgb, var(--primary-text-color) 8%, transparent);
        }
        .field-row b {
          color: var(--primary-text-color);
        }
        @media (max-width: 900px) {
          .controls,
          .summary,
          .record-grid,
          .field-list {
            grid-template-columns: 1fr;
          }
          .header {
            grid-template-columns: auto 1fr;
          }
          .status {
            grid-column: 1 / -1;
            justify-self: stretch;
            justify-content: center;
          }
          button {
            width: 100%;
          }
        }
      </style>
      <ha-card>
        <div class="wrap">
          <div class="header">
            <div class="icon" aria-hidden="true">
              <svg viewBox="0 0 64 64" fill="none">
                <path d="M12 50h40" stroke="currentColor" stroke-width="5" stroke-linecap="round"/>
                <path d="M16 46V14" stroke="currentColor" stroke-width="5" stroke-linecap="round"/>
                <path d="M22 39l9-11 8 7 11-18" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M48 12h7v7" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </div>
            <div>
              <h2>${this._escape(this._name)}</h2>
              <div class="subtitle">Manual alarm lookup from the official SolaX Developer API. Dashboard loading does not call SolaX.</div>
            </div>
            <div class="status ${statusClass}">${statusLabel}</div>
          </div>

          <div class="controls">
            <label>
              Plant
              <select id="plant">
                ${plantOptions}
              </select>
            </label>
            <label>
              Device
              <select id="device">
                ${deviceOptions}
              </select>
            </label>
            <label>
              Alarm State
              <select id="alarm-state">
                <option value="all"${this._alarmState === "all" ? " selected" : ""}>All</option>
                <option value="ongoing"${this._alarmState === "ongoing" ? " selected" : ""}>Ongoing</option>
                <option value="closed"${this._alarmState === "closed" ? " selected" : ""}>Closed</option>
              </select>
            </label>
            <button id="fetch" ${this._fetching || !this._targetsLoaded || !this._plants.length ? "disabled" : ""}>
              ${this._fetching ? "Fetching..." : "Fetch Alarms"}
            </button>
          </div>

          <div class="summary">
            <div class="tile">
              <div class="label">Target</div>
              <div class="value">${this._escape(this._targetLabel())}</div>
              <div class="hint">${this._plants.length} plant(s), ${this._devices.length} device(s)</div>
            </div>
            <div class="tile">
              <div class="label">Alarm Rows</div>
              <div class="value">${this._records.length}</div>
              <div class="hint">${Number(this._lastMeta?.api_calls_made || 0)} API call(s)</div>
            </div>
            <div class="tile">
              <div class="label">Ongoing / Closed</div>
              <div class="value">${this._summaryValue("ongoing")} / ${this._summaryValue("closed")}</div>
              <div class="hint">Based on returned alarmState</div>
            </div>
            <div class="tile">
              <div class="label">Last Fetch</div>
              <div class="value">${this._escape(this._lastFetchLabel())}</div>
              <div class="hint">Manual fetch only</div>
            </div>
          </div>

          ${this._lastError ? `<div class="error-box">${this._escape(this._lastError)}</div>` : ""}
          ${this._renderRecords()}
        </div>
      </ha-card>
    `;
    this._bindEvents();
  }

  _renderRecords() {
    if (!this._lastFetchAt && !this._records.length) {
      return `<div class="empty">Fetch alarms to show returned alarm records.</div>`;
    }
    if (!this._records.length) {
      return `<div class="empty">No alarm records returned for this filter.</div>`;
    }
    return `
      <div class="records">
        ${this._records.map((record) => this._renderRecord(record)).join("")}
      </div>
    `;
  }

  _renderRecord(record) {
    const fields = Object.entries(record)
      .filter(([, value]) => value !== undefined && value !== null && value !== "")
      .map(
        ([key, value]) => `
          <div class="field-row">
            <b>${this._escape(key)}</b>
            <span>${this._escape(value)}</span>
          </div>
        `
      )
      .join("");
    const stateClass = this._stateClass(record.alarmState);
    return `
      <article class="record">
        <div class="record-head">
          <div class="record-title">${this._escape(record.alarmName || "Unnamed alarm")}</div>
          <div class="pill ${stateClass}">${this._escape(this._stateLabel(record.alarmState))}</div>
        </div>
        <div class="record-grid">
          <div class="kv"><span>Started</span><strong>${this._escape(this._formatDate(record.alarmStartTime))}</strong></div>
          <div class="kv"><span>Recovered</span><strong>${this._escape(this._formatDate(record.alarmEndTime))}</strong></div>
          <div class="kv"><span>Device</span><strong>${this._escape(this._shortSerial(record.deviceSn))}</strong></div>
          <div class="kv"><span>Code / Level</span><strong>${this._escape(record.errorCode ?? "Unknown")} / ${this._escape(record.alarmLevel ?? "Unknown")}</strong></div>
          <div class="kv"><span>Type</span><strong>${this._escape(record.alarmType || "Unknown")}</strong></div>
          <div class="kv"><span>Device Type</span><strong>${this._escape(this._mappedValue(record.deviceType, record.deviceTypeName))}</strong></div>
          <div class="kv"><span>Device Model</span><strong>${this._escape(this._mappedValue(record.deviceModel, record.deviceModelName))}</strong></div>
          <div class="kv"><span>Plant</span><strong>${this._escape(record.plantId || "Unknown")}</strong></div>
        </div>
        <details>
          <summary>Show all returned fields</summary>
          <div class="field-list">${fields}</div>
        </details>
      </article>
    `;
  }

  _bindEvents() {
    const root = this.shadowRoot;
    root.getElementById("plant")?.addEventListener("change", (event) => {
      this._selectedPlantKey = event.target.value;
      this._selectedDeviceKey = "";
      this._render();
    });
    root.getElementById("device")?.addEventListener("change", (event) => {
      this._selectedDeviceKey = event.target.value;
      this._render();
    });
    root.getElementById("alarm-state")?.addEventListener("change", (event) => {
      this._alarmState = event.target.value;
      this._render();
    });
    root.getElementById("fetch")?.addEventListener("click", () => {
      void this._fetchAlarms();
    });
  }
}

if (!customElements.get("solax-alarm-viewer")) {
  customElements.define("solax-alarm-viewer", SolaxAlarmViewerCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "solax-alarm-viewer")) {
  window.customCards.push({
    type: "solax-alarm-viewer",
    name: "SolaX Alarm Viewer",
    description: "Manual SolaX Developer API alarm viewer.",
  });
}
