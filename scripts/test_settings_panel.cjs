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

test("time validation catches incomplete and overlapping periods", () => {
  assert.equal(validatePeriods({ schedule_enabled: false }).schedule_enabled, undefined);
  assert.match(
    validatePeriods({ schedule_enabled: true, charge_start_time_period1: "22:00" })
      .charge_end_time_period1,
    /both/,
  );
  assert.match(
    validatePeriods({
      schedule_enabled: true,
      charge_start_time_period1: "22:00",
      charge_end_time_period1: "06:00",
      discharge_start_time_period1: "05:00",
      discharge_end_time_period1: "07:00",
    }).discharge_start_time_period1,
    /overlaps/,
  );
  assert.equal(
    Object.keys(validatePeriods({
      schedule_enabled: true,
      charge_start_time_period1: "22:00",
      charge_end_time_period1: "06:00",
      discharge_start_time_period1: "13:00",
      discharge_end_time_period1: "15:00",
    })).length,
    0,
  );
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
