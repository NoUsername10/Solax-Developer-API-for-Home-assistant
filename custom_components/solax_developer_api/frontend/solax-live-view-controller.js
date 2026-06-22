class SolaxLiveViewControllerCard extends HTMLElement {
  constructor() {
    super();
    this._hass = undefined;
    this._connected = false;
    this._heartbeatHandle = undefined;
    this._entryId = undefined;
    this._durationSeconds = 120;
    this._intervalSeconds = undefined;
    this._heartbeatSeconds = 45;
  }

  setConfig(config) {
    const cfg = config || {};
    this._entryId = typeof cfg.entry_id === "string" && cfg.entry_id.trim() ? cfg.entry_id.trim() : undefined;
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
  }

  set hass(hass) {
    this._hass = hass;
    if (this._connected && !this._heartbeatHandle) {
      this._startHeartbeat();
    }
  }

  connectedCallback() {
    this._connected = true;
    this.style.display = "none";
    this.style.height = "0";
    this.style.margin = "0";
    this.style.padding = "0";
    this._startHeartbeat();
  }

  disconnectedCallback() {
    this._connected = false;
    this._stopHeartbeat();
  }

  getCardSize() {
    return 1;
  }

  _toInt(raw, fallback, min, max) {
    const parsed = Number.parseInt(raw, 10);
    if (!Number.isFinite(parsed)) {
      return fallback;
    }
    return Math.max(min, Math.min(max, parsed));
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

  async _startLiveView() {
    if (!this._hass || !this._connected) {
      return;
    }
    try {
      await this._hass.callService("solax_developer_api", "start_live_view", this._servicePayload());
    } catch (_err) {
      // Silent by design: this controller should never break dashboard rendering.
    }
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
}

customElements.define("solax-live-view-controller", SolaxLiveViewControllerCard);
