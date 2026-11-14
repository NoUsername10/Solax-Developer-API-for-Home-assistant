"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../custom_components/solax_developer_api/frontend/solax-settings-panel.js"),
  "utf8",
);
const elements = new Map();
class Element {
  attachShadow() {
    this.shadowRoot = { querySelector: () => ({}) };
  }
}
const context = {
  HTMLElement: Element,
  customElements: {
    get: (name) => elements.get(name),
    define: (name, element) => elements.set(name, element),
  },
  window: {
    confirm: () => true,
    location: { search: "" },
  },
  URLSearchParams,
};
vm.runInNewContext(
  `${source}\nglobalThis.testExports = { validatePeriods, Panel: SolaxDeveloperSettingsPanel };`,
  context,
);
const { validatePeriods, Panel } = context.testExports;

test("time validation catches incomplete periods and allows overlaps", () => {
  assert.equal(validatePeriods({ schedule_enabled: false }).schedule_enabled, undefined);
  assert.match(
    validatePeriods({ schedule_enabled: true, charge_start_time_period1: "22:00" })
      .charge_end_time_period1,
    /both/,
  );
  assert.equal(
    Object.keys(validatePeriods({
      schedule_enabled: true,
      charge_start_time_period1: "22:00",
      charge_end_time_period1: "06:00",
      discharge_start_time_period1: "05:00",
      discharge_end_time_period1: "07:00",
    })).length,
    0,
  );
});

test("period 2 clocks stay disabled until enabled without clearing entered values", () => {
  const panel = new Panel();
  const controls = new Map([
    ["schedule_enabled", { checked: true }],
    ["enable_time_period2", { checked: false }],
  ]);
  for (const pair of [
    ["charge_start_time_period1", "charge_end_time_period1"],
    ["discharge_start_time_period1", "discharge_end_time_period1"],
    ["charge_start_time_period2", "charge_end_time_period2"],
    ["discharge_start_time_period2", "discharge_end_time_period2"],
  ]) {
    for (const name of pair) controls.set(name, { value: "13:00", disabled: false });
  }
  const form = { elements: { namedItem: (name) => controls.get(name) } };
  panel._syncScheduleFields(form);
  assert.equal(controls.get("charge_start_time_period1").disabled, false);
  assert.equal(controls.get("charge_start_time_period2").disabled, true);
  panel._form = { data_schema: [
    { name: "charge_start_time_period1", selector: { time: {} } },
    { name: "charge_start_time_period2", selector: { time: {} } },
  ] };
  assert.equal(panel._collectForm(form).charge_start_time_period2, undefined);
  assert.equal(panel._collectForm(form, true).charge_start_time_period2, "13:00");
  controls.get("enable_time_period2").checked = true;
  panel._syncScheduleFields(form);
  assert.equal(controls.get("charge_start_time_period2").disabled, false);
  assert.equal(controls.get("charge_start_time_period2").value, "13:00");
  controls.get("schedule_enabled").checked = false;
  panel._syncScheduleFields(form);
  assert.equal(controls.get("charge_start_time_period1").disabled, true);
  assert.equal(controls.get("charge_start_time_period2").disabled, true);
});

test("GUI keeps edited profile values when Home Assistant returns an error", async () => {
  const panel = new Panel();
  panel._render = () => {};
  panel._flow = "flow-1";
  panel._tab = "inverter_modes";
  panel._form = { type: "form", data_schema: [
    { name: "profile_name", required: true, selector: { text: {} } },
    { name: "min_soc", required: true, selector: { number: {} } },
  ] };
  panel._next = async () => ({
    type: "form",
    errors: { min_soc: "profile_invalid_soc" },
    step_id: "inverter_mode_settings",
    data_schema: panel._form.data_schema,
  });
  panel._hass = { localize: (key) => key.endsWith("profile_invalid_soc") ? "Enter a whole-number percentage from 0 to 100." : key.endsWith("min_soc") ? "Minimum SOC" : "" };
  const fields = new Map([
    ["profile_name", { value: "Cloudy draft" }],
    ["min_soc", { value: "35" }],
  ]);
  await panel._save({ elements: { namedItem: (name) => fields.get(name) } });
  assert.equal(panel._draftValues.profile_name, "Cloudy draft");
  assert.equal(panel._draftValues.min_soc, 35);
  assert.equal(panel._error, "Minimum SOC: Enter a whole-number percentage from 0 to 100.");
});

test("new device-control opt-ins require risk acknowledgement before saving", async () => {
  const panel = new Panel();
  panel._render = () => {};
  panel._flow = "flow-1";
  panel._tab = "advanced";
  panel._form = { type: "form", step_id: "advanced", data_schema: [
    { name: "ev_charger_controls_enabled", default: false, selector: { boolean: {} } },
    { name: "inverter_mode_controls_enabled", default: false, selector: { boolean: {} } },
  ] };
  const sent = [];
  panel._next = async (data) => {
    sent.push(data);
    return { type: "form", step_id: "advanced", errors: { base: "invalid" } };
  };
  const form = { elements: { namedItem: () => ({ checked: true }) } };
  await panel._save(form);
  assert.equal(sent.length, 0);
  assert.deepEqual(Array.from(panel._riskControls), ["EV charger controls", "inverter work-mode controls"]);
  assert.match(panel._renderRiskDialog(), /Use them at your own risk/);
  assert.match(panel._renderRiskDialog(), /risk-confirm[^>]*disabled/);
  await panel._confirmRisk();
  assert.equal(sent.length, 0);
  panel._cancelRisk();
  assert.equal(panel._draftValues.ev_charger_controls_enabled, true);
  assert.equal(sent.length, 0);
  await panel._save(form);
  panel._riskAccepted = true;
  await panel._confirmRisk();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].ev_charger_controls_enabled, true);
  assert.equal(sent[0].inverter_mode_controls_enabled, true);
});

test("already-enabled controls save without another acknowledgement", async () => {
  const panel = new Panel();
  panel._render = () => {};
  panel._flow = "flow-1";
  panel._tab = "advanced";
  panel._form = { type: "form", step_id: "advanced", data_schema: [
    { name: "ev_charger_controls_enabled", default: true, selector: { boolean: {} } },
    { name: "inverter_mode_controls_enabled", default: false, selector: { boolean: {} } },
  ] };
  let saved;
  panel._next = async (data) => {
    saved = data;
    return { type: "form", step_id: "advanced", errors: { base: "invalid" } };
  };
  const controls = new Map([
    ["ev_charger_controls_enabled", { checked: true }],
    ["inverter_mode_controls_enabled", { checked: false }],
  ]);
  await panel._save({ elements: { namedItem: (name) => controls.get(name) } });
  assert.equal(panel._pendingRiskData, null);
  assert.equal(saved.ev_charger_controls_enabled, true);
});

test("time periods have separate headings and full-width switches", () => {
  const panel = new Panel();
  panel._form = { type: "form", step_id: "inverter_mode_settings", data_schema: [
    { name: "schedule_enabled", selector: { boolean: {} } },
    { name: "charge_start_time_period1", selector: { time: {} } },
    { name: "enable_time_period2", selector: { boolean: {} } },
    { name: "charge_start_time_period2", selector: { time: {} } },
  ] };
  const markup = panel._renderForm();
  assert.ok(markup.indexOf("Time period 1") < markup.indexOf('name="schedule_enabled"'));
  assert.ok(markup.indexOf('name="charge_start_time_period1"') < markup.indexOf("Time period 2"));
  assert.ok(markup.indexOf("Time period 2") < markup.indexOf('name="enable_time_period2"'));
  assert.ok(markup.indexOf('name="enable_time_period2"') < markup.indexOf('name="charge_start_time_period2"'));
  assert.match(markup, /schedule-toggle/);
});

test("delete submits complete profile data through the options flow", async () => {
  const panel = new Panel();
  let sent;
  panel._render = () => {};
  panel._openProfile = async () => {
    panel._flow = "flow-1";
    panel._editing = { mode: "self_use", profileId: "profile-1" };
  };
  panel._collectForm = () => ({ profile_name: "Cloudy", min_soc: 20 });
  panel._next = async (data) => {
    sent = data;
    return { type: "create_entry" };
  };
  panel._refreshSnapshot = async () => {};
  await panel._deleteProfile({ mode: "self_use", id: "profile-1", name: "Cloudy" });
  assert.deepEqual(JSON.parse(JSON.stringify(sent)), {
    profile_name: "Cloudy",
    min_soc: 20,
    remove_profile: true,
  });
  assert.equal(panel._success, "Profile deleted.");
});

test("profile editor follows the existing Home Assistant options flow", async () => {
  const panel = new Panel();
  const sent = [];
  panel._render = () => {};
  panel._entry = { controls_enabled: true, entry_id: "entry-1" };
  panel._selectedSerial = "INV-1";
  panel._hass = {
    callApi: async (method, url, data) => {
      sent.push([method, url, data]);
      if (url === "config/config_entries/options/flow") {
        return { type: "menu", flow_id: "flow-1" };
      }
      if (data?.next_step_id === "classic") return { type: "menu" };
      return { type: "form", step_id: "inverter_mode_settings", data_schema: [] };
    },
  };
  await panel._openProfile("self_use", "profile-1");
  assert.deepEqual(JSON.parse(JSON.stringify(sent.map((call) => call[2]))), [
    { handler: "entry-1" },
    { next_step_id: "classic" },
    { next_step_id: "inverter_modes" },
    { inverter_serial: "INV-1" },
    { mode: "self_use" },
    { profile: "profile-1" },
  ]);
  assert.equal(panel._editing.profileId, "profile-1");
});

test("inverter selection resets unsupported mode", async () => {
  const panel = new Panel();
  panel._render = () => {};
  panel._selectedSerial = "A1";
  panel._selectedMode = "manual";
  panel._hass = {
    callWS: async () => ({
      entries: [{
        entry_id: "entry-1",
        inverters: [{ serial: "A1", modes: ["self_use", "back_up"], profiles: [] }],
      }],
    }),
  };
  await panel._refreshSnapshot();
  assert.equal(panel._selectedMode, "self_use");
});
