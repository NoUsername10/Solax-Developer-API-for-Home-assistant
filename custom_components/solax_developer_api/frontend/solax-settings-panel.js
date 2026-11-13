/* SolaX Developer API GUI settings. Writes go through the existing HA options flow. */
const OPTIONS_FLOW = "config/config_entries/options/flow";
const SNAPSHOT = "solax_developer_api/settings_snapshot";
const MODE_LABELS = {
  self_use: "Self Use",
  feed_in_priority: "Feed-in Priority",
  back_up: "Back Up",
  manual: "Manual",
};
const TABS = [
  ["credentials", "General"],
  ["polling", "Polling & Live View"],
  ["manual_devices", "Devices"],
  ["inverter_modes", "Workmodes"],
  ["advanced", "Advanced"],
];
const TIME_PAIRS = [
  ["charge_start_time_period1", "charge_end_time_period1"],
  ["discharge_start_time_period1", "discharge_end_time_period1"],
  ["charge_start_time_period2", "charge_end_time_period2"],
  ["discharge_start_time_period2", "discharge_end_time_period2"],
];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function schemaFields(result) {
  return Array.isArray(result?.data_schema) ? result.data_schema : [];
}

function initialValue(field) {
  return field.description?.suggested_value ?? field.default ?? "";
}

function optionItems(field) {
  const options = field.selector?.select?.options ?? [];
  return Array.isArray(options) ? options.map((item) => (
    typeof item === "object" ? item : { value: item, label: item }
  )) : [];
}

function fieldKind(field) {
  if (field.selector?.boolean) return "boolean";
  if (field.selector?.number) return "number";
  if (field.selector?.time) return "time";
  if (field.selector?.select) return "select";
  if (field.selector?.text?.multiline) return "textarea";
  if (field.selector?.text?.type === "password") return "password";
  return "text";
}

function validatePeriods(data) {
  const errors = {};
  const anyTime = TIME_PAIRS.some(([start, end]) => data[start] || data[end]);
  if (!data.schedule_enabled) {
    if (anyTime) errors.schedule_enabled = "Enable time periods or clear the entered times.";
    return errors;
  }
  let firstPeriod = false;
  let secondPeriod = false;
  for (const [index, [startKey, endKey]] of TIME_PAIRS.entries()) {
    const start = data[startKey];
    const end = data[endKey];
    if (Boolean(start) !== Boolean(end)) {
      errors[start ? endKey : startKey] = "Enter both the start and end time.";
      continue;
    }
    if (!start) continue;
    if (index < 2) firstPeriod = true;
    else secondPeriod = true;
    if (index >= 2 && !data.enable_time_period2) {
      errors.enable_time_period2 = "Enable period 2 or clear its times.";
    }
    if (start.slice(0, 5) === end.slice(0, 5)) {
      errors[endKey] = "Start and end time must differ.";
    }
  }
  if (!firstPeriod) errors.schedule_enabled = "Enter at least one period 1 window.";
  if (data.enable_time_period2 && !secondPeriod) {
    errors.enable_time_period2 = "Enter a charge or discharge window for period 2.";
  }
  return errors;
}

class SolaxDeveloperSettingsPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "credentials";
    this._entry = null;
    this._snapshot = null;
    this._flow = null;
    this._form = null;
    this._busy = false;
    this._error = "";
    this._success = "";
    this._fieldErrors = {};
    this._selectedSerial = "";
    this._selectedMode = "self_use";
    this._editing = null;
    this._secretDefault = "";
    this._draftValues = null;
    this._loaded = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded && this.isConnected) void this._load();
  }

  set panel(panel) { this._panel = panel; }
  set narrow(narrow) {
    this._narrow = narrow;
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._render();
    if (this._hass && !this._loaded) void this._load();
  }

  disconnectedCallback() {
    void this._closeFlow();
  }

  async _load() {
    this._loaded = true;
    try {
      const launchFlow = new URLSearchParams(window.location.search).get("launch_flow_id");
      if (launchFlow) {
        try {
          await this._hass.callApi("DELETE", `${OPTIONS_FLOW}/${encodeURIComponent(launchFlow)}`);
        } catch (_error) {
          // The selection dialog may have been closed already.
        }
      }
      await this._refreshSnapshot();
      if (!this._entry) return;
      await this._openSection("credentials");
    } catch (error) {
      this._error = `Could not open settings: ${error.message || error}`;
      this._render();
    }
  }

  async _refreshSnapshot() {
    const snapshot = await this._hass.callWS({ type: SNAPSHOT });
    const requested = new URLSearchParams(window.location.search).get("entry_id");
    const entry = snapshot.entries.find((item) => item.entry_id === requested)
      || (requested ? null : snapshot.entries[0]);
    if (!entry) throw new Error("Integration entry was not found.");
    this._snapshot = snapshot;
    this._entry = entry;
    if (!entry.inverters.some((item) => item.serial === this._selectedSerial)) {
      this._selectedSerial = entry.inverters[0]?.serial || "";
    }
    const selected = entry.inverters.find((item) => item.serial === this._selectedSerial);
    if (selected && !selected.modes.includes(this._selectedMode)) {
      this._selectedMode = selected.modes[0];
    }
    this._render();
  }

  async _startFlow() {
    await this._closeFlow();
    const result = await this._hass.callApi("POST", OPTIONS_FLOW, {
      handler: this._entry.entry_id,
    });
    if (result.type !== "menu" || !result.flow_id) {
      throw new Error("Home Assistant did not start the settings flow.");
    }
    this._flow = result.flow_id;
    await this._next({ next_step_id: "classic" });
  }

  async _next(data) {
    const result = await this._hass.callApi("POST", `${OPTIONS_FLOW}/${this._flow}`, data);
    if (result.type === "abort") throw new Error(result.description || result.reason || "Settings flow stopped.");
    return result;
  }

  async _closeFlow() {
    if (!this._flow) return;
    const id = this._flow;
    this._flow = null;
    try {
      await this._hass.callApi("DELETE", `${OPTIONS_FLOW}/${id}`);
    } catch (_error) {
      // A completed flow has already been removed by Home Assistant.
    }
  }

  async _openSection(tab) {
    this._busy = true;
    this._error = "";
    this._success = "";
    this._fieldErrors = {};
    this._form = null;
    this._editing = null;
    this._draftValues = null;
    this._tab = tab;
    this._render();
    try {
      if (tab === "inverter_modes") {
        await this._closeFlow();
      } else {
        await this._startFlow();
        this._form = await this._next({ next_step_id: tab });
        if (tab === "credentials") {
          this._secretDefault = String(
            initialValue(schemaFields(this._form).find((field) => field.name === "client_secret") || {})
          );
        }
      }
    } catch (error) {
      this._error = error.message || String(error);
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _openProfile(mode, profileId = null) {
    if (!this._entry?.controls_enabled) {
      this._error = "Enable inverter work-mode controls under Advanced first.";
      this._render();
      return;
    }
    this._busy = true;
    this._error = "";
    this._success = "";
    this._fieldErrors = {};
    this._form = null;
    this._draftValues = null;
    this._render();
    try {
      await this._startFlow();
      let result = await this._next({ next_step_id: "inverter_modes" });
      if (result.type !== "form") throw new Error("Inverter selection is unavailable.");
      result = await this._next({ inverter_serial: this._selectedSerial });
      if (result.type !== "form") throw new Error("Mode selection is unavailable.");
      result = await this._next({ mode });
      if (result.type !== "form") throw new Error("Profile selection is unavailable.");
      this._form = await this._next({ profile: profileId || "new" });
      if (this._form.type !== "form") throw new Error("Profile settings are unavailable.");
      this._editing = { mode, profileId };
      this._selectedMode = mode;
    } catch (error) {
      this._error = error.message || String(error);
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _label(step, field) {
    const key = `component.solax_developer_api.options.step.${step}.data.${field}`;
    return this._hass?.localize?.(key) || field.replaceAll("_", " ");
  }

  _errorText(key) {
    const localized = this._hass?.localize?.(`component.solax_developer_api.options.error.${key}`);
    return localized || key.replaceAll("_", " ");
  }

  _fieldMarkup(field, step) {
    const kind = fieldKind(field);
    const name = field.name;
    const label = escapeHtml(this._label(step, name));
    let value = this._draftValues && Object.hasOwn(this._draftValues, name)
      ? this._draftValues[name] : initialValue(field);
    if (name === "client_secret" && !this._draftValues) value = "";
    const required = field.required && name !== "client_secret" ? "required" : "";
    let control;
    if (kind === "boolean") {
      control = `<input type="checkbox" name="${escapeHtml(name)}" ${value ? "checked" : ""}>`;
    } else if (kind === "select") {
      control = `<select name="${escapeHtml(name)}" ${required}>${optionItems(field).map((item) =>
        `<option value="${escapeHtml(item.value)}" ${String(item.value) === String(value) ? "selected" : ""}>${escapeHtml(item.label)}</option>`
      ).join("")}</select>`;
    } else if (kind === "textarea") {
      control = `<textarea name="${escapeHtml(name)}" rows="4" ${required}>${escapeHtml(value)}</textarea>`;
    } else {
      const selector = field.selector?.number || {};
      const bounds = kind === "number" ? `min="${escapeHtml(selector.min ?? 0)}" max="${escapeHtml(selector.max ?? 100)}" step="${escapeHtml(selector.step ?? 1)}"` : "";
      const placeholder = name === "client_secret" ? 'placeholder="Leave blank to keep the current secret" autocomplete="new-password"' : "";
      control = `<input name="${escapeHtml(name)}" type="${kind === "password" ? "password" : kind}" value="${escapeHtml(value)}" ${bounds} ${placeholder} ${required}>`;
    }
    const error = this._fieldErrors[name] || (this._form?.errors?.[name] && this._errorText(this._form.errors[name]));
    return `<label class="field ${kind === "boolean" ? "toggle" : ""} ${error ? "invalid" : ""}"><span>${label}</span>${control}${error ? `<small class="field-error">${escapeHtml(error)}</small>` : ""}</label>`;
  }

  _syncScheduleFields(form) {
    const schedule = form.elements.namedItem("schedule_enabled");
    const period2 = form.elements.namedItem("enable_time_period2");
    if (!schedule || !period2) return;
    TIME_PAIRS.forEach(([start, end], index) => {
      for (const name of [start, end]) {
        const input = form.elements.namedItem(name);
        if (input) input.disabled = !schedule.checked || (index >= 2 && !period2.checked);
      }
    });
  }

  _collectForm(form, includeDisabled = false) {
    const data = {};
    for (const field of schemaFields(this._form)) {
      if (field.name === "remove_profile") continue;
      const input = form.elements.namedItem(field.name);
      if (!input) continue;
      if (input.disabled && !includeDisabled) continue;
      const kind = fieldKind(field);
      if (kind === "boolean") data[field.name] = input.checked;
      else if (kind === "number") data[field.name] = Number(input.value);
      else if (field.name === "client_secret" && !input.value) data[field.name] = this._secretDefault;
      else if (input.value !== "" || field.required) data[field.name] = input.value;
    }
    return data;
  }

  async _save(form) {
    if (!this._flow || !this._form) return;
    const data = this._collectForm(form);
    this._draftValues = this._collectForm(form, true);
    if (this._tab === "credentials") this._draftValues.client_secret = form.elements.namedItem("client_secret")?.value || "";
    this._fieldErrors = {};
    if (this._tab === "inverter_modes" && data.schedule_enabled !== undefined) {
      this._fieldErrors = validatePeriods(data);
      if (Object.keys(this._fieldErrors).length) {
        const [field, reason] = Object.entries(this._fieldErrors)[0];
        this._error = `${this._label(this._form.step_id, field)}: ${reason}`;
        this._render();
        return;
      }
    }
    this._busy = true;
    this._error = "";
    this._render();
    try {
      const result = await this._next(data);
      if (result.type === "form") {
        this._form = result;
        const [field, code] = Object.entries(result.errors || {})[0] || [];
        this._error = field === "base" ? this._errorText(code)
          : field ? `${this._label(result.step_id, field)}: ${this._errorText(code)}`
            : "Check the highlighted fields.";
      } else if (result.type === "create_entry") {
        const savedTab = this._tab;
        this._flow = null;
        this._form = null;
        this._editing = null;
        this._draftValues = null;
        await this._refreshSnapshot();
        if (savedTab !== "inverter_modes") await this._openSection(savedTab);
        this._success = "Settings saved. The integration has reloaded.";
      } else {
        throw new Error("Home Assistant returned an unexpected settings result.");
      }
    } catch (error) {
      this._error = error.message || String(error);
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _deleteProfile(profile) {
    if (!window.confirm(`Delete profile “${profile.name}”? Automations using its button will need updating.`)) return;
    await this._openProfile(profile.mode, profile.id);
    if (!this._flow || !this._editing) return;
    const form = this.shadowRoot.querySelector("#settings-form");
    if (!form) return;
    const data = { ...this._collectForm(form), remove_profile: true };
    this._busy = true;
    this._render();
    try {
      const result = await this._next(data);
      if (result.type !== "create_entry") throw new Error("Home Assistant did not remove the profile.");
      this._flow = null;
      this._form = null;
      this._editing = null;
      this._draftValues = null;
      this._success = "Profile deleted.";
      await this._refreshSnapshot();
    } catch (error) {
      this._error = error.message || String(error);
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _renderWorkmodes() {
    if (!this._entry) return "";
    const inverters = this._entry.inverters;
    if (!inverters.length) return '<div class="empty">No compatible inverter has been discovered yet.</div>';
    const inverter = inverters.find((item) => item.serial === this._selectedSerial) || inverters[0];
    const profiles = inverter.profiles;
    const controlsNotice = this._entry.controls_enabled ? "" :
      '<div class="notice">Inverter work-mode controls are off. Enable them under Advanced before creating or applying profiles.</div>';
    const rows = profiles.length ? profiles.map((profile, index) => {
      const settings = profile.settings;
      const periods = TIME_PAIRS.map(([start, end], period) => settings[start] && settings[end]
        ? `${period % 2 === 0 ? "Charge" : "Discharge"}: ${settings[start]}–${settings[end]}` : "").filter(Boolean);
      return `<div class="profile-row"><div><strong>${escapeHtml(profile.name)}</strong><div class="muted">${escapeHtml(MODE_LABELS[profile.mode] || profile.mode)}${periods.length ? ` · ${escapeHtml(periods.join(" · "))}` : ""}</div></div><div class="row-actions"><button type="button" data-edit="${index}">Edit</button><button type="button" class="danger" data-delete="${index}">Delete</button></div></div>`;
    }).join("") : '<div class="empty">No profiles yet. Create one to add an inverter button for automations.</div>';
    const modeOptions = inverter.modes.map((mode) => `<option value="${escapeHtml(mode)}" ${mode === this._selectedMode ? "selected" : ""}>${escapeHtml(MODE_LABELS[mode])}</option>`).join("");
    const editor = this._editing && this._form
      ? `<h2>${this._editing.profileId ? "Edit" : "Create"} profile · ${escapeHtml(MODE_LABELS[this._editing.mode])}</h2>${this._renderForm()}`
      : '<div class="empty">Choose a profile to edit, or select a mode and create a profile.</div>';
    return `${controlsNotice}<div class="columns"><section class="card"><h2>Profiles</h2><label class="field"><span>Inverter</span><select id="inverter-choice">${inverters.map((item) => `<option value="${escapeHtml(item.serial)}" ${item.serial === inverter.serial ? "selected" : ""}>${escapeHtml(item.serial)} · ${item.family === "a1_hybrid_g2" ? "A1-Hybrid-G2" : "Standard"}</option>`).join("")}</select></label><div class="create-row"><select id="mode-choice" aria-label="Mode for new profile">${modeOptions}</select><button type="button" class="primary" id="create-profile" ${!this._entry.controls_enabled ? "disabled" : ""}>+ Create profile</button></div><div class="profile-list">${rows}</div></section><section class="card editor">${editor}</section></div>`;
  }

  _renderForm() {
    if (!this._form || this._form.type !== "form") return '<div class="empty">Loading settings…</div>';
    const step = this._form.step_id;
    const fields = schemaFields(this._form).filter((field) => field.name !== "remove_profile");
    const markup = fields.map((field) => this._fieldMarkup(field, step)).join("");
    const note = step === "credentials" ? '<p class="muted">The current client secret is never displayed. Leave that field blank to keep it.</p>' : "";
    return `<form id="settings-form">${note}<div class="fields">${markup}</div><div class="form-actions"><button class="primary" type="submit" ${this._busy ? "disabled" : ""}>${this._editing ? (this._editing.profileId ? "Save changes" : "Create profile") : "Save settings"}</button></div></form>`;
  }

  _render() {
    const current = TABS.find(([id]) => id === this._tab);
    const body = this._tab === "inverter_modes" ? this._renderWorkmodes()
      : `<section class="card single"><h2>${escapeHtml(current?.[1] || "Settings")}</h2>${this._renderForm()}</section>`;
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block;min-height:100%;background:var(--primary-background-color,#11151c);color:var(--primary-text-color,#f5f5f5);font-family:var(--paper-font-body1_-_font-family,Roboto,Arial,sans-serif)}
        *{box-sizing:border-box}button,input,select,textarea{font:inherit}button{cursor:pointer;border-radius:8px;border:1px solid var(--divider-color,#454b54);background:var(--secondary-background-color,#232b35);color:var(--primary-text-color,#fff);padding:10px 14px}button:hover:not(:disabled){filter:brightness(1.12)}button:disabled{opacity:.5;cursor:default}button.primary{background:var(--primary-color,#03a9f4);border-color:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff);font-weight:600}button.danger{color:var(--error-color,#f77)}
        .wrap{max-width:1440px;margin:0 auto;padding:28px 30px 48px}.head{display:flex;align-items:center;gap:16px;margin-bottom:22px}.head h1{font-size:28px;line-height:1.2;margin:0}.head p{margin:5px 0 0;color:var(--secondary-text-color,#aeb6c2)}.back{white-space:nowrap;text-decoration:none;color:var(--primary-color,#03a9f4)}.menu-toggle{padding:7px 11px;font-size:20px}
        nav{display:flex;gap:4px;overflow:auto;border-bottom:1px solid var(--divider-color,#3c4652);margin-bottom:26px}nav button{border:none;border-radius:0;background:transparent;white-space:nowrap;padding:13px 17px;color:var(--secondary-text-color,#aeb6c2)}nav button.active{color:var(--primary-color,#03a9f4);border-bottom:3px solid var(--primary-color,#03a9f4);font-weight:600}
        .columns{display:grid;grid-template-columns:minmax(320px,1fr) minmax(360px,1fr);gap:22px}.card{background:var(--card-background-color,#1c232d);border:1px solid var(--divider-color,#3c4652);border-radius:14px;padding:24px;min-width:0}.card h2{font-size:21px;margin:0 0 20px}.single{max-width:820px}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.field{display:flex;flex-direction:column;gap:7px;min-width:0;font-size:14px;font-weight:600}.field>span{color:var(--primary-text-color,#eee)}.field input:not([type=checkbox]),.field select,.field textarea,.create-row select{width:100%;background:var(--primary-background-color,#11151c);color:var(--primary-text-color,#fff);border:1px solid var(--divider-color,#4d5866);border-radius:7px;padding:10px;min-height:42px}.field input:disabled{opacity:.45;cursor:not-allowed}.field input:focus,.field select:focus,.field textarea:focus{outline:2px solid var(--primary-color,#03a9f4);outline-offset:1px}.field.toggle{flex-direction:row;align-items:center;justify-content:space-between;gap:14px;padding:12px;border:1px solid var(--divider-color,#4d5866);border-radius:7px}.field.toggle input{width:20px;height:20px}.field.invalid input,.field.invalid select{border-color:var(--error-color,#f66)}.field-error{color:var(--error-color,#f66);font-weight:400}.form-actions{display:flex;justify-content:flex-end;margin-top:24px}.muted,.empty{color:var(--secondary-text-color,#aeb6c2);font-size:14px}.empty{padding:16px 0}.notice,.alert{padding:13px 16px;border-radius:8px;margin-bottom:20px;background:var(--secondary-background-color,#26374b)}.alert.error{border-left:4px solid var(--error-color,#f66)}.alert.success{border-left:4px solid var(--success-color,#46be87)}
        .create-row{display:flex;gap:10px;margin:18px 0}.create-row select{flex:1}.profile-list{display:grid;gap:10px}.profile-row{border:1px solid var(--divider-color,#45505e);border-radius:9px;padding:15px;display:flex;gap:12px;align-items:center;justify-content:space-between}.profile-row strong{display:block;margin-bottom:5px}.row-actions{display:flex;gap:6px;flex-shrink:0}.row-actions button{padding:7px 9px}
        @media(max-width:900px){.columns{grid-template-columns:1fr}.wrap{padding:18px}.fields{grid-template-columns:1fr}.head{flex-wrap:wrap}}@media(max-width:600px){.profile-row{align-items:flex-start;flex-direction:column}.row-actions{align-self:flex-end}.create-row{flex-direction:column}}
      </style>
      <div class="wrap"><header class="head">${this._narrow ? '<button class="menu-toggle" type="button" aria-label="Open Home Assistant menu">☰</button>' : ""}<a class="back" href="/config/integrations">← Integrations</a><div><h1>SolaX Developer API settings</h1><p>Choose a section to review or change. Saving reloads the integration.</p></div></header>
      <nav aria-label="Settings sections">${TABS.map(([id,label]) => `<button type="button" data-tab="${id}" class="${this._tab === id ? "active" : ""}">${escapeHtml(label)}</button>`).join("")}</nav>
      ${this._error ? `<div class="alert error" role="alert">${escapeHtml(this._error)}</div>` : ""}
      ${this._success ? `<div class="alert success" role="status">${escapeHtml(this._success)}</div>` : ""}
      ${this._busy ? '<p class="muted">Working…</p>' : ""}${body}
    </div>`;
    for (const button of this.shadowRoot.querySelectorAll("[data-tab]")) {
      button.addEventListener("click", () => void this._openSection(button.dataset.tab));
    }
    this.shadowRoot.querySelector(".menu-toggle")?.addEventListener("click", () => {
      this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
    });
    this.shadowRoot.querySelector("#settings-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      void this._save(event.currentTarget);
    });
    const settingsForm = this.shadowRoot.querySelector("#settings-form");
    if (settingsForm) {
      this._syncScheduleFields(settingsForm);
      for (const name of ["schedule_enabled", "enable_time_period2"]) {
        settingsForm.elements.namedItem(name)?.addEventListener("change", () => {
          this._syncScheduleFields(settingsForm);
        });
      }
    }
    this.shadowRoot.querySelector("#inverter-choice")?.addEventListener("change", (event) => {
      this._selectedSerial = event.currentTarget.value;
      this._editing = null;
      this._form = null;
      const selected = this._entry.inverters.find((item) => item.serial === this._selectedSerial);
      if (selected && !selected.modes.includes(this._selectedMode)) {
        this._selectedMode = selected.modes[0];
      }
      this._render();
    });
    this.shadowRoot.querySelector("#mode-choice")?.addEventListener("change", (event) => {
      this._selectedMode = event.currentTarget.value;
    });
    this.shadowRoot.querySelector("#create-profile")?.addEventListener("click", () => {
      void this._openProfile(this._selectedMode);
    });
    const inverter = this._entry?.inverters.find((item) => item.serial === this._selectedSerial);
    inverter?.profiles.forEach((profile, index) => {
      this.shadowRoot.querySelector(`[data-edit="${index}"]`)?.addEventListener("click", () => void this._openProfile(profile.mode, profile.id));
      this.shadowRoot.querySelector(`[data-delete="${index}"]`)?.addEventListener("click", () => void this._deleteProfile(profile));
    });
  }
}

if (!customElements.get("solax-developer-settings-panel")) {
  customElements.define("solax-developer-settings-panel", SolaxDeveloperSettingsPanel);
}
