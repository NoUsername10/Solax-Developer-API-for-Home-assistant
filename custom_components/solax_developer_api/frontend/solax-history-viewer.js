class SolaxHistoryViewerCard extends HTMLElement {
  static MODE_DEVICE_HISTORY = "device_history";
  static MODE_PLANT_STATISTICS = "plant_statistics";
  static PLANT_VIEW_YEAR = "year";
  static PLANT_VIEW_MONTH = "month";
  static CHART_SCALE_ZERO = "zero";
  static CHART_SCALE_AUTO = "auto";
  static RANGE_PRESETS = [
    { hours: 1, label: "Last 1h", interval: 5 },
    { hours: 3, label: "Last 3h", interval: 5 },
    { hours: 6, label: "Last 6h", interval: 5 },
    { hours: 12, label: "Last 12h", interval: 5 },
    { hours: 24, label: "Day", interval: 15 },
    { hours: 48, label: "2 days", interval: 30 },
    { hours: 72, label: "3 days", interval: 30 },
    { hours: 168, label: "Week", interval: 60 },
  ];
  static DEVICE_TYPE_NAMES = {
    1: "Inverter",
    2: "Battery",
    3: "Meter",
    4: "EV Charger",
  };

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._connected = false;
    this._entryId = undefined;
    this._name = "SolaX History";
    this._mode = SolaxHistoryViewerCard.MODE_DEVICE_HISTORY;
    this._plantView = SolaxHistoryViewerCard.PLANT_VIEW_YEAR;
    this._defaultRangeHours = 6;
    this._maxSelectedFields = 6;
    this._rangeHours = 6;
    this._selectedYear = new Date().getFullYear();
    this._selectedMonth = new Date().getMonth() + 1;
    this._devices = [];
    this._plants = [];
    this._devicesLoaded = false;
    this._plantsLoaded = false;
    this._loadingDevices = false;
    this._loadingPlants = false;
    this._selectedDeviceType = 1;
    this._selectedDeviceKeys = new Set();
    this._selectedPlantKey = undefined;
    this._showDeviceBreakdown = true;
    this._chartScaleMode = SolaxHistoryViewerCard.CHART_SCALE_ZERO;
    this._customHistoryRange = undefined;
    this._metadataRetryTimer = undefined;
    this._fetching = false;
    this._lastError = undefined;
    this._lastFetchAt = undefined;
    this._rows = [];
    this._fields = [];
    this._selectedFields = new Set();
    this._lastResultMeta = {};
    this._shellRendered = false;
    this._eventsBound = false;
    this._chartModel = undefined;
  }

  setConfig(config) {
    const cfg = config || {};
    const nextEntryId = this._cleanString(cfg.entry_id);
    if (nextEntryId !== this._entryId) {
      this._devicesLoaded = false;
      this._plantsLoaded = false;
      this._selectedDeviceKeys = new Set();
      this._selectedPlantKey = undefined;
      this._clearMetadataRetry();
    }
    this._entryId = nextEntryId;
    this._name = this._cleanString(cfg.name) || "SolaX History";
    this._defaultRangeHours = this._rangePresetForHours(
      this._toInt(cfg.default_range_hours, 6, 1, 168)
    ).hours;
    this._maxSelectedFields = this._toInt(cfg.max_selected_fields, 6, 1, 12);
    this._chartScaleMode = this._normalizeChartScaleMode(cfg.default_scale_mode);
    this._rangeHours = this._defaultRangeHours;
    this._selectedYear = this._currentYear();
    this._selectedMonth = new Date().getMonth() + 1;
    this._render();
  }

  set hass(hass) {
    const hadHass = Boolean(this._hass);
    this._hass = hass;
    if (this._connected && !hadHass) {
      this._loadMetadata();
      this._render();
    }
  }

  connectedCallback() {
    this._connected = true;
    this._loadMetadata();
    this._render();
  }

  disconnectedCallback() {
    this._connected = false;
    this._clearMetadataRetry();
  }

  getCardSize() {
    return 8;
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

  _normalizeChartScaleMode(raw) {
    return raw === SolaxHistoryViewerCard.CHART_SCALE_AUTO
      ? SolaxHistoryViewerCard.CHART_SCALE_AUTO
      : SolaxHistoryViewerCard.CHART_SCALE_ZERO;
  }

  _toInt(raw, fallback, min, max) {
    const parsed = Number.parseInt(raw, 10);
    if (!Number.isFinite(parsed)) {
      return fallback;
    }
    return Math.max(min, Math.min(max, parsed));
  }

  _currentYear() {
    return new Date().getFullYear();
  }

  _rangePresetForHours(hours) {
    const parsed = Number(hours);
    return (
      SolaxHistoryViewerCard.RANGE_PRESETS.find((preset) => preset.hours === parsed) ||
      SolaxHistoryViewerCard.RANGE_PRESETS.reduce((closest, preset) =>
        Math.abs(preset.hours - parsed) < Math.abs(closest.hours - parsed) ? preset : closest
      )
    );
  }

  _rangePreset() {
    return this._rangePresetForHours(this._rangeHours);
  }

  _recommendedInterval(hours) {
    return this._rangePresetForHours(hours).interval;
  }

  _selectedDevices() {
    return this._devices.filter(
      (device) =>
        Number(device.device_type) === Number(this._selectedDeviceType) &&
        this._selectedDeviceKeys.has(this._deviceKey(device))
    );
  }

  _familyDevices() {
    return this._devices.filter(
      (device) => Number(device.device_type) === Number(this._selectedDeviceType)
    );
  }

  _selectedPlant() {
    return this._plants.find((plant) => this._plantKey(plant) === this._selectedPlantKey);
  }

  _estimatedRequestCount() {
    const hours = this._customHistoryRange
      ? Math.max(1, (this._customHistoryRange.end - this._customHistoryRange.start) / 3600000)
      : this._rangeHours;
    const windows = Math.max(1, Math.ceil(hours / 11));
    const chunks = Math.max(1, Math.ceil(this._selectedDevices().length / 10));
    return windows * chunks;
  }

  _servicePayload(extra = {}) {
    return this._entryId ? { entry_id: this._entryId, ...extra } : extra;
  }

  _clearMetadataRetry() {
    if (this._metadataRetryTimer) {
      clearTimeout(this._metadataRetryTimer);
      this._metadataRetryTimer = undefined;
    }
  }

  _scheduleMetadataRetry() {
    if (!this._connected || this._metadataRetryTimer) {
      return;
    }
    this._metadataRetryTimer = setTimeout(() => {
      this._metadataRetryTimer = undefined;
      this._loadMetadata();
    }, 5000);
  }

  _metadataUnavailableMessage(response) {
    const entries = Array.isArray(response?.entries) ? response.entries : [];
    if (entries.length > 0) {
      return undefined;
    }
    if (this._entryId) {
      return `No loaded SolaX Developer API integration matches entry_id "${this._entryId}". Remove entry_id from the card or use the exact config entry id.`;
    }
    return "No loaded SolaX Developer API integration is available yet. The card will retry automatically.";
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

  _loadMetadata() {
    if (!this._hass) {
      return;
    }
    if (!this._devicesLoaded && !this._loadingDevices) {
      void this._loadDevices();
    }
    if (!this._plantsLoaded && !this._loadingPlants) {
      void this._loadPlants();
    }
  }

  async _loadDevices() {
    this._loadingDevices = true;
    this._lastError = undefined;
    this._render();
    try {
      const response = await this._callService("list_history_devices", this._servicePayload());
      const unavailableMessage = this._metadataUnavailableMessage(response);
      if (unavailableMessage) {
        this._devicesLoaded = false;
        this._lastError = unavailableMessage;
        this._scheduleMetadataRetry();
        return;
      }
      this._devices = Array.isArray(response?.devices) ? response.devices : [];
      this._devicesLoaded = true;
      this._ensureDefaultDeviceSelection();
    } catch (err) {
      this._lastError = err?.message || String(err);
      this._devices = [];
    } finally {
      this._loadingDevices = false;
      this._render();
    }
  }

  async _loadPlants() {
    this._loadingPlants = true;
    this._lastError = undefined;
    this._render();
    try {
      const response = await this._callService(
        "list_plant_statistics_targets",
        this._servicePayload()
      );
      const unavailableMessage = this._metadataUnavailableMessage(response);
      if (unavailableMessage) {
        this._plantsLoaded = false;
        this._lastError = unavailableMessage;
        this._scheduleMetadataRetry();
        return;
      }
      this._plants = Array.isArray(response?.plants) ? response.plants : [];
      this._plantsLoaded = true;
      if (!this._selectedPlantKey && this._plants.length > 0) {
        this._selectedPlantKey = this._plantKey(this._plants[0]);
      }
    } catch (err) {
      this._lastError = err?.message || String(err);
      this._plants = [];
    } finally {
      this._loadingPlants = false;
      this._render();
    }
  }

  _ensureDefaultDeviceSelection() {
    const types = this._deviceTypes();
    if (!types.length) {
      this._selectedDeviceKeys = new Set();
      return;
    }
    if (!types.includes(Number(this._selectedDeviceType))) {
      this._selectedDeviceType = types.includes(1) ? 1 : types[0];
    }
    const family = this._familyDevices();
    const validKeys = new Set(family.map((device) => this._deviceKey(device)));
    const retained = new Set(
      Array.from(this._selectedDeviceKeys).filter((key) => validKeys.has(key))
    );
    if (retained.size > 0) {
      this._selectedDeviceKeys = retained;
      return;
    }
    this._selectedDeviceKeys = new Set(family.map((device) => this._deviceKey(device)));
  }

  _deviceTypes() {
    return Array.from(new Set(this._devices.map((device) => Number(device.device_type))))
      .filter((type) => [1, 2, 3, 4].includes(type))
      .sort((a, b) => a - b);
  }

  _deviceKey(device) {
    return [
      device.entry_id || this._entryId || "",
      device.device_sn,
      device.device_type,
      device.business_type,
    ].join("|");
  }

  _plantKey(plant) {
    return [
      plant.entry_id || this._entryId || "",
      plant.plant_id,
      plant.business_type,
    ].join("|");
  }

  _clearSeries() {
    this._rows = [];
    this._fields = [];
    this._selectedFields = new Set();
    this._lastResultMeta = {};
    this._lastFetchAt = undefined;
    this._chartModel = undefined;
  }

  async _fetchCurrentMode() {
    if (this._mode === SolaxHistoryViewerCard.MODE_PLANT_STATISTICS) {
      await this._fetchPlantStatistics();
      return;
    }
    await this._fetchHistory();
  }

  async _fetchHistory(options = {}) {
    if (!this._hass || this._fetching) {
      return;
    }
    const devices = this._selectedDevices();
    if (!devices.length) {
      this._lastError = "Select at least one history-capable device first.";
      this._render();
      return;
    }
    const groups = this._historyRequestGroups(devices);
    if (!groups.length) {
      this._lastError = "Selected devices cannot be queried together.";
      this._render();
      return;
    }

    this._fetching = true;
    this._lastError = undefined;
    this._render();
    const range = options.range || this._customHistoryRange || this._relativeHistoryRange();
    const interval = options.interval || this._recommendedInterval(this._rangeHours);
    const allRows = [];
    let requestCount = 0;

    try {
      for (const group of groups) {
        const payload = {
          sn_list: group.devices.map((device) => device.device_sn),
          device_type: group.deviceType,
          business_type: group.businessType,
          start_time: Math.floor(range.start),
          end_time: Math.floor(range.end),
          time_interval: interval,
        };
        if (group.entryId || this._entryId) {
          payload.entry_id = group.entryId || this._entryId;
        }
        const response = await this._callService("fetch_device_history", payload);
        requestCount += Number(response?.window_summary?.requestCount || 1);
        if (Array.isArray(response?.result)) {
          allRows.push(...response.result);
        }
      }
      this._lastResultMeta = {
        requestCount,
        helper: `${range.label || this._rangePreset().label} at ${interval} min`,
      };
      this._lastFetchAt = new Date();
      this._processHistoryRows(allRows, interval, range.start);
    } catch (err) {
      this._lastError = err?.message || String(err);
      this._rows = [];
      this._fields = [];
      this._selectedFields = new Set();
    } finally {
      this._fetching = false;
      this._render();
    }
  }

  _relativeHistoryRange() {
    const end = Date.now();
    const start = end - this._rangeHours * 60 * 60 * 1000;
    return { start, end, label: this._rangePreset().label };
  }

  _historyRequestGroups(devices) {
    const groups = new Map();
    for (const device of devices) {
      const key = [device.entry_id || this._entryId || "", device.device_type, device.business_type].join("|");
      if (!groups.has(key)) {
        groups.set(key, {
          entryId: device.entry_id || this._entryId,
          deviceType: Number(device.device_type),
          businessType: Number(device.business_type),
          devices: [],
        });
      }
      groups.get(key).devices.push(device);
    }
    return Array.from(groups.values());
  }

  async _fetchPlantStatistics() {
    if (!this._hass || this._fetching) {
      return;
    }
    const plant = this._selectedPlant();
    if (!plant) {
      this._lastError = "Select a plant first.";
      this._render();
      return;
    }

    this._fetching = true;
    this._lastError = undefined;
    this._render();
    const payload = {
      plant_id: plant.plant_id,
      business_type: Number(plant.business_type),
      year: Number(this._selectedYear),
    };
    if (plant.entry_id || this._entryId) {
      payload.entry_id = plant.entry_id || this._entryId;
    }

    try {
      const service =
        this._plantView === SolaxHistoryViewerCard.PLANT_VIEW_MONTH
          ? "fetch_plant_month_statistics"
          : "fetch_plant_year_statistics";
      if (this._plantView === SolaxHistoryViewerCard.PLANT_VIEW_MONTH) {
        payload.month = Number(this._selectedMonth);
      }
      const response = await this._callService(service, payload);
      const rows = Array.isArray(response?.rows) ? response.rows : [];
      this._lastResultMeta = {
        requestCount: response?.api_calls_made,
        helper:
          this._plantView === SolaxHistoryViewerCard.PLANT_VIEW_MONTH
            ? `${response?.date || this._yearMonthText()}, daily`
            : `${response?.year || this._selectedYear}, monthly`,
      };
      this._lastFetchAt = new Date();
      this._processPlantRows(rows);
    } catch (err) {
      this._lastError = err?.message || String(err);
      this._rows = [];
      this._fields = [];
      this._selectedFields = new Set();
    } finally {
      this._fetching = false;
      this._render();
    }
  }

  async _drillToMonth(timestamp) {
    const date = new Date(timestamp);
    this._selectedYear = date.getUTCFullYear();
    this._selectedMonth = date.getUTCMonth() + 1;
    this._plantView = SolaxHistoryViewerCard.PLANT_VIEW_MONTH;
    this._clearSeries();
    await this._fetchPlantStatistics();
  }

  async _drillToDay(timestamp) {
    const date = new Date(timestamp);
    const start = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
    const end = start + 24 * 60 * 60 * 1000 - 1;
    this._mode = SolaxHistoryViewerCard.MODE_DEVICE_HISTORY;
    this._rangeHours = 24;
    this._customHistoryRange = {
      start,
      end,
      label: date.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" }),
    };
    this._clearSeries();
    await this._fetchHistory({ range: this._customHistoryRange, interval: 15 });
  }

  _yearMonthText() {
    return `${this._selectedYear}-${String(this._selectedMonth).padStart(2, "0")}`;
  }

  _parseTimestamp(row) {
    const raw = row?.timestamp ?? row?.dataTime ?? row?.plantLocalTime ?? row?.time ?? row?.date;
    if (typeof raw === "number" && Number.isFinite(raw)) {
      return raw > 9999999999 ? raw : raw * 1000;
    }
    if (typeof raw !== "string" || !raw.trim()) {
      return undefined;
    }
    const text = raw.trim();
    const dateOnly = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (dateOnly) {
      const [, year, month, day] = dateOnly;
      return new Date(Number(year), Number(month) - 1, Number(day)).getTime();
    }
    const monthOnly = text.match(/^(\d{4})-(\d{2})$/);
    if (monthOnly) {
      const [, year, month] = monthOnly;
      return Date.UTC(Number(year), Number(month) - 1, 1);
    }
    const match = text.match(
      /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/
    );
    if (match) {
      const [, year, month, day, hour, minute, second = "0"] = match;
      return new Date(
        Number(year),
        Number(month) - 1,
        Number(day),
        Number(hour),
        Number(minute),
        Number(second)
      ).getTime();
    }
    const parsed = Date.parse(text);
    return Number.isFinite(parsed) ? parsed : undefined;
  }

  _flatten(row, prefix = "") {
    const result = {};
    if (!row || typeof row !== "object" || Array.isArray(row)) {
      return result;
    }
    for (const [key, value] of Object.entries(row)) {
      const path = prefix ? `${prefix}.${key}` : key;
      if (value && typeof value === "object" && !Array.isArray(value)) {
        Object.assign(result, this._flatten(value, path));
      } else {
        result[path] = value;
      }
    }
    return result;
  }

  _rowSerial(row) {
    return this._cleanString(row?.deviceSn || row?.deviceSN || row?.sn || row?.inverterSN || row?.serial);
  }

  _isExcludedField(field) {
    const normalized = field.toLowerCase().replaceAll(".", "").replaceAll("_", "");
    return [
      "devicesn",
      "devicesn",
      "sn",
      "invertersn",
      "serial",
      "registerno",
      "datatime",
      "plantlocaltime",
      "timestamp",
      "time",
      "date",
      "day",
      "month",
      "devicestatus",
      "onlinestatus",
      "status",
      "businesstype",
      "devicetype",
      "plantid",
    ].includes(normalized);
  }

  _toNumber(raw) {
    if (raw === null || raw === undefined || raw === "") {
      return undefined;
    }
    const value = Number(raw);
    return Number.isFinite(value) ? value : undefined;
  }

  _fieldPriority(field) {
    const normalized = field.toLowerCase().replaceAll(".", "");
    const preferred = [
      "pvgeneration",
      "inverteracoutputenergy",
      "loadconsumption",
      "exportenergy",
      "importenergy",
      "batterycharged",
      "batterydischarged",
      "earnings",
      "gridpower",
      "totalactivepower",
      "acpower",
      "acpower1",
      "dailyyield",
      "totalyield",
      "todayimportenergy",
      "todayexportenergy",
      "totalimportenergy",
      "totalexportenergy",
      "dailyacoutput",
      "totalacoutput",
      "mppttotalinputpower",
      "power",
      "voltage",
      "current",
      "temperature",
    ];
    const index = preferred.findIndex((token) => normalized.includes(token));
    return index === -1 ? 999 : index;
  }

  _historyBucketTimestamp(timestamp, intervalMinutes, rangeStart) {
    const intervalMs = Math.max(60000, Number(intervalMinutes || 5) * 60 * 1000);
    return Math.round(timestamp / intervalMs) * intervalMs;
  }

  _isCumulativeHistoryField(field) {
    const normalized = String(field).toLowerCase().replaceAll(".", "");
    return (
      normalized.includes("energy") ||
      normalized.includes("yield") ||
      normalized.includes("earnings") ||
      normalized.includes("total")
    );
  }

  _addHistoryAggregate(accumulator, field, value, timestamp) {
    const stat = accumulator[field] || {
      sum: 0,
      count: 0,
      lastTimestamp: Number.NEGATIVE_INFINITY,
      lastValue: undefined,
    };
    stat.sum += value;
    stat.count += 1;
    if (timestamp >= stat.lastTimestamp) {
      stat.lastTimestamp = timestamp;
      stat.lastValue = value;
    }
    accumulator[field] = stat;
  }

  _finalizeHistoryAggregates(bucket) {
    const deviceValues = {};
    for (const [serial, fields] of Object.entries(bucket.deviceAggregates || {})) {
      const values = {};
      for (const [field, stat] of Object.entries(fields || {})) {
        if (!stat || !stat.count) {
          continue;
        }
        values[field] = this._isCumulativeHistoryField(field)
          ? stat.lastValue
          : stat.sum / stat.count;
      }
      if (Object.keys(values).length) {
        deviceValues[serial] = values;
      }
    }
    return { timestamp: bucket.timestamp, deviceValues };
  }

  _processHistoryRows(rows, intervalMinutes, rangeStart) {
    const grouped = new Map();
    const selectedSerials = this._selectedDevices().map((device) => String(device.device_sn));

    for (const rawRow of rows) {
      if (!rawRow || typeof rawRow !== "object") {
        continue;
      }
      const timestamp = this._parseTimestamp(rawRow);
      if (!Number.isFinite(timestamp)) {
        continue;
      }
      const serial = this._rowSerial(rawRow) || (selectedSerials.length === 1 ? selectedSerials[0] : undefined);
      if (!serial) {
        continue;
      }
      const bucketTimestamp = this._historyBucketTimestamp(
        timestamp,
        intervalMinutes,
        rangeStart
      );
      const bucket =
        grouped.get(bucketTimestamp) || { timestamp: bucketTimestamp, deviceAggregates: {} };
      const flat = this._flatten(rawRow);
      const values = {};
      for (const [field, valueRaw] of Object.entries(flat)) {
        if (this._isExcludedField(field)) {
          continue;
        }
        const value = this._toNumber(valueRaw);
        if (value === undefined) {
          continue;
        }
        values[field] = value;
      }
      if (Object.keys(values).length) {
        bucket.deviceAggregates[serial] = bucket.deviceAggregates[serial] || {};
        for (const [field, value] of Object.entries(values)) {
          this._addHistoryAggregate(
            bucket.deviceAggregates[serial],
            field,
            value,
            timestamp
          );
        }
        grouped.set(bucketTimestamp, bucket);
      }
    }

    this._rows = Array.from(grouped.values())
      .map((bucket) => this._finalizeHistoryAggregates(bucket))
      .sort((a, b) => a.timestamp - b.timestamp);
    const fieldStats = this._historyFieldStats(this._rows);
    this._setFieldsFromStats(fieldStats);
  }

  _historyFieldStats(rows) {
    const fieldStats = new Map();
    for (const row of rows) {
      const fieldsInBucket = new Set();
      for (const values of Object.values(row.deviceValues || {})) {
        for (const [field, value] of Object.entries(values || {})) {
          if (Number.isFinite(value)) {
            fieldsInBucket.add(field);
          }
        }
      }
      for (const field of fieldsInBucket) {
        const stat = fieldStats.get(field) || { field, count: 0 };
        stat.count += 1;
        fieldStats.set(field, stat);
      }
    }
    return fieldStats;
  }

  _processPlantRows(rows) {
    const processed = [];
    const fieldStats = new Map();

    for (const rawRow of rows) {
      if (!rawRow || typeof rawRow !== "object") {
        continue;
      }
      const timestamp = this._parseTimestamp(rawRow);
      if (!Number.isFinite(timestamp)) {
        continue;
      }
      const flat = this._flatten(rawRow);
      const values = {};
      for (const [field, valueRaw] of Object.entries(flat)) {
        if (this._isExcludedField(field)) {
          continue;
        }
        const value = this._toNumber(valueRaw);
        if (value === undefined) {
          continue;
        }
        values[field] = value;
        const stat = fieldStats.get(field) || { field, count: 0 };
        stat.count += 1;
        fieldStats.set(field, stat);
      }
      processed.push({ timestamp, values, raw: rawRow });
    }

    this._rows = processed.sort((a, b) => a.timestamp - b.timestamp);
    this._setFieldsFromStats(fieldStats);
  }

  _setFieldsFromStats(fieldStats) {
    this._fields = Array.from(fieldStats.values())
      .filter((field) => field.count > 0)
      .sort((a, b) => {
        const priority = this._fieldPriority(a.field) - this._fieldPriority(b.field);
        if (priority !== 0) {
          return priority;
        }
        return a.field.localeCompare(b.field);
      });

    const retained = new Set(
      Array.from(this._selectedFields).filter((field) =>
        this._fields.some((item) => item.field === field)
      )
    );
    if (retained.size > 0) {
      this._selectedFields = retained;
      return;
    }

    this._selectedFields = new Set(
      this._fields.slice(0, this._maxSelectedFields).map((item) => item.field)
    );
  }

  _toggleField(field) {
    const selected = new Set(this._selectedFields);
    if (selected.has(field)) {
      selected.delete(field);
    } else if (selected.size < this._maxSelectedFields) {
      selected.add(field);
    } else {
      this._lastError = `Maximum ${this._maxSelectedFields} chart fields can be selected.`;
    }
    this._selectedFields = selected;
    this._render();
  }

  _toggleDevice(key) {
    const selected = new Set(this._selectedDeviceKeys);
    if (selected.has(key)) {
      selected.delete(key);
    } else {
      selected.add(key);
    }
    this._selectedDeviceKeys = selected;
    this._customHistoryRange = undefined;
    this._clearSeries();
    this._lastError = undefined;
    this._render();
  }

  _selectAllFamilyDevices() {
    this._selectedDeviceKeys = new Set(this._familyDevices().map((device) => this._deviceKey(device)));
    this._customHistoryRange = undefined;
    this._clearSeries();
    this._lastError = undefined;
    this._render();
  }

  _selectNoDevices() {
    this._selectedDeviceKeys = new Set();
    this._customHistoryRange = undefined;
    this._clearSeries();
    this._lastError = undefined;
    this._render();
  }

  _humanizeField(field) {
    const text = String(field);
    const mapMatch = text.match(/^(mpptMap|pvMap)\.(mppt|pv)(\d+)(.*)$/i);
    if (mapMatch) {
      const [, mapName, , index, suffix] = mapMatch;
      const prefix = mapName.toLowerCase().startsWith("mppt") ? "MPPT" : "PV";
      return `${prefix} ${index} ${this._humanizeField(suffix || "")}`.trim();
    }
    return text
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/(mppt|pv)(\d+)/gi, "$1 $2")
      .replace(/\bmppt\b/gi, "MPPT")
      .replace(/\bpv\b/gi, "PV")
      .replace(/\bac\b/gi, "AC")
      .replace(/\bdc\b/gi, "DC")
      .replace(/\beps\b/gi, "EPS")
      .replace(/\bsoc\b/gi, "SOC")
      .replace(/\./g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  _formatDateTime(timestamp) {
    if (!Number.isFinite(timestamp)) {
      return "Unknown";
    }
    return new Date(timestamp).toLocaleString();
  }

  _formatAxisTime(timestamp) {
    if (!Number.isFinite(timestamp)) {
      return "";
    }
    const date = new Date(timestamp);
    if (this._mode === SolaxHistoryViewerCard.MODE_PLANT_STATISTICS) {
      if (this._plantView === SolaxHistoryViewerCard.PLANT_VIEW_MONTH) {
        return date.toLocaleDateString([], { day: "numeric", timeZone: "UTC" });
      }
      return date.toLocaleDateString([], { month: "short", timeZone: "UTC" });
    }
    if (this._customHistoryRange || this._rangeHours > 24) {
      return date.toLocaleDateString([], { month: "short", day: "numeric" });
    }
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  _formatValue(value) {
    if (!Number.isFinite(value)) {
      return "n/a";
    }
    if (Math.abs(value) >= 1000) {
      return value.toFixed(0);
    }
    if (Math.abs(value) >= 100) {
      return value.toFixed(1);
    }
    return value.toFixed(2).replace(/\.00$/, "");
  }

  _formatTooltipTime(timestamp) {
    if (!Number.isFinite(timestamp)) {
      return "Unknown";
    }
    const date = new Date(timestamp);
    if (this._mode === SolaxHistoryViewerCard.MODE_PLANT_STATISTICS) {
      if (this._plantView === SolaxHistoryViewerCard.PLANT_VIEW_YEAR) {
        return date.toLocaleDateString([], {
          month: "long",
          year: "numeric",
          timeZone: "UTC",
        });
      }
      return date.toLocaleDateString([], {
        weekday: "short",
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      });
    }
    return date.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  _selectedFieldArray() {
    return this._fields
      .map((item) => item.field)
      .filter((field) => this._selectedFields.has(field));
  }

  _deviceShortLabel(device) {
    const serial = String(device?.device_sn || "");
    if (serial.length <= 8) {
      return serial || "Device";
    }
    return `${serial.slice(0, 4)}…${serial.slice(-4)}`;
  }

  _seriesForChart() {
    const selectedFields = this._selectedFieldArray();
    const colors = [
      "#1e88e5",
      "#ffb300",
      "#43a047",
      "#d81b60",
      "#7e57c2",
      "#00acc1",
      "#fb8c00",
      "#8e24aa",
      "#26a69a",
      "#ef5350",
      "#5c6bc0",
      "#9ccc65",
    ];
    const series = [];
    let colorIndex = 0;

    if (this._mode === SolaxHistoryViewerCard.MODE_PLANT_STATISTICS) {
      for (const field of selectedFields) {
        series.push({
          key: field,
          label: this._humanizeField(field),
          color: colors[colorIndex++ % colors.length],
          value: (row) => row.values?.[field],
        });
      }
      return series;
    }

    const devices = this._selectedDevices();
    for (const field of selectedFields) {
      for (const device of devices) {
        series.push({
          key: `${device.device_sn}|${field}`,
          label:
            devices.length === 1
              ? this._humanizeField(field)
              : `${this._deviceShortLabel(device)} ${this._humanizeField(field)}`,
          color: colors[colorIndex++ % colors.length],
          value: (row) => row.deviceValues?.[device.device_sn]?.[field],
        });
      }
    }
    return series.slice(0, 36);
  }

  _chartYDomain(values) {
    let minY = Math.min(...values);
    let maxY = Math.max(...values);
    const autoZoom =
      this._mode === SolaxHistoryViewerCard.MODE_DEVICE_HISTORY &&
      this._chartScaleMode === SolaxHistoryViewerCard.CHART_SCALE_AUTO;

    if (!autoZoom) {
      if (minY > 0) {
        minY = 0;
      }
      if (maxY < 0) {
        maxY = 0;
      }
    }

    if (minY === maxY) {
      const centeredPadding = Math.max(Math.abs(maxY) * 0.01, 1);
      return {
        minY: minY - centeredPadding,
        maxY: maxY + centeredPadding,
      };
    }

    if (autoZoom) {
      const span = maxY - minY;
      const padding = Math.max(span * 0.08, Math.abs(maxY) * 0.001, 0.01);
      minY -= padding;
      maxY += padding;
    }

    return { minY, maxY };
  }

  _renderChart() {
    const series = this._seriesForChart();
    if (!this._rows.length || !series.length) {
      this._chartModel = undefined;
      return `
        <div class="chart-empty">
          ${this._rows.length ? "Select at least one field to draw the chart." : `Fetch ${this._mode === SolaxHistoryViewerCard.MODE_PLANT_STATISTICS ? "statistics" : "history"} to draw the chart.`}
        </div>
      `;
    }

    const width = 920;
    const height = 360;
    const pad = { left: 62, right: 24, top: 28, bottom: 48 };
    const minX = Math.min(...this._rows.map((row) => row.timestamp));
    const maxX = Math.max(...this._rows.map((row) => row.timestamp));
    const values = [];
    for (const row of this._rows) {
      for (const item of series) {
        const value = item.value(row);
        if (Number.isFinite(value)) {
          values.push(value);
        }
      }
    }
    if (!values.length) {
      this._chartModel = undefined;
      return `<div class="chart-empty">Selected fields have no numeric values in this result.</div>`;
    }
    const { minY, maxY } = this._chartYDomain(values);
    const xScale = (timestamp) =>
      pad.left +
      ((timestamp - minX) / Math.max(1, maxX - minX)) *
        (width - pad.left - pad.right);
    const yScale = (value) =>
      pad.top +
      (1 - (value - minY) / Math.max(1, maxY - minY)) *
        (height - pad.top - pad.bottom);

    const chartSvg =
      this._mode === SolaxHistoryViewerCard.MODE_PLANT_STATISTICS
        ? this._renderBarSeries(series, width, height, pad, xScale, yScale)
        : this._renderLineSeries(series, xScale, yScale);
    const legend = series
      .map(
        (item) => `
          <span class="legend-item">
            <span class="legend-dot" style="background:${item.color}"></span>
            ${this._escape(item.label)}
          </span>
        `
      )
      .join("");

    this._chartModel = { width, height, pad, minX, maxX, minY, maxY, rows: this._rows, series, xScale, yScale };

    return `
      <div class="chart-wrap" data-role="chart-wrap">
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="SolaX history chart" data-role="chart-svg">
          <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height - pad.bottom}" class="axis" />
          <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" class="axis" />
          <line x1="${pad.left}" y1="${pad.top}" x2="${width - pad.right}" y2="${pad.top}" class="grid-line" />
          <line x1="${pad.left}" y1="${(height - pad.bottom + pad.top) / 2}" x2="${width - pad.right}" y2="${(height - pad.bottom + pad.top) / 2}" class="grid-line" />
          <text x="${pad.left - 8}" y="${pad.top + 4}" text-anchor="end" class="axis-label">${this._escape(this._formatValue(maxY))}</text>
          <text x="${pad.left - 8}" y="${height - pad.bottom + 4}" text-anchor="end" class="axis-label">${this._escape(this._formatValue(minY))}</text>
          <text x="${pad.left}" y="${height - 14}" text-anchor="start" class="axis-label">${this._escape(this._formatAxisTime(minX))}</text>
          <text x="${width - pad.right}" y="${height - 14}" text-anchor="end" class="axis-label">${this._escape(this._formatAxisTime(maxX))}</text>
          ${chartSvg}
          <line x1="0" y1="${pad.top}" x2="0" y2="${height - pad.bottom}" class="crosshair" data-role="crosshair" />
          <rect x="${pad.left}" y="${pad.top}" width="${width - pad.left - pad.right}" height="${height - pad.top - pad.bottom}" class="chart-hitbox" data-role="chart-hitbox" />
        </svg>
        <div class="chart-tooltip" data-role="tooltip"></div>
        <div class="legend">${legend}</div>
      </div>
    `;
  }

  _renderLineSeries(series, xScale, yScale) {
    return series
      .map((item) => {
        const segments = [];
        let current = [];
        for (const row of this._rows) {
          const value = item.value(row);
          if (Number.isFinite(value)) {
            current.push(`${xScale(row.timestamp).toFixed(1)},${yScale(value).toFixed(1)}`);
          } else if (current.length) {
            segments.push(current);
            current = [];
          }
        }
        if (current.length) {
          segments.push(current);
        }
        return segments
          .map((points) =>
            points.length === 1
              ? `<circle cx="${points[0].split(",")[0]}" cy="${points[0].split(",")[1]}" r="3.5" fill="${item.color}" />`
              : `<polyline points="${points.join(" ")}" fill="none" stroke="${item.color}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" />`
          )
          .join("");
      })
      .join("");
  }

  _renderBarSeries(series, width, height, pad, xScale, yScale) {
    const availableWidth = width - pad.left - pad.right;
    const slot = availableWidth / Math.max(1, this._rows.length);
    const groupWidth = Math.min(34, Math.max(9, slot * 0.72));
    const barWidth = Math.max(3, groupWidth / Math.max(1, series.length));
    const zeroY = yScale(0);
    return this._rows
      .map((row) => {
        const center = xScale(row.timestamp);
        return series
          .map((item, index) => {
            const value = item.value(row);
            if (!Number.isFinite(value)) {
              return "";
            }
            const x = center - groupWidth / 2 + index * barWidth;
            const y = yScale(Math.max(0, value));
            const h = Math.max(1, Math.abs(zeroY - yScale(value)));
            return `<rect x="${x.toFixed(1)}" y="${Math.min(y, zeroY).toFixed(1)}" width="${Math.max(2, barWidth - 1).toFixed(1)}" height="${h.toFixed(1)}" rx="2" fill="${item.color}" opacity="0.9" />`;
          })
          .join("");
      })
      .join("");
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

  _renderModeSwitch() {
    const modes = [
      { id: SolaxHistoryViewerCard.MODE_DEVICE_HISTORY, label: "Device History" },
      { id: SolaxHistoryViewerCard.MODE_PLANT_STATISTICS, label: "Plant Statistics" },
    ];
    return `
      <div class="mode-switch" role="tablist">
        ${modes
          .map(
            (mode) => `
          <button class="mode-button ${this._mode === mode.id ? "active" : ""}" data-mode="${mode.id}" type="button">
            ${this._escape(mode.label)}
          </button>
        `
          )
          .join("")}
      </div>
    `;
  }

  _renderPlantViewSwitch() {
    const views = [
      { id: SolaxHistoryViewerCard.PLANT_VIEW_YEAR, label: "Year" },
      { id: SolaxHistoryViewerCard.PLANT_VIEW_MONTH, label: "Month" },
    ];
    return `
      <div class="small-switch" role="tablist">
        ${views
          .map(
            (view) => `
          <button class="plant-view-button ${this._plantView === view.id ? "active" : ""}" data-view="${view.id}" type="button">
            ${this._escape(view.label)}
          </button>
        `
          )
          .join("")}
      </div>
    `;
  }

  _renderDeviceTypeOptions() {
    const types = this._deviceTypes();
    if (!types.length) {
      return `<option value="">No devices</option>`;
    }
    return types
      .map((type) => {
        const selected = Number(type) === Number(this._selectedDeviceType) ? "selected" : "";
        return `<option value="${type}" ${selected}>${this._escape(SolaxHistoryViewerCard.DEVICE_TYPE_NAMES[type] || `Device ${type}`)}</option>`;
      })
      .join("");
  }

  _renderPlantOptions() {
    if (!this._plants.length) {
      return `<option value="">No plants found</option>`;
    }
    return this._plants
      .map((plant) => {
        const key = this._plantKey(plant);
        const selected = key === this._selectedPlantKey ? "selected" : "";
        return `<option value="${this._escape(key)}" ${selected}>${this._escape(plant.label)}</option>`;
      })
      .join("");
  }

  _renderYearOptions() {
    const currentYear = this._currentYear();
    const years = Array.from({ length: 6 }, (_, index) => currentYear - index);
    return years
      .map((year) => `<option value="${year}" ${year === this._selectedYear ? "selected" : ""}>${year}</option>`)
      .join("");
  }

  _renderMonthOptions() {
    const formatter = new Intl.DateTimeFormat(undefined, { month: "long" });
    const maxMonth = this._selectedYear === this._currentYear() ? new Date().getMonth() + 1 : 12;
    return Array.from({ length: maxMonth }, (_, index) => index + 1)
      .map((month) => {
        const label = formatter.format(new Date(this._selectedYear, month - 1, 1));
        return `<option value="${month}" ${month === this._selectedMonth ? "selected" : ""}>${this._escape(label)}</option>`;
      })
      .join("");
  }

  _renderDeviceSelector() {
    const devices = this._familyDevices();
    if (!devices.length) {
      return `<div class="chips-empty compact">No devices in this family.</div>`;
    }
    return `
      <div class="device-actions">
        <button type="button" class="mini-action" id="select-all-devices">Select all</button>
        <button type="button" class="mini-action" id="select-no-devices">Clear</button>
        <span>${this._selectedDevices().length} selected</span>
      </div>
      <div class="device-chips">
        ${devices
          .map((device) => {
            const key = this._deviceKey(device);
            const selected = this._selectedDeviceKeys.has(key);
            return `
              <button type="button" class="device-chip ${selected ? "selected" : ""}" data-device-key="${this._escape(key)}">
                <span>${this._escape(device.label)}</span>
                <small>${this._escape(device.source || "inventory")}</small>
              </button>
            `;
          })
          .join("")}
      </div>
    `;
  }

  _renderFieldChips() {
    if (!this._fields.length) {
      return `
        <div class="chips-empty">
          Fetch ${this._mode === SolaxHistoryViewerCard.MODE_PLANT_STATISTICS ? "statistics" : "history"} first. Available chart fields are built from the returned API rows.
        </div>
      `;
    }
    return this._fields
      .map((item) => {
        const selected = this._selectedFields.has(item.field);
        return `
          <button type="button" class="chip ${selected ? "selected" : ""}" data-field="${this._escape(item.field)}">
            ${this._escape(this._humanizeField(item.field))}
            <span>${item.count}</span>
          </button>
        `;
      })
      .join("");
  }

  _renderScaleControls() {
    if (this._mode !== SolaxHistoryViewerCard.MODE_DEVICE_HISTORY) {
      return "";
    }
    const autoZoom = this._chartScaleMode === SolaxHistoryViewerCard.CHART_SCALE_AUTO;
    return `
      <div class="scale-panel">
        <div>
          <div class="field-title">Chart Scale</div>
          <div class="scale-helper">
            ${autoZoom
              ? "Auto zoom uses the selected data range so stable values like grid frequency show small changes."
              : "Zero baseline keeps power and energy graphs anchored to 0."}
          </div>
        </div>
        <div class="scale-buttons" role="group" aria-label="Chart scale">
          <button type="button" class="scale-button ${!autoZoom ? "active" : ""}" data-scale="${SolaxHistoryViewerCard.CHART_SCALE_ZERO}">
            Zero baseline
          </button>
          <button type="button" class="scale-button ${autoZoom ? "active" : ""}" data-scale="${SolaxHistoryViewerCard.CHART_SCALE_AUTO}">
            Auto zoom
          </button>
        </div>
      </div>
    `;
  }

  _renderDayDrilldowns() {
    if (this._mode !== SolaxHistoryViewerCard.MODE_DEVICE_HISTORY || this._rows.length < 2) {
      return "";
    }
    const days = new Map();
    for (const row of this._rows) {
      const date = new Date(row.timestamp);
      const start = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
      days.set(start, date.toLocaleDateString([], { month: "short", day: "numeric" }));
    }
    if (days.size <= 1) {
      return "";
    }
    return `
      <div class="day-panel">
        <div class="field-title">Day Drilldown</div>
        <div class="chips">
          ${Array.from(days.entries())
            .map(
              ([start, label]) => `
            <button type="button" class="day-chip" data-day-start="${start}">${this._escape(label)}</button>
          `
            )
            .join("")}
        </div>
      </div>
    `;
  }

  _renderControls() {
    const selectedPlant = this._selectedPlant();
    if (this._mode === SolaxHistoryViewerCard.MODE_PLANT_STATISTICS) {
      return `
        <div class="controls plant-controls">
          <label>View
            ${this._renderPlantViewSwitch()}
          </label>
          <label>Plant
            <select id="plant" ${this._loadingPlants || !this._plants.length ? "disabled" : ""}>
              ${this._renderPlantOptions()}
            </select>
          </label>
          <label>Year
            <select id="year">${this._renderYearOptions()}</select>
          </label>
          <label class="${this._plantView === SolaxHistoryViewerCard.PLANT_VIEW_MONTH ? "" : "hidden"}">Month
            <select id="month">${this._renderMonthOptions()}</select>
          </label>
          <button type="button" class="fetch" id="fetch" ${this._fetching || !selectedPlant ? "disabled" : ""}>${this._fetching ? "Fetching..." : "Fetch Statistics"}</button>
        </div>
      `;
    }
    return `
      <div class="controls history-controls">
        <label>Device Family
          <select id="device-type" ${this._loadingDevices || !this._devices.length ? "disabled" : ""}>
            ${this._renderDeviceTypeOptions()}
          </select>
        </label>
        <label>Range
          <select id="range">
            ${SolaxHistoryViewerCard.RANGE_PRESETS.map((preset) => `<option value="${preset.hours}" ${preset.hours === this._rangeHours ? "selected" : ""}>${this._escape(preset.label)}</option>`).join("")}
          </select>
        </label>
        <label>Resolution
          <div class="readonly-control">${this._recommendedInterval(this._rangeHours)} min</div>
        </label>
        <button type="button" class="fetch" id="fetch" ${this._fetching || !this._selectedDevices().length ? "disabled" : ""}>${this._fetching ? "Fetching..." : "Fetch History"}</button>
      </div>
      <div class="device-panel">${this._renderDeviceSelector()}</div>
    `;
  }

  _renderMetrics() {
    const selectedPlant = this._selectedPlant();
    const requests = this._lastResultMeta?.requestCount;
    if (this._mode === SolaxHistoryViewerCard.MODE_PLANT_STATISTICS) {
      const periodLabel = this._plantView === SolaxHistoryViewerCard.PLANT_VIEW_MONTH ? this._yearMonthText() : String(this._selectedYear);
      return `
        <div class="metrics">
          ${this._renderMetric("Plant", selectedPlant?.label || "None", selectedPlant ? `business ${selectedPlant.business_type}` : "Select a plant")}
          ${this._renderMetric(this._plantView === SolaxHistoryViewerCard.PLANT_VIEW_MONTH ? "Days" : "Months", String(this._rows.length), requests ? `${requests} API request(s)` : "No fetch yet")}
          ${this._renderMetric("Fields", String(this._fields.length), `${this._selectedFields.size} selected`)}
          ${this._renderMetric("Last Fetch", this._lastFetchAt ? this._formatDateTime(this._lastFetchAt.getTime()) : "Never", this._lastResultMeta?.helper || periodLabel)}
        </div>
      `;
    }
    const devices = this._selectedDevices();
    return `
      <div class="metrics">
        ${this._renderMetric("Devices", String(devices.length), devices.length ? `${SolaxHistoryViewerCard.DEVICE_TYPE_NAMES[this._selectedDeviceType] || "Device"} selected` : "Select devices")}
        ${this._renderMetric("Rows", String(this._rows.length), requests ? `${requests} API request(s)` : `~${this._estimatedRequestCount()} request(s)`)}
        ${this._renderMetric("Fields", String(this._fields.length), `${this._selectedFields.size} selected`)}
        ${this._renderMetric("Last Fetch", this._lastFetchAt ? this._formatDateTime(this._lastFetchAt.getTime()) : "Never", this._lastResultMeta?.helper || `${this._rangePreset().label} at ${this._recommendedInterval(this._rangeHours)} min`)}
      </div>
    `;
  }

  _render() {
    if (!this.shadowRoot) {
      return;
    }
    if (this._shellRendered) {
      this._updateDynamicContent();
      return;
    }
    const statusText = this._lastError ? "Error" : this._fetching ? "Fetching" : this._rows.length ? "Ready" : "Idle";
    const statusClass = this._lastError ? "error" : this._fetching ? "starting" : this._rows.length ? "active" : "idle";
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          container-type: inline-size;
          display: block;
          max-width: none;
          min-width: 0;
          overflow-anchor: none;
          width: 100%;
        }
        ha-card {
          box-sizing: border-box;
          overflow-anchor: none;
          overflow: hidden;
          border-radius: var(--ha-card-border-radius, 18px);
          color: var(--primary-text-color);
          max-width: none;
          width: 100%;
          background:
            radial-gradient(circle at 16% 10%, rgba(255, 186, 0, 0.25), transparent 30%),
            radial-gradient(circle at 88% 18%, rgba(21, 101, 192, 0.18), transparent 32%),
            linear-gradient(135deg, var(--ha-card-background, var(--card-background-color)) 0%, var(--secondary-background-color) 100%);
          border: 1px solid var(--divider-color);
          box-shadow: var(--ha-card-box-shadow, 0 8px 28px rgba(0, 0, 0, 0.16));
        }
        .card { box-sizing: border-box; overflow-anchor: none; padding: 20px; width: 100%; }
        .header { align-items: flex-start; display: flex; gap: 14px; justify-content: space-between; }
        .brand { align-items: center; display: flex; gap: 12px; min-width: 0; }
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
        ha-icon { --mdc-icon-size: 26px; }
        .title { font-size: 1.15rem; font-weight: 700; letter-spacing: -0.01em; line-height: 1.2; margin: 0; }
        .subtitle { color: var(--secondary-text-color); font-size: 0.82rem; line-height: 1.35; margin-top: 4px; }
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
        .dot { border-radius: 999px; height: 9px; width: 9px; }
        .status.active .dot { animation: pulse 1.8s ease-in-out infinite; background: var(--success-color, #43a047); box-shadow: 0 0 0 5px rgba(67, 160, 71, 0.14); }
        .status.starting .dot { background: var(--warning-color, #ffb300); }
        .status.error .dot { background: var(--error-color, #db4437); }
        .status.idle .dot { background: var(--secondary-text-color); }
        .mode-switch, .small-switch {
          background: rgba(127, 127, 127, 0.08);
          border: 1px solid var(--divider-color);
          border-radius: 16px;
          display: grid;
          gap: 6px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          padding: 6px;
        }
        .mode-switch { margin: 18px 0 0; }
        .mode-button, .plant-view-button, .toggle-button, .mini-action {
          background: transparent;
          border: 0;
          border-radius: 12px;
          color: var(--secondary-text-color);
          cursor: pointer;
          font: inherit;
          font-weight: 800;
          min-height: 38px;
        }
        .mode-button.active, .plant-view-button.active, .toggle-button.active {
          background: linear-gradient(135deg, rgba(21, 101, 192, 0.18), rgba(255, 186, 0, 0.14));
          color: var(--primary-text-color);
        }
        .controls {
          align-items: end;
          display: grid;
          gap: 10px;
          margin: 14px 0;
        }
        .history-controls { grid-template-columns: minmax(150px, 1fr) minmax(130px, 0.8fr) minmax(130px, 0.8fr) minmax(170px, 0.9fr); }
        .plant-controls { grid-template-columns: minmax(150px, 0.8fr) minmax(220px, 1.4fr) minmax(120px, 0.7fr) minmax(150px, 0.8fr) minmax(170px, 0.9fr); }
        .controls > *, .metrics > *, .mode-switch > *, .small-switch > * { min-width: 0; }
        label {
          color: var(--secondary-text-color);
          display: grid;
          font-size: 0.74rem;
          font-weight: 800;
          gap: 6px;
          letter-spacing: 0.04em;
          min-width: 0;
          text-transform: uppercase;
        }
        label.hidden { display: none; }
        select, .readonly-control, button.fetch, .toggle-button {
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color);
          box-sizing: border-box;
          border-radius: 13px;
          color: var(--primary-text-color);
          font: inherit;
          max-width: 100%;
          min-height: 42px;
          min-width: 0;
          padding: 0 12px;
          width: 100%;
        }
        select { overflow: hidden; text-overflow: ellipsis; }
        .readonly-control { align-items: center; display: flex; font-weight: 800; justify-content: center; }
        button.fetch {
          align-self: end;
          background: linear-gradient(135deg, #1565c0, #0d47a1);
          border: 0;
          color: #fff;
          cursor: pointer;
          font-weight: 800;
          min-width: 0;
          padding: 0 16px;
          white-space: nowrap;
        }
        button.fetch:disabled { cursor: wait; opacity: 0.65; }
        .device-panel, .day-panel {
          background: rgba(127, 127, 127, 0.06);
          border: 1px solid var(--divider-color);
          border-radius: 16px;
          box-sizing: border-box;
          margin: 0 0 14px;
          padding: 12px;
        }
        .device-actions { align-items: center; color: var(--secondary-text-color); display: flex; flex-wrap: wrap; font-size: 0.75rem; gap: 8px; margin-bottom: 10px; }
        .mini-action { border: 1px solid var(--divider-color); min-height: 30px; padding: 0 10px; }
        .device-chips { display: flex; flex-wrap: wrap; gap: 8px; }
        .device-chip {
          align-items: flex-start;
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 14px;
          color: var(--primary-text-color);
          cursor: pointer;
          display: grid;
          font: inherit;
          font-size: 0.78rem;
          font-weight: 750;
          gap: 2px;
          min-width: 150px;
          padding: 9px 11px;
          text-align: left;
        }
        .device-chip.selected { background: rgba(21, 101, 192, 0.14); border-color: rgba(21, 101, 192, 0.42); }
        .device-chip small { color: var(--secondary-text-color); font-size: 0.68rem; font-weight: 700; }
        .metrics { display: grid; gap: 10px; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 14px; }
        .metric { background: rgba(127, 127, 127, 0.08); border: 1px solid var(--divider-color); border-radius: 14px; min-width: 0; padding: 12px; }
        .metric-label { color: var(--secondary-text-color); font-size: 0.76rem; font-weight: 700; line-height: 1.2; }
        .metric-value { font-size: 1rem; font-weight: 750; line-height: 1.3; margin-top: 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .metric-helper { color: var(--secondary-text-color); font-size: 0.74rem; line-height: 1.25; margin-top: 5px; }
        .field-panel { background: rgba(127, 127, 127, 0.06); border: 1px solid var(--divider-color); border-radius: 16px; box-sizing: border-box; margin-bottom: 14px; min-height: 118px; padding: 12px; }
        .field-title { color: var(--secondary-text-color); font-size: 0.76rem; font-weight: 800; letter-spacing: 0.05em; margin-bottom: 9px; text-transform: uppercase; }
        .chips { display: flex; flex-wrap: wrap; gap: 8px; }
        .chip, .day-chip {
          align-items: center;
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 999px;
          color: var(--primary-text-color);
          cursor: pointer;
          display: inline-flex;
          font: inherit;
          font-size: 0.78rem;
          font-weight: 750;
          gap: 7px;
          padding: 7px 10px;
        }
        .chip.selected { background: rgba(21, 101, 192, 0.14); border-color: rgba(21, 101, 192, 0.42); }
        .chip span { color: var(--secondary-text-color); font-size: 0.7rem; }
        .chips-empty, .chart-empty { align-items: center; box-sizing: border-box; color: var(--secondary-text-color); display: flex; font-size: 0.88rem; justify-content: center; line-height: 1.45; padding: 18px; text-align: center; }
        .chips-empty.compact { min-height: 44px; padding: 8px; }
        .chart-empty { min-height: 420px; }
        .scale-panel {
          align-items: center;
          background: rgba(127, 127, 127, 0.06);
          border: 1px solid var(--divider-color);
          border-radius: 16px;
          box-sizing: border-box;
          display: flex;
          gap: 12px;
          justify-content: space-between;
          margin-bottom: 14px;
          padding: 12px;
        }
        .scale-helper { color: var(--secondary-text-color); font-size: 0.76rem; line-height: 1.35; }
        .scale-buttons { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
        .scale-button {
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 999px;
          color: var(--primary-text-color);
          cursor: pointer;
          font: inherit;
          font-size: 0.78rem;
          font-weight: 800;
          min-height: 34px;
          padding: 0 12px;
        }
        .scale-button.active {
          background: rgba(21, 101, 192, 0.14);
          border-color: rgba(21, 101, 192, 0.42);
        }
        .chart-wrap { background: rgba(127, 127, 127, 0.06); border: 1px solid var(--divider-color); border-radius: 18px; box-sizing: border-box; min-height: 420px; overflow: hidden; padding: 10px; position: relative; }
        svg { display: block; height: auto; max-width: 100%; width: 100%; }
        .axis { stroke: var(--secondary-text-color); stroke-opacity: 0.55; stroke-width: 1; }
        .grid-line { stroke: var(--divider-color); stroke-width: 1; }
        .axis-label { fill: var(--secondary-text-color); font-size: 12px; }
        .crosshair { display: none; pointer-events: none; stroke: var(--primary-text-color); stroke-dasharray: 4 4; stroke-opacity: 0.45; stroke-width: 1; }
        .chart-hitbox { cursor: crosshair; fill: transparent; pointer-events: all; }
        .chart-tooltip { background: var(--card-background-color, #fff); border: 1px solid var(--divider-color); border-radius: 12px; box-shadow: 0 10px 26px rgba(0, 0, 0, 0.24); color: var(--primary-text-color); display: none; font-size: 0.76rem; left: 0; max-width: min(310px, calc(100% - 24px)); padding: 9px 10px; pointer-events: none; position: absolute; top: 0; z-index: 2; }
        .tooltip-title { font-weight: 850; margin-bottom: 6px; }
        .tooltip-row { align-items: center; display: grid; gap: 7px; grid-template-columns: 9px minmax(0, 1fr) auto; margin-top: 4px; }
        .tooltip-dot { border-radius: 999px; height: 8px; width: 8px; }
        .tooltip-label { color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .tooltip-value { font-weight: 850; }
        .tooltip-hint { color: var(--secondary-text-color); font-size: 0.7rem; margin-top: 7px; }
        .legend { display: flex; flex-wrap: wrap; gap: 8px 12px; padding: 0 10px 10px; }
        .legend-item { align-items: center; color: var(--secondary-text-color); display: inline-flex; font-size: 0.78rem; gap: 6px; }
        .legend-dot { border-radius: 999px; height: 8px; width: 8px; }
        .error-text { background: rgba(219, 68, 55, 0.1); border: 1px solid rgba(219, 68, 55, 0.22); border-radius: 12px; color: var(--error-color, #db4437); font-size: 0.84rem; font-weight: 700; margin-top: 12px; padding: 10px 12px; }
        @keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.35); } }
        @container (max-width: 940px) { .history-controls, .plant-controls { grid-template-columns: repeat(2, minmax(0, 1fr)); } button.fetch { grid-column: 1 / -1; } .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
        @container (max-width: 560px) { .history-controls, .plant-controls, .metrics, .mode-switch { grid-template-columns: 1fr; } button.fetch { grid-column: auto; } .header { align-items: stretch; flex-direction: column; } .status { justify-content: center; } .scale-panel { align-items: stretch; flex-direction: column; } .scale-buttons { justify-content: stretch; } .scale-button { flex: 1; } }
        @media (max-width: 720px) { .history-controls, .plant-controls, .metrics, .mode-switch { grid-template-columns: 1fr; } .header { align-items: stretch; flex-direction: column; } .status { justify-content: center; } .scale-panel { align-items: stretch; flex-direction: column; } .scale-buttons { justify-content: stretch; } .scale-button { flex: 1; } }
      </style>
      <ha-card>
        <div class="card">
          <div class="header">
            <div class="brand">
              <div class="icon-wrap"><ha-icon icon="mdi:chart-line"></ha-icon></div>
              <div>
                <h2 class="title" data-role="title">${this._escape(this._name)}</h2>
                <div class="subtitle">Display-only Developer API history and plant statistics. Fetch manually; nothing is written to Home Assistant Recorder.</div>
              </div>
            </div>
            <div class="status ${statusClass}" data-role="status">
              <span class="dot"></span>
              <span data-role="status-text">${this._escape(statusText)}</span>
            </div>
          </div>

          <div data-section="mode">${this._renderModeSwitch()}</div>
          <div data-section="controls">${this._renderControls()}</div>
          <div data-section="metrics">${this._renderMetrics()}</div>
          <div data-section="days">${this._renderDayDrilldowns()}</div>

          <div class="field-panel">
            <div class="field-title">Available Fields</div>
            <div class="chips" data-section="chips">${this._renderFieldChips()}</div>
          </div>

          <div data-section="scale">${this._renderScaleControls()}</div>
          <div data-section="chart">${this._renderChart()}</div>
          <div data-section="error">${this._lastError ? `<div class="error-text">${this._escape(this._lastError)}</div>` : ""}</div>
        </div>
      </ha-card>
    `;
    this._shellRendered = true;
    this._bindEvents();
    this._updateDynamicContent();
  }

  _setSectionHTML(name, html) {
    const section = this.shadowRoot?.querySelector(`[data-section="${name}"]`);
    if (section && section.innerHTML !== html) {
      section.innerHTML = html;
    }
  }

  _withStableViewport(updateCallback) {
    const scrollingElement = document.scrollingElement || document.documentElement;
    const scrollTop = scrollingElement?.scrollTop ?? window.scrollY;
    const scrollLeft = scrollingElement?.scrollLeft ?? window.scrollX;
    updateCallback();
    requestAnimationFrame(() => {
      const currentTop = scrollingElement?.scrollTop ?? window.scrollY;
      const currentLeft = scrollingElement?.scrollLeft ?? window.scrollX;
      if (Math.abs(currentTop - scrollTop) > 1 || Math.abs(currentLeft - scrollLeft) > 1) {
        if (scrollingElement) {
          scrollingElement.scrollTop = scrollTop;
          scrollingElement.scrollLeft = scrollLeft;
        } else {
          window.scrollTo(scrollLeft, scrollTop);
        }
      }
    });
  }

  _updateDynamicContent() {
    if (!this.shadowRoot || !this._shellRendered) {
      return;
    }
    this._withStableViewport(() => this._updateDynamicContentUnsafe());
  }

  _updateDynamicContentUnsafe() {
    const statusText = this._lastError ? "Error" : this._fetching ? "Fetching" : this._rows.length ? "Ready" : "Idle";
    const statusClass = this._lastError ? "error" : this._fetching ? "starting" : this._rows.length ? "active" : "idle";
    const title = this.shadowRoot.querySelector('[data-role="title"]');
    if (title) {
      title.textContent = this._name;
    }
    const status = this.shadowRoot.querySelector('[data-role="status"]');
    if (status) {
      status.className = `status ${statusClass}`;
    }
    const statusTextNode = this.shadowRoot.querySelector('[data-role="status-text"]');
    if (statusTextNode) {
      statusTextNode.textContent = statusText;
    }
    this._setSectionHTML("mode", this._renderModeSwitch());
    this._setSectionHTML("controls", this._renderControls());
    this._setSectionHTML("metrics", this._renderMetrics());
    this._setSectionHTML("days", this._renderDayDrilldowns());
    this._setSectionHTML("chips", this._renderFieldChips());
    this._setSectionHTML("scale", this._renderScaleControls());
    this._setSectionHTML("chart", this._renderChart());
    this._setSectionHTML(
      "error",
      this._lastError ? `<div class="error-text">${this._escape(this._lastError)}</div>` : ""
    );
  }

  _nearestChartRow(event) {
    const model = this._chartModel;
    const svg = this.shadowRoot?.querySelector('[data-role="chart-svg"]');
    if (!model || !svg || !model.rows.length) {
      return undefined;
    }
    const rect = svg.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * model.width;
    const targetTime =
      model.minX +
      ((x - model.pad.left) / Math.max(1, model.width - model.pad.left - model.pad.right)) *
        (model.maxX - model.minX);
    return model.rows.reduce((closest, row) =>
      Math.abs(row.timestamp - targetTime) < Math.abs(closest.timestamp - targetTime) ? row : closest
    );
  }

  _showTooltip(event) {
    const model = this._chartModel;
    const row = this._nearestChartRow(event);
    const root = this.shadowRoot;
    const wrap = root?.querySelector('[data-role="chart-wrap"]');
    const tooltip = root?.querySelector('[data-role="tooltip"]');
    const crosshair = root?.querySelector('[data-role="crosshair"]');
    if (!model || !row || !wrap || !tooltip || !crosshair) {
      return;
    }
    const x = model.xScale(row.timestamp);
    crosshair.setAttribute("x1", String(x));
    crosshair.setAttribute("x2", String(x));
    crosshair.style.display = "block";
    const values = model.series
      .map((item) => ({ item, value: item.value(row) }))
      .filter((entry) => Number.isFinite(entry.value))
      .slice(0, 14);
    tooltip.innerHTML = `
      <div class="tooltip-title">${this._escape(this._formatTooltipTime(row.timestamp))}</div>
      ${values
        .map(
          ({ item, value }) => `
        <div class="tooltip-row">
          <span class="tooltip-dot" style="background:${item.color}"></span>
          <span class="tooltip-label">${this._escape(item.label)}</span>
          <span class="tooltip-value">${this._escape(this._formatValue(value))}</span>
        </div>
      `
        )
        .join("")}
      ${this._mode === SolaxHistoryViewerCard.MODE_PLANT_STATISTICS ? `<div class="tooltip-hint">Click to drill down</div>` : ""}
    `;
    tooltip.style.display = "block";
    const wrapRect = wrap.getBoundingClientRect();
    const left = Math.min(Math.max(12, event.clientX - wrapRect.left + 14), wrapRect.width - 320);
    const top = Math.min(Math.max(12, event.clientY - wrapRect.top + 14), wrapRect.height - 180);
    tooltip.style.left = `${Math.max(12, left)}px`;
    tooltip.style.top = `${Math.max(12, top)}px`;
  }

  _hideTooltip() {
    const root = this.shadowRoot;
    const tooltip = root?.querySelector('[data-role="tooltip"]');
    const crosshair = root?.querySelector('[data-role="crosshair"]');
    if (tooltip) {
      tooltip.style.display = "none";
    }
    if (crosshair) {
      crosshair.style.display = "none";
    }
  }

  _bindEvents() {
    if (this._eventsBound) {
      return;
    }
    const root = this.shadowRoot;
    root.addEventListener("click", (event) => {
      const button = event.target.closest("button");
      if (!button) {
        return;
      }
      event.preventDefault();
      button.blur();
      if (button.classList.contains("mode-button")) {
        this._mode = button.dataset.mode || SolaxHistoryViewerCard.MODE_DEVICE_HISTORY;
        this._clearSeries();
        this._lastError = undefined;
        this._render();
        return;
      }
      if (button.classList.contains("plant-view-button")) {
        this._plantView = button.dataset.view || SolaxHistoryViewerCard.PLANT_VIEW_YEAR;
        this._clearSeries();
        this._lastError = undefined;
        this._render();
        return;
      }
      if (button.classList.contains("chip")) {
        this._toggleField(button.dataset.field);
        return;
      }
      if (button.classList.contains("scale-button")) {
        this._chartScaleMode = this._normalizeChartScaleMode(button.dataset.scale);
        this._hideTooltip();
        this._render();
        return;
      }
      if (button.classList.contains("device-chip")) {
        this._toggleDevice(button.dataset.deviceKey);
        return;
      }
      if (button.classList.contains("day-chip")) {
        const start = Number(button.dataset.dayStart);
        if (Number.isFinite(start)) {
          void this._drillToDay(start);
        }
        return;
      }
      if (button.id === "select-all-devices") {
        this._selectAllFamilyDevices();
        return;
      }
      if (button.id === "select-no-devices") {
        this._selectNoDevices();
        return;
      }
      if (button.id === "fetch") {
        void this._fetchCurrentMode();
      }
    });
    root.addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLSelectElement)) {
        return;
      }
      if (target.id === "device-type") {
        this._selectedDeviceType = this._toInt(target.value, 1, 1, 4);
        this._selectedDeviceKeys = new Set(this._familyDevices().map((device) => this._deviceKey(device)));
        this._customHistoryRange = undefined;
        this._clearSeries();
        this._lastError = undefined;
        this._render();
        return;
      }
      if (target.id === "plant") {
        this._selectedPlantKey = target.value;
        this._clearSeries();
        this._lastError = undefined;
        this._render();
        return;
      }
      if (target.id === "range") {
        const preset = this._rangePresetForHours(
          this._toInt(target.value, this._defaultRangeHours, 1, 168)
        );
        this._rangeHours = preset.hours;
        this._customHistoryRange = undefined;
        this._clearSeries();
        this._lastError = undefined;
        this._render();
        return;
      }
      if (target.id === "year") {
        this._selectedYear = this._toInt(target.value, this._currentYear(), 2000, this._currentYear());
        const maxMonth = this._selectedYear === this._currentYear() ? new Date().getMonth() + 1 : 12;
        this._selectedMonth = Math.min(this._selectedMonth, maxMonth);
        this._clearSeries();
        this._lastError = undefined;
        this._render();
        return;
      }
      if (target.id === "month") {
        this._selectedMonth = this._toInt(target.value, new Date().getMonth() + 1, 1, 12);
        this._clearSeries();
        this._lastError = undefined;
        this._render();
      }
    });
    root.addEventListener("pointermove", (event) => {
      if (event.target.closest('[data-role="chart-hitbox"]')) {
        this._showTooltip(event);
      }
    });
    root.addEventListener("pointerout", (event) => {
      if (event.target.closest('[data-role="chart-hitbox"]')) {
        this._hideTooltip();
      }
    });
    root.addEventListener("click", (event) => {
      if (!event.target.closest('[data-role="chart-hitbox"]')) {
        return;
      }
      const row = this._nearestChartRow(event);
      if (!row || this._mode !== SolaxHistoryViewerCard.MODE_PLANT_STATISTICS) {
        return;
      }
      if (this._plantView === SolaxHistoryViewerCard.PLANT_VIEW_YEAR) {
        void this._drillToMonth(row.timestamp);
      } else {
        void this._drillToDay(row.timestamp);
      }
    });
    this._eventsBound = true;
  }
}

if (!customElements.get("solax-history-viewer")) {
  customElements.define("solax-history-viewer", SolaxHistoryViewerCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "solax-history-viewer")) {
  window.customCards.push({
    type: "solax-history-viewer",
    name: "SolaX History Viewer",
    description: "Fetches and charts SolaX Developer API device history and plant statistics on demand.",
    preview: true,
  });
}
