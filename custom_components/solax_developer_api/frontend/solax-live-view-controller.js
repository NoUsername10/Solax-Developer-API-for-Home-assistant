class SolaxLiveViewControllerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._connected = false;
    this._heartbeatHandle = undefined;
    this._tickerHandle = undefined;
    this._entryId = undefined;
    this._entityId = undefined;
    this._name = "SolaX Live View";
    this._minimal = false;
    this._durationSeconds = 120;
    this._intervalSeconds = undefined;
    this._heartbeatSeconds = 45;
    this._lastHeartbeatAt = undefined;
    this._lastServiceResult = undefined;
    this._lastError = undefined;
    this._localLiveViewUntil = undefined;
  }

  setConfig(config) {
    const cfg = config || {};
    this._entryId = this._cleanString(cfg.entry_id);
    this._entityId = this._cleanString(cfg.entity || cfg.live_view_entity);
    this._name = this._cleanString(cfg.name) || "SolaX Live View";
    this._minimal =
      this._toBool(cfg.minimal, false) ||
      ["minimal", "compact"].includes(
        String(cfg.mode || cfg.display_mode || cfg.view || "").trim().toLowerCase()
      );
    this._durationSeconds = this._toInt(cfg.duration_seconds, 120, 30, 3600);
    this._intervalSeconds =
      cfg.interval_seconds === undefined ? undefined : this._toInt(cfg.interval_seconds, 5, 2, 60);
    const defaultHeartbeat = Math.max(20, Math.floor(this._durationSeconds / 2));
    this._heartbeatSeconds = this._toInt(
      cfg.heartbeat_seconds,
      defaultHeartbeat,
      15,
      Math.max(20, this._durationSeconds - 5)
    );
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._connected && !this._heartbeatHandle) {
      this._startHeartbeat();
    }
    if (this._connected && !this._tickerHandle) {
      this._startTicker();
    }
    this._render();
  }

  connectedCallback() {
    this._connected = true;
    this._startHeartbeat();
    this._startTicker();
    this._render();
  }

  disconnectedCallback() {
    this._connected = false;
    this._stopHeartbeat();
    this._stopTicker();
  }

  getCardSize() {
    return this._minimal ? 1 : 3;
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

  _toBool(raw, fallback = false) {
    if (typeof raw === "boolean") {
      return raw;
    }
    if (typeof raw === "string") {
      const normalized = raw.trim().toLowerCase();
      if (["true", "yes", "on", "1"].includes(normalized)) {
        return true;
      }
      if (["false", "no", "off", "0"].includes(normalized)) {
        return false;
      }
    }
    return fallback;
  }

  _servicePayload() {
    const payload = {
      duration_seconds: this._durationSeconds,
    };
    if (this._entryId) {
      payload.entry_id = this._entryId;
    }
    if (this._intervalSeconds !== undefined) {
      payload.interval_seconds = this._intervalSeconds;
    }
    return payload;
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

    return await this._hass.callService(
      "solax_developer_api",
      service,
      payload,
      undefined,
      true,
      true
    );
  }

  _detectedLiveViewEntity() {
    if (!this._hass) {
      return undefined;
    }
    if (this._entityId && this._hass.states[this._entityId]) {
      return this._entityId;
    }
    const entities = Object.keys(this._hass.states).filter(
      (entityId) =>
        entityId.startsWith("switch.") &&
        entityId.endsWith("_live_view_mode") &&
        this._hass.states[entityId]?.attributes
    );
    return entities.length > 0 ? entities[0] : undefined;
  }

  _liveViewEntityState() {
    const entityId = this._detectedLiveViewEntity();
    if (!entityId || !this._hass) {
      return { entityId: undefined, state: undefined, attributes: {} };
    }
    const state = this._hass.states[entityId];
    return {
      entityId,
      state: state?.state,
      attributes: state?.attributes || {},
    };
  }

  _secondsUntil(isoDate) {
    if (!isoDate) {
      return undefined;
    }
    const timestamp = Date.parse(isoDate);
    if (!Number.isFinite(timestamp)) {
      return undefined;
    }
    return Math.max(0, Math.ceil((timestamp - Date.now()) / 1000));
  }

  _numberOrUndefined(raw) {
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : undefined;
  }

  _boolOrUndefined(raw) {
    if (typeof raw === "boolean") {
      return raw;
    }
    if (typeof raw === "string") {
      const normalized = raw.trim().toLowerCase();
      if (["true", "on", "active", "yes"].includes(normalized)) {
        return true;
      }
      if (["false", "off", "inactive", "no"].includes(normalized)) {
        return false;
      }
    }
    return undefined;
  }

  _localRemainingSeconds() {
    if (!this._localLiveViewUntil) {
      return undefined;
    }
    return Math.max(0, Math.ceil((this._localLiveViewUntil - Date.now()) / 1000));
  }

  _normalizeServiceResponse(response) {
    if (!response || typeof response !== "object") {
      return response;
    }
    if (response.response && typeof response.response === "object") {
      return response.response;
    }
    if (response.service_response && typeof response.service_response === "object") {
      return response.service_response;
    }
    if (
      response.context &&
      response.response === undefined &&
      response.service_response === undefined
    ) {
      return undefined;
    }
    return response;
  }

  _buildDisplayState() {
    const entity = this._liveViewEntityState();
    const attrs = entity.attributes || {};
    const result = this._lastServiceResult || {};
    const remaining =
      this._numberOrUndefined(attrs.live_view_remaining_seconds) ??
      this._secondsUntil(attrs.live_view_until) ??
      this._secondsUntil(result.live_view_until) ??
      this._localRemainingSeconds() ??
      0;
    const entityActive = entity.state === "on";
    const resultActive = this._boolOrUndefined(result.live_view_active);
    const active = entityActive || resultActive === true || remaining > 0;
    const effectiveInterval =
      this._numberOrUndefined(attrs.effective_scan_interval) ??
      this._numberOrUndefined(result.effective_scan_interval);
    const targetInterval =
      this._numberOrUndefined(attrs.live_view_target_interval) ??
      this._numberOrUndefined(result.live_view_target_interval) ??
      this._intervalSeconds ??
      5;
    const pollProfile = attrs.poll_profile || result.poll_profile || (active ? "live_view" : "standard");
    const budgetAdjusted =
      this._boolOrUndefined(attrs.live_view_budget_adjusted) ??
      this._boolOrUndefined(result.live_view_budget_adjusted) ??
      false;
    const callBudget =
      this._numberOrUndefined(attrs.live_view_call_budget_per_minute) ??
      this._numberOrUndefined(result.live_view_call_budget_per_minute) ??
      20;
    const estimatedCalls =
      this._numberOrUndefined(attrs.live_view_estimated_calls_per_cycle) ??
      this._numberOrUndefined(result.live_view_estimated_calls_per_cycle);
    const refreshOk =
      this._boolOrUndefined(result.refresh_attempt_success) ??
      (this._lastHeartbeatAt ? true : undefined);

    return {
      active,
      remaining,
      effectiveInterval,
      targetInterval,
      pollProfile,
      budgetAdjusted,
      callBudget,
      estimatedCalls,
      refreshOk,
      entityId: entity.entityId,
    };
  }

  async _startLiveView() {
    if (!this._hass || !this._connected) {
      return;
    }
    this._lastError = undefined;
    const payload = this._servicePayload();
    try {
      const response = await this._callService("start_live_view", payload);
      const normalizedResponse = this._normalizeServiceResponse(response);
      this._lastHeartbeatAt = new Date();
      this._localLiveViewUntil = Date.now() + this._durationSeconds * 1000;
      this._lastServiceResult =
        normalizedResponse && typeof normalizedResponse === "object"
          ? normalizedResponse
          : {
              ok: true,
              live_view_active: true,
              live_view_until: new Date(this._localLiveViewUntil).toISOString(),
              live_view_target_interval: this._intervalSeconds ?? 5,
              live_view_call_budget_per_minute: 20,
              refresh_attempt_success: true,
            };
    } catch (err) {
      this._lastError = err?.message || String(err);
    }
    this._render();
  }

  _startHeartbeat() {
    if (this._heartbeatHandle) {
      return;
    }
    void this._startLiveView();
    this._heartbeatHandle = window.setInterval(() => {
      void this._startLiveView();
    }, this._heartbeatSeconds * 1000);
  }

  _stopHeartbeat() {
    if (!this._heartbeatHandle) {
      return;
    }
    window.clearInterval(this._heartbeatHandle);
    this._heartbeatHandle = undefined;
  }

  _startTicker() {
    if (this._tickerHandle) {
      return;
    }
    this._tickerHandle = window.setInterval(() => {
      this._render();
    }, 1000);
  }

  _stopTicker() {
    if (!this._tickerHandle) {
      return;
    }
    window.clearInterval(this._tickerHandle);
    this._tickerHandle = undefined;
  }

  _formatSeconds(seconds) {
    const value = Math.max(0, Math.floor(Number(seconds) || 0));
    if (value >= 3600) {
      const hours = Math.floor(value / 3600);
      const minutes = Math.floor((value % 3600) / 60);
      return `${hours}h ${minutes}m`;
    }
    if (value >= 60) {
      const minutes = Math.floor(value / 60);
      const remainder = value % 60;
      return `${minutes}m ${remainder}s`;
    }
    return `${value}s`;
  }

  _formatValue(value, suffix = "") {
    if (value === undefined || value === null || value === "") {
      return "Unknown";
    }
    return `${value}${suffix}`;
  }

  _formatHeartbeatAge() {
    if (!this._lastHeartbeatAt) {
      return "Waiting";
    }
    const seconds = Math.max(0, Math.floor((Date.now() - this._lastHeartbeatAt.getTime()) / 1000));
    return `${this._formatSeconds(seconds)} ago`;
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  _renderMetric(label, value, helper = "") {
    return `
      <div class="metric">
        <div class="metric-label">${this._escape(label)}</div>
        <div class="metric-value">${this._escape(value)}</div>
        ${helper ? `<div class="metric-helper">${this._escape(helper)}</div>` : ""}
      </div>
    `;
  }

  _renderMinimal(state, statusText, statusClass) {
    const detail = this._lastError
      ? this._lastError
      : state.budgetAdjusted
        ? "API budget protected"
        : `Heartbeat ${this._formatHeartbeatAge()}`;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }

        ha-card {
          overflow: hidden;
          border-radius: var(--ha-card-border-radius, 18px);
          color: var(--primary-text-color);
          background:
            radial-gradient(circle at 8% 10%, rgba(255, 186, 0, 0.22), transparent 38%),
            radial-gradient(circle at 92% 18%, rgba(21, 101, 192, 0.16), transparent 34%),
            linear-gradient(135deg, var(--ha-card-background, var(--card-background-color)) 0%, var(--secondary-background-color) 100%);
          border: 1px solid var(--divider-color);
          box-shadow: var(--ha-card-box-shadow, 0 8px 24px rgba(0, 0, 0, 0.14));
        }

        .minimal-card {
          align-items: center;
          display: grid;
          gap: 12px;
          grid-template-columns: auto minmax(0, 1fr) auto;
          padding: 13px 16px;
        }

        .icon-wrap {
          align-items: center;
          background: rgba(255, 186, 0, 0.18);
          border: 1px solid rgba(255, 186, 0, 0.42);
          border-radius: 14px;
          color: #ffb300;
          display: flex;
          height: 42px;
          justify-content: center;
          width: 42px;
        }

        ha-icon {
          --mdc-icon-size: 24px;
        }

        .content {
          min-width: 0;
        }

        .title-row {
          align-items: baseline;
          display: flex;
          gap: 10px;
          min-width: 0;
        }

        .title {
          font-size: 1rem;
          font-weight: 760;
          letter-spacing: -0.01em;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .remaining {
          color: var(--primary-text-color);
          flex: 0 0 auto;
          font-size: 1rem;
          font-weight: 850;
          letter-spacing: -0.03em;
        }

        .detail {
          color: var(--secondary-text-color);
          font-size: 0.74rem;
          line-height: 1.2;
          margin-top: 3px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .status {
          align-items: center;
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 999px;
          display: inline-flex;
          font-size: 0.72rem;
          font-weight: 800;
          gap: 7px;
          justify-self: end;
          padding: 7px 10px;
          text-transform: uppercase;
        }

        .dot {
          border-radius: 999px;
          height: 8px;
          width: 8px;
        }

        .status.active .dot {
          animation: pulse 1.8s ease-in-out infinite;
          background: var(--success-color, #43a047);
          box-shadow: 0 0 0 5px rgba(67, 160, 71, 0.14);
        }

        .status.starting .dot {
          background: var(--warning-color, #ffb300);
        }

        .status.error .dot {
          background: var(--error-color, #db4437);
        }

        .status.error {
          color: var(--error-color, #db4437);
        }

        @keyframes pulse {
          0%, 100% {
            transform: scale(1);
          }
          50% {
            transform: scale(1.35);
          }
        }

        @media (max-width: 360px) {
          .minimal-card {
            grid-template-columns: auto minmax(0, 1fr);
          }

          .status {
            grid-column: 1 / -1;
            justify-self: stretch;
            justify-content: center;
          }
        }
      </style>
      <ha-card>
        <div class="minimal-card">
          <div class="icon-wrap"><ha-icon icon="mdi:clock-fast"></ha-icon></div>
          <div class="content">
            <div class="title-row">
              <div class="title">${this._escape(this._name)}</div>
              <div class="remaining">${this._escape(this._formatSeconds(state.remaining))}</div>
            </div>
            <div class="detail">${this._escape(detail)}</div>
          </div>
          <div class="status ${statusClass}">
            <span class="dot"></span>
            <span>${this._escape(statusText)}</span>
          </div>
        </div>
      </ha-card>
    `;
  }

  _render() {
    if (!this.shadowRoot) {
      return;
    }
    const state = this._buildDisplayState();
    const statusText = this._lastError ? "Error" : state.active ? "Active" : "Starting";
    const statusClass = this._lastError ? "error" : state.active ? "active" : "starting";
    const budgetText = state.budgetAdjusted ? "Protected" : "Normal";
    const refreshText =
      state.refreshOk === undefined ? "Pending" : state.refreshOk ? "Fresh" : "Live, refresh warning";
    const entityText = state.entityId || "Auto-detecting";

    if (this._minimal) {
      this._renderMinimal(state, statusText, statusClass);
      return;
    }

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }

        ha-card {
          overflow: hidden;
          border-radius: var(--ha-card-border-radius, 18px);
          color: var(--primary-text-color);
          background:
            radial-gradient(circle at 16% 10%, rgba(255, 186, 0, 0.25), transparent 30%),
            radial-gradient(circle at 88% 18%, rgba(21, 101, 192, 0.18), transparent 32%),
            linear-gradient(135deg, var(--ha-card-background, var(--card-background-color)) 0%, var(--secondary-background-color) 100%);
          border: 1px solid var(--divider-color);
          box-shadow: var(--ha-card-box-shadow, 0 8px 28px rgba(0, 0, 0, 0.16));
        }

        .card {
          position: relative;
          padding: 20px;
        }

        .header {
          align-items: flex-start;
          display: flex;
          gap: 14px;
          justify-content: space-between;
        }

        .brand {
          align-items: center;
          display: flex;
          gap: 12px;
          min-width: 0;
        }

        .icon-wrap {
          align-items: center;
          background: rgba(255, 186, 0, 0.18);
          border: 1px solid rgba(255, 186, 0, 0.4);
          border-radius: 16px;
          color: #ffb300;
          display: flex;
          height: 46px;
          justify-content: center;
          width: 46px;
        }

        ha-icon {
          --mdc-icon-size: 26px;
        }

        .title {
          font-size: 1.15rem;
          font-weight: 700;
          letter-spacing: -0.01em;
          line-height: 1.2;
          margin: 0;
        }

        .subtitle {
          color: var(--secondary-text-color);
          font-size: 0.82rem;
          line-height: 1.35;
          margin-top: 4px;
        }

        .status {
          align-items: center;
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 999px;
          display: inline-flex;
          flex: 0 0 auto;
          font-size: 0.78rem;
          font-weight: 700;
          gap: 8px;
          padding: 7px 10px;
          text-transform: uppercase;
        }

        .dot {
          border-radius: 999px;
          height: 9px;
          width: 9px;
        }

        .status.active .dot {
          animation: pulse 1.8s ease-in-out infinite;
          background: var(--success-color, #43a047);
          box-shadow: 0 0 0 5px rgba(67, 160, 71, 0.14);
        }

        .status.starting .dot {
          background: var(--warning-color, #ffb300);
        }

        .status.error .dot {
          background: var(--error-color, #db4437);
        }

        .hero {
          align-items: end;
          display: grid;
          gap: 14px;
          grid-template-columns: 1fr auto;
          margin: 18px 0 16px;
        }

        .remaining-label {
          color: var(--secondary-text-color);
          font-size: 0.78rem;
          font-weight: 700;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }

        .remaining-value {
          font-size: 2.25rem;
          font-weight: 800;
          letter-spacing: -0.05em;
          line-height: 1;
          margin-top: 4px;
        }

        .profile {
          background: rgba(21, 101, 192, 0.12);
          border: 1px solid rgba(21, 101, 192, 0.22);
          border-radius: 14px;
          color: var(--primary-text-color);
          font-size: 0.82rem;
          font-weight: 700;
          padding: 10px 12px;
          text-align: right;
        }

        .grid {
          display: grid;
          gap: 10px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .metric {
          background: rgba(127, 127, 127, 0.08);
          border: 1px solid var(--divider-color);
          border-radius: 14px;
          min-width: 0;
          padding: 12px;
        }

        .metric-label {
          color: var(--secondary-text-color);
          font-size: 0.76rem;
          font-weight: 700;
          line-height: 1.2;
        }

        .metric-value {
          font-size: 1rem;
          font-weight: 750;
          line-height: 1.3;
          margin-top: 5px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .metric-helper {
          color: var(--secondary-text-color);
          font-size: 0.74rem;
          line-height: 1.25;
          margin-top: 5px;
        }

        .footer {
          border-top: 1px solid var(--divider-color);
          color: var(--secondary-text-color);
          font-size: 0.78rem;
          line-height: 1.35;
          margin-top: 14px;
          padding-top: 12px;
        }

        .error-text {
          color: var(--error-color, #db4437);
          font-weight: 700;
        }

        @keyframes pulse {
          0%, 100% {
            transform: scale(1);
          }
          50% {
            transform: scale(1.35);
          }
        }

        @media (max-width: 520px) {
          .header,
          .hero {
            grid-template-columns: 1fr;
          }

          .header {
            align-items: stretch;
            flex-direction: column;
          }

          .status {
            justify-content: center;
          }

          .profile {
            text-align: left;
          }

          .grid {
            grid-template-columns: 1fr;
          }
        }
      </style>
      <ha-card>
        <div class="card">
          <div class="header">
            <div class="brand">
              <div class="icon-wrap"><ha-icon icon="mdi:solar-power"></ha-icon></div>
              <div>
                <h2 class="title">${this._escape(this._name)}</h2>
                <div class="subtitle">Keeps Developer API Live View active while this dashboard is open.</div>
              </div>
            </div>
            <div class="status ${statusClass}">
              <span class="dot"></span>
              <span>${this._escape(statusText)}</span>
            </div>
          </div>

          <div class="hero">
            <div>
              <div class="remaining-label">Live View Remaining</div>
              <div class="remaining-value">${this._escape(this._formatSeconds(state.remaining))}</div>
            </div>
            <div class="profile">${this._escape(String(state.pollProfile).replaceAll("_", " "))}</div>
          </div>

          <div class="grid">
            ${this._renderMetric("Target Interval", this._formatValue(state.targetInterval, "s"), "Requested card/service target")}
            ${this._renderMetric("Effective Interval", this._formatValue(state.effectiveInterval, "s"), "May be increased for API safety")}
            ${this._renderMetric("API Budget", budgetText, state.callBudget ? `${state.callBudget} calls/min configured` : "Budget metadata pending")}
            ${this._renderMetric("Estimated Calls", this._formatValue(state.estimatedCalls), "Per Live View refresh cycle")}
            ${this._renderMetric("Last Heartbeat", this._formatHeartbeatAge(), `Every ${this._heartbeatSeconds}s`)}
            ${this._renderMetric("Refresh Status", refreshText, this._lastError ? this._lastError : "Latest service heartbeat")}
          </div>

          <div class="footer">
            Entity: <strong>${this._escape(entityText)}</strong>
            ${this._lastError ? `<br><span class="error-text">${this._escape(this._lastError)}</span>` : ""}
          </div>
        </div>
      </ha-card>
    `;
  }
}

if (!customElements.get("solax-live-view-controller")) {
  customElements.define("solax-live-view-controller", SolaxLiveViewControllerCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "solax-live-view-controller")) {
  window.customCards.push({
    type: "solax-live-view-controller",
    name: "SolaX Live View Controller",
    description: "Keeps SolaX Developer API Live View active while a dashboard is open.",
    preview: true,
  });
}
