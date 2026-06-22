# SolaX Developer API for Home Assistant

<img src="https://raw.githubusercontent.com/NoUsername10/Solax-Developer-API-for-Home-assistant/main/assets/icon.png" width="40%" height="40%" alt="SolaX Developer API icon">

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-donate-orange.svg)](https://www.buymeacoffee.com/DefaultLogin)

[<img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant instance and add this repository to HACS">](https://my.home-assistant.io/redirect/hacs_repository/?owner=NoUsername10&repository=Solax-Developer-API-for-Home-assistant&category=integration)

**SolaX Developer API** integration for Home Assistant using the official **SolaX Developer OpenAPI**.
It authenticates with a Developer Portal `client_id` and `client_secret`, automatically discovers authorized plants and devices, and creates entities dynamically from the data your system actually returns.

The integration supports residential and commercial/industrial systems, including inverters, batteries, meters, EV chargers, and confirmed EMS systems.

> [!IMPORTANT]
> All control services are currently **hard-blocked dry-runs**. Payloads are validated and audited, but no write request is sent to SolaX.

## ✨ Features in short

- **Automatic discovery** of all authorized residential and C&I plants and devices
- **Dynamic sensors** based on real API fields and observed device capabilities
- **Inverter, battery, meter, EV charger, and EMS support**
- **Plant data, alarms, statistics, device telemetry, and system totals**
- **Manual meter and EMS onboarding** when inventory endpoints omit an accessible device
- **Standard, night, and temporary Live View polling profiles**
- **Automatic token renewal and official Home Assistant reauthentication**
- **Rate-limit protection, retry backoff, Repairs, and stale-data retention**
- **Privacy-safe diagnostics** with raw and filtered API response views
- **No YAML required**
- **English, Spanish, and Swedish**
  - 🇬🇧 🇪🇸 🇸🇪
- **No dependency on another integration**

This integration is developed and tested against real SolaX Developer API responses and Home Assistant installations.
Contributions, issues, and pull requests are welcome.

<!-- Future screenshot locations remain invisible until matching Developer API assets are published. -->
<!-- Screenshot: assets/developer-system-overview.png -->
<!-- Screenshot: assets/developer-inverter-device.png -->
<!-- Screenshot: assets/developer-meter-device.png -->
<!-- Screenshot: assets/developer-plant-statistics.png -->
<!-- Screenshot: assets/developer-live-view.png -->
<!-- Screenshot: assets/developer-diagnostics.png -->

## ✨ Full Feature Set

<details>
<summary><b>Complete feature summary</b></summary><br>

- **Single Integration Instance** - One config entry covers every plant and device authorized for the Developer API application.
- **Developer API Authentication** - Uses OAuth client credentials with automatic access-token renewal.
- **Official Reauthentication** - Home Assistant starts a reauthentication flow when SolaX rejects stored credentials.
- **Residential and C&I Discovery** - Queries both `businessType=1` and `businessType=4`.
- **All Main Device Families** - Inverters, batteries, meters, EV chargers, and confirmed EMS systems.
- **Dynamic Sensor Creation** - Creates sensors from non-null fields returned by the API.
- **Capability Memory** - Remembers previously observed device fields so temporarily offline devices retain their entity model.
- **Unavailable-Sensor Filtering** - Capability-only fields start disabled and are automatically enabled if real data later appears.
- **Plant Telemetry** - Realtime plant values, inventory metadata, alarms, and annual/monthly statistics.
- **Device Telemetry** - Realtime device values grouped and batched by device type, business type, and serial number.
- **System Totals Device** - AC/DC power, yield, efficiency, health, polling, Live View, and API diagnostics.
- **Transparent Calculations** - Total sensors expose attributes showing which devices or plants contributed.
- **Manual Meter Support** - Validates accessible meters that are missing from device inventory before saving them.
- **Manual EMS Support** - Available for relevant C&I systems and validated through the dedicated EMS endpoint.
- **Duplicate Protection** - Already discovered devices are not added again as manual devices.
- **Adaptive Polling** - Standard, night, and temporary realtime-focused Live View profiles.
- **API Budget Protection** - Live View automatically increases its effective interval when necessary to stay within its configured call budget.
- **Transient Error Retention** - Last good values remain available during temporary API, network, rate-limit, or quota failures.
- **Deterministic Retry Backoff** - Failed refresh cycles back off instead of repeatedly hammering the API.
- **Home Assistant Repairs** - Surfaces active rate/quota limits and incomplete endpoint permissions.
- **Capability-Gated Services** - Device-specific services are registered only when matching equipment is present.
- **On-Demand History Reads** - Device history requests are split into API-safe serial and time-range chunks.
- **Built-in Live View Controller** - Optional Lovelace card renews Live View while its dashboard view is open.
- **Official Diagnostics Export** - Includes raw API envelopes, filtered entity-driving data, and raw-versus-filtered field summaries.
- **Privacy Redaction** - Credentials, tokens, serials, plant identity, account identity, address, and coordinates are sanitized.
- **Full Translation Layer** - English (`en`), Spanish (`es`), and Swedish (`sv`), with English fallback.
- **Hard Dry-Run Controls** - Control payloads use schema validation, auditing, and event output without any outbound write request.

</details>

## ✅ Prerequisites (Step 1)

Before installation, you need:

1. **Home Assistant 2025.1.0 or newer**
2. **SolaX Developer Portal access**
   - [SolaX Developer Portal](https://developer.solaxcloud.com/home)
3. **A Developer API application**
   - Obtain its **Client ID** and **Client Secret**.
4. **Authorized plants and devices**
   - Your Developer API application must have permission to read the relevant SolaX plants.
5. **The correct API region**
   - EU: `openapi-eu.solaxcloud.com`
   - CN: `openapi-cn.solaxcloud.com`

The integration validates both authentication and read access during setup. A token alone is not considered a successful configuration unless at least one plant-information request succeeds.

## 📦 Installation with HACS (Step 2)

[<img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant instance and add this repository to HACS">](https://my.home-assistant.io/redirect/hacs_repository/?owner=NoUsername10&repository=Solax-Developer-API-for-Home-assistant&category=integration)

This repository is installed as a **HACS custom repository**:

1. Open **HACS** in Home Assistant.
2. Open the top-right menu and select **Custom repositories**.
3. Add:
   - Repository: `https://github.com/NoUsername10/Solax-Developer-API-for-Home-assistant`
   - Category: **Integration**
4. Search for and install **SolaX Developer API for Home Assistant**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration**.
7. Search for **SolaX Developer API**.

### Manual Installation

1. Download the [latest release](https://github.com/NoUsername10/Solax-Developer-API-for-Home-assistant/releases/latest).
2. Extract `solax_developer_api.zip`.
3. Create `/config/custom_components/solax_developer_api` if it does not exist.
4. Copy the extracted archive contents directly into that directory so `manifest.json` is located at `/config/custom_components/solax_developer_api/manifest.json`.
5. Restart Home Assistant.
6. Add **SolaX Developer API** from **Settings → Devices & services**.

## ⚙️ Configuration (Step 3)

### 🚀 Initial Setup

1. Go to **Settings → Devices & services**.
2. Click **Add integration**.
3. Search for **SolaX Developer API**.
4. Enter:
   - **Client ID** - From the SolaX Developer Portal application.
   - **Client Secret** - From the same application.
   - **System Name** - Used for the System Totals device and stable entity prefix.
   - **Scan Interval** - Standard polling interval in seconds. Default: `120`.
   - **API Region** - EU or CN.
5. Submit the form.

The integration obtains an access token, verifies plant read access, then discovers all authorized plants and devices automatically.

### 🧩 Integration Options

Open the integration and click **Configure**. Settings are organized into four pages:

#### Credentials and system

- Client ID
- Client Secret
- API region
- System name

Changed credentials are validated before they are saved.

#### Polling and Live View

- Standard scan interval
- Live View default duration
- Live View target interval
- Live View call budget
- Night scan interval
- Night start and end hours

#### Manual devices

- Add or remove manual meter serials
- Add or remove manual EMS systems when relevant

#### Advanced and diagnostics

- Enable or disable rate-limit notifications

The integration reloads automatically after saved option changes.

### ➕ Manual Meters

Most devices are discovered automatically. Some meters can be queried by serial number even though SolaX does not return them from the regular device inventory endpoint.

To add one:

1. Open **Configure → Manual devices**.
2. Enter one meter serial per line.
3. Optionally add `|1` or `|4` to specify the business type.
4. Submit the form.

Examples:

```text
METER_SERIAL
METER_SERIAL|1
METER_SERIAL|4
```

Before saving, the integration:

- Checks whether the meter is already auto-discovered
- Tries the supported business types
- Requires matching realtime meter data
- Records the fields actually returned
- Prevents duplicate manual devices

Saved manual meters appear in the same options page and can be selected for removal.

### ➕ Manual EMS Systems

EMS discovery normally uses the C&I master-control relationship. If a compatible C&I account can read an EMS that is not discovered automatically, the options page can accept:

```text
EMS_SERIAL|PLANT_ID
```

The dedicated EMS attribute endpoint must validate the serial and plant before the system is saved.

EMS entities and controls remain hidden until an EMS is confirmed. Manual EMS options are shown only for a relevant C&I plant or an existing manual EMS entry, allowing an inventory-omitted EMS to be validated without exposing EMS settings to unrelated residential systems.

## 📝 API and Polling Behavior

| Setting | Default | Supported range |
|---|---:|---:|
| Standard scan interval | 120 seconds | 60-3600 seconds |
| Live View duration | 300 seconds | 30-3600 seconds |
| Live View target interval | 5 seconds | 2-60 seconds |
| Live View call budget | 20 calls/minute | 5-100 calls/minute |
| Night scan interval | 600 seconds | 120-7200 seconds |
| Night period | 23:00-06:00 | Configurable |

Important behavior:

- **Developer API limit** - The documented account limit is 100 calls per minute.
- **Budget-first Live View** - The effective interval can be slower than requested when the current plant/device topology would exceed the selected call budget.
- **Realtime-focused Live View** - Heavy inventory, statistics, and alarm paths are skipped during temporary Live View polling.
- **Night throttling** - The slower night profile is selected during the configured local hours.
- **Automatic token renewal** - Tokens are renewed before expiry, using a 24-hour safety target for long-lived tokens.
- **Auth retry** - An API authentication rejection triggers one forced token refresh before failing.
- **Stale-data retention** - Existing values are kept during temporary failures.
- **Official update failure state** - A cycle with no fresh endpoint data is reported to Home Assistant as a failed coordinator update.
- **Rate/quota recovery** - Temporary failures use deterministic backoff.

## 🔌 Supported Systems and Models

The integration supports all standard SolaX Developer API device types plus its own internal EMS classification:

| Type | Device family |
|---:|---|
| `1` | Inverter |
| `2` | Battery |
| `3` | Meter |
| `4` | EV charger |
| `100` | Internal integration type for EMS systems discovered through dedicated EMS/master-control endpoints |

Types `1`-`4` are API-native `deviceType` values. Type `100` is used internally so EMS devices returned by the dedicated EMS endpoints can participate consistently in Home Assistant device and capability handling.

Model names are resolved using the combination of business type, device type, and model code where the Developer API provides enough context.

<details>
<summary><b>Residential inverter model mappings</b></summary><br>

- X1-LX
- X-Hybrid
- X1-Hybrid-G3
- X1-Boost/Air/Mini
- X3-Hybrid-G1/G2
- X3-20K/30K
- X3-MIC/PRO
- X1-Smart
- X1-AC
- A1-Hybrid
- A1-FIT
- A1
- J1-ESS
- X3-Hybrid-G4
- X1-Hybrid-G4
- X3-MIC/PRO-G2
- X1-SPT
- X1-Boost-G4
- A1-HYB-G2
- A1-AC-G2
- A1-SMT-G2
- X1-Mini-G4
- X1-IES
- X3-IES
- X3-ULT
- X1-SMART-G2
- A1-Micro 1 in 1
- X1-Micro 2 in 1
- X1-Micro 4 in 1
- X1-Micro 4 in 1G2
- X1-Micro 2 in 1G2
- X3-AELIO
- X3-HYB-G4 PRO
- X3-NEO-LV
- X1-VAST
- X3-IES-P
- J3-ULT-LV-16.5K
- J3-ULT-30K
- J1-ESS-HB-2
- C3-IES
- X3-IES-A
- X1-IES-A
- X3-ULT-GLV
- X1-MINI-G4 PLUS
- X1-Reno-LV
- A1-HYB-G3
- X-MS 2700
- OG
- X1-SPT-10K/12K
- LVE
- AEGIS
- X3-AELIO (LA)
- X3-FTH
- X3-MGA-G2
- X1-Hybrid-LV
- X1-Lite-LV
- X3-GRAND-HV
- X3-FORTH-PLUS
- X3-MIC-G3
- X3-PRO-G3

</details>

<details>
<summary><b>Commercial and industrial inverter mappings</b></summary><br>

- X3-AELIO
- X3-TRENE-100KI
- X3-TRENE-100K
- X3-TRENE
- X3-PRO G2
- X3-FORTH
- X3-MEGA G2
- X3-GRAND
- X3-FORTH PLUS

</details>

<details>
<summary><b>Battery, meter, and EV charger mappings</b></summary><br>

**C&I batteries**

- TB-HR140
- TB-HR522
- TSYS-HS51
- TR-HR140

**Residential meters**

- Meter X
- M1-40
- M3-40
- M3-40-Dual
- M3-40-Wide

**C&I meters**

- CT
- DTSU666-CT
- UMG 103-CBM
- M3-40
- M3-40-Dual
- PRISMA-310A

**EV chargers**

- X1/X3-EVC
- X1/X3-EVC G1.1
- X1/X3-HAC
- J1-EVC
- A1-HAC
- C1/C3-HAC

</details>

An unknown model code does not prevent device creation. The integration keeps the raw code available for diagnostics and can still build sensors from returned telemetry.

## 📊 Sensor Information

### System Totals

The System Totals device always provides:

- `System AC Power`
- `System DC Power`
- `System Yield Today`
- `System Yield Lifetime`
- `System Total Efficiency`
- `System Health`
- `API Rate Limit Status`
- `Poll Profile`
- `Effective Scan Interval`
- `Live View State`
- `Live View Remaining`
- `Last Poll Attempt` (diagnostic, disabled by default)
- `Next Scheduled Poll` (diagnostic, disabled by default)
- `Token Expires At`
- `Dry-Run Command Count`

Calculation attributes explain what is included:

- AC and DC power totals include inverter realtime data only.
- Non-inverter devices, including grid meters, are listed as excluded from inverter power totals.
- Yield totals aggregate plant realtime `dailyYield` and `totalYield`.
- Efficiency is `System AC Power / System DC Power × 100`.
- If AC and DC power are both zero, efficiency is reported as `0%`.

### Dynamic Device Sensors

Device sensors are generated from non-null fields returned for each device. Depending on hardware and account permissions, these can include:

- AC active, reactive, and apparent power
- DC, PV, and MPPT power/current/voltage
- Yield and energy totals
- Battery SOC, power, current, voltage, temperature, and status
- Meter import/export energy and active power
- Grid frequency, voltage, current, and power factor
- EPS/backup values
- EV charger state, charging power, current, and session values
- EMS system summary fields
- Device status, working mode, timestamps, and firmware/inventory metadata

Inverter friendly names omit the redundant `Inverter` prefix. Entity IDs retain device context and place the serial at the end:

```text
sensor.<system>_<field>_device_<serial>
sensor.<system>_<field>_info_device_<serial>
```

### Offline and Unsupported Fields

- Fields that have produced real non-null data are remembered as device capabilities.
- A temporarily offline device can retain its known entities even when the current poll has no telemetry.
- Capability-only fields are created disabled by default.
- If a field later returns real data, an entity disabled by the integration is automatically enabled.
- User-disabled entities are never automatically re-enabled.
- Inventory diagnostics are generally disabled by default to avoid UI clutter.

### Plant Devices

Each plant can expose:

- Realtime plant fields
- Active alarm count
- Up to three alarm previews
- Annual and monthly statistics
- Plant inventory diagnostics

Available plant statistics are generated dynamically from API data rather than from a fixed universal sensor list.

## 🔍 Read Services

Universal polling services are always registered. Capability-specific read services appear only when the loaded system supports them:

- `solax_developer_api.manual_refresh`
- `solax_developer_api.start_live_view`
- `solax_developer_api.stop_live_view`
- `solax_developer_api.fetch_device_history`
- `solax_developer_api.query_request_result`
- `solax_developer_api.query_master_control_device`

### Manual Refresh

```yaml
action: solax_developer_api.manual_refresh
data: {}
```

Use the optional `entry_id` field to target a specific config entry.

### Device History

`fetch_device_history` is an on-demand read service. It:

- Accepts 1-200 serial numbers
- Splits serials into API batches
- Splits long time ranges into safe windows
- Merges and deduplicates returned history rows
- Caches the latest result for diagnostics

Required service fields:

- `sn_list`
- `device_type`
- `business_type`
- `start_time`
- `end_time`
- `time_interval`

All Home Assistant service fields use `snake_case`.

## 🛡️ Dry-Run Control Services

Control services are registered only when compatible equipment is present.

<details>
<summary><b>Available control families</b></summary><br>

**Grid and strategy**

- `solax_developer_api.set_export_control`
- `solax_developer_api.set_import_control`

**Inverter work modes**

- `solax_developer_api.batch_set_spontaneity_self_use`
- `solax_developer_api.batch_set_on_grid_first`
- `solax_developer_api.batch_set_peace_mode`
- `solax_developer_api.batch_set_manual_mode`
- `solax_developer_api.self_use_mode`
- `solax_developer_api.feed_in_priority`
- `solax_developer_api.back_up_mode`
- `solax_developer_api.demand_mode`
- `solax_developer_api.const_power_mode`

**VPP**

- `solax_developer_api.exit_vpp_mode`
- `solax_developer_api.power_control_mode`
- `solax_developer_api.electric_quantity_target_control_mode`
- `solax_developer_api.soc_target_control_mode`
- `solax_developer_api.push_power_positive_or_negative_mode`
- `solax_developer_api.push_power_zero_mode`
- `solax_developer_api.self_consume_charge_or_discharge_mode`
- `solax_developer_api.self_consume_charge_only_mode`
- `solax_developer_api.pv_and_bat_individual_setting_duration_mode`
- `solax_developer_api.pv_and_bat_individual_setting_target_soc_mode`

**EV charger**

- `solax_developer_api.set_charge_scene`
- `solax_developer_api.set_evc_qr_code`
- `solax_developer_api.set_evc_work_mode`
- `solax_developer_api.set_evc_start_mode`
- `solax_developer_api.set_evc_charge_command`
- `solax_developer_api.set_evc_reserve_charge`
- `solax_developer_api.set_evc_current_limit`

**Battery and EMS**

- `solax_developer_api.set_battery_heating`
- `solax_developer_api.set_ems_manual_mode`

</details>

Every dry-run service:

1. Accepts documented `snake_case` Home Assistant fields.
2. Validates required fields, types, values, time formats, ranges, and serial limits.
3. Converts validated fields to SolaX API-native names internally.
4. Records a sanitized audit event.
5. Returns a blocked dry-run result.
6. Sends **no outbound write request**.

## ⚡ Built-in Card-Aware Live View

The integration includes a lightweight Lovelace controller card that renews Live View while the card is mounted. When the dashboard view closes, the heartbeat stops and Live View expires automatically.

### Add the resource

- URL: `/api/solax_developer_api/frontend/solax-live-view-controller.js`
- Type: `module`

### Add the card

```yaml
type: custom:solax-live-view-controller
entry_id: YOUR_CONFIG_ENTRY_ID   # optional
duration_seconds: 120            # optional
heartbeat_seconds: 45            # optional
interval_seconds: 5              # optional target
```

No `browser_mod` or other integration is required.

The requested interval is a target. The integration can automatically select a slower effective interval to protect the configured API call budget.

## 🩺 Diagnostics and Privacy

### Download diagnostics

1. Go to **Settings → Devices & services**.
2. Open **SolaX Developer API**.
3. Open the top-right menu (`⋮`).
4. Select **Download diagnostics**.
5. Attach the JSON file when opening a GitHub issue.

The diagnostics payload includes:

- Config-entry and polling metadata
- Coordinator health and refresh timing
- Latest raw API endpoint envelopes
- Filtered data used by entities
- Raw-versus-filtered field comparisons
- Manual-device and capability summaries
- Cached on-demand read results
- Collection issues encountered while building diagnostics

Privacy handling:

- Client ID, client secret, authorization headers, and tokens are partially masked.
- Secret presence and length metadata are included without exposing the full value.
- Serial numbers have a six-character middle segment replaced with `***`.
- Plant ID, plant name, login name, plant address, longitude, and latitude are replaced with `*REDACTED*`.
- `token_expires_at` remains visible because it contains no credential value.
- Redaction is recursive across raw responses, filtered data, summaries, and cached results.

If the integration has no meaningful coordinator state, diagnostics attempts a safe one-time read-only probe and reports any probe errors without failing the download.

## 🛠️ Troubleshooting

### Cannot complete setup

- Verify the Client ID and Client Secret in the SolaX Developer Portal.
- Confirm that the selected EU/CN region matches the application.
- Confirm that the application has at least one authorized plant.
- Token success without a successful plant read is rejected intentionally.

### Authentication failed after setup

Home Assistant starts the official reauthentication flow. Open the integration repair/configuration prompt and enter current credentials.

### Rate-limit or quota warnings

- Increase the standard scan interval.
- Reduce Live View duration or call budget.
- Allow the deterministic backoff period to complete.
- Check **Settings → System → Repairs**.
- Check the `API Rate Limit Status` sensor.

The integration retains previous values while recovery is in progress.

### A device is offline at night

Known device capabilities are cached. An inverter that stops uploading overnight can retain its existing entities instead of being rediscovered from an empty realtime response.

Current states can be unavailable until SolaX returns fresh data, but a temporary API failure does not erase the last successful coordinator model.

### A meter is missing

Some readable meters are not returned by `page_device_info`.

1. Open **Configure → Manual devices**.
2. Add the exact meter serial.
3. Let the integration validate realtime access.

After restart, the saved manual meter remains part of inventory polling and appears as its own Energy Meter device.

### Manual device disappears after restart

- Confirm the device still appears under **Configure → Manual devices**.
- Download diagnostics and inspect `manual_meter_config_present` or the manual-device summary.
- Recheck that the API still returns matching realtime data for the saved serial.

### No EMS entities or settings

That is expected when the account has no confirmed EMS. EMS discovery, entities, and controls are capability-driven and hidden when irrelevant. Manual EMS onboarding is offered only for a relevant C&I plant or an existing manual EMS entry.

### Missing or disabled sensors

- The API returns different fields for different models and system configurations.
- Null-only or unsupported fields are not enabled by default.
- Three-phase, battery, EPS, meter, and EV fields appear only when the system returns them.
- If an integration-disabled capability field later receives real data, it is automatically enabled.

### Need an immediate refresh

Call:

```yaml
action: solax_developer_api.manual_refresh
data: {}
```

### Need to report a problem

Download diagnostics and open an issue:

[GitHub Issues](https://github.com/NoUsername10/Solax-Developer-API-for-Home-assistant/issues)

Never post unredacted credentials or Developer Portal secrets.

## 🌍 Translation Support

Included languages:

- English (`en`) - default and fallback
- Spanish (`es`)
- Swedish (`sv`)

The official Home Assistant translation files and runtime translation catalogs are validated for key and placeholder parity.

## 🏷️ Brand Assets

The integration ships local SolaX icon and logo assets for Home Assistant.

On Home Assistant versions that support the Brands Proxy API, they are served through:

- `/api/brands/integration/solax_developer_api/icon`
- `/api/brands/integration/solax_developer_api/logo`

The repository also includes `assets/icon.png` for this README and HACS presentation.

## 🤝 Contributing

Found a bug or have a feature request?

- [Open an issue](https://github.com/NoUsername10/Solax-Developer-API-for-Home-assistant/issues)
- [Open a pull request](https://github.com/NoUsername10/Solax-Developer-API-for-Home-assistant/pulls)

Contributions for additional tested device fields, model mappings, translations, and Developer API account variants are welcome.

When reporting API differences, include privacy-redacted diagnostics and describe the device family, business type, and API region.

## 📄 License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

## ⚠️ Disclaimer

This integration is not officially affiliated with SolaX Power.

Cloud data availability, update frequency, endpoint permissions, and API limits are controlled by SolaX. Use the integration and all future control functionality at your own risk.

## 🚧 Project Status

- **Read functionality:** Active
- **Automatic discovery:** Active
- **Manual meter/EMS validation:** Active
- **Diagnostics and Repairs:** Active
- **Live View:** Active
- **Control functionality:** Integrated as hard-blocked dry-run only
- **Outbound write requests:** Disabled
- **Callback URL async push processing:** Deferred

---

This integration is designed to provide a robust, transparent, and privacy-conscious Home Assistant interface for the official SolaX Developer API.
