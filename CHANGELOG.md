# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [v0.4.5] - 2026-09-03

### Fixed
- Added automatic support for batteries that SolaX lists without a battery
  serial. The integration now associates an unambiguous battery with its
  inverter and queries battery realtime data using `deviceType=2` and
  `requestSnType=1` as documented by SolaX.
- Serial-less battery sensors are attached to their inverter device, while
  batteries that have their own serial continue to appear as separate Home
  Assistant devices. Failed proxy reads retain the last successful battery
  values.

## [v0.4.4] - 2026-08-31

### Added
- Automatically register the bundled Live View, History Viewer, and Alarm
  Viewer modules with the Home Assistant frontend so all three cards appear in
  the dashboard card picker without manual resource configuration.

### Changed
- Promoted the dashboard cards directly below the installation guide with
  visible previews and collapsible, non-duplicated configuration details.
- Added native SolaX alarm monitoring and Home Assistant persistent
  notifications to the README feature summary.
- Clarified that the integration currently supports one configured Developer
  API account and removed unnecessary multi-entry guidance from card examples.

## [v0.4.3] - 2026-08-27

### Fixed
- Raised the minimum supported Home Assistant version to `2026.1.0`, matching
  the native `async_register_admin_service` response-support API used by the
  administrator-only EV charger services. This removes the setup failure that
  affected EV charger accounts on the previously declared older version range.
- Moved frontend asset path resolution and existence checks into Home
  Assistant's executor so integration setup performs no blocking filesystem
  calls on the event loop.
- Updated lifecycle registry assertions to use Home Assistant's
  config-entry-aware device listing API instead of the deprecated global
  identifier lookup.

### Changed
- Removed the obsolete local `StaticPathConfig` compatibility shim and now use
  Home Assistant's public HTTP API directly.
- Removed the redundant repository-root brand assets. The installed icon and
  logo remain under `custom_components/solax_developer_api/brand/`, and the
  README presentation icon remains under `assets/`.
- Updated CI to validate both Home Assistant `2026.1.0` and current stable,
  including lifecycle fixture coverage at both supported boundaries.
- Constrained lifecycle fixture installation to the Home Assistant version
  already present in each CI container, preventing the fixture resolver from
  silently upgrading minimum/stable jobs to a newer beta release.

## [v0.4.2] - 2026-08-21

### Security
- Restricted the seven direct EV charger hardware-control services to Home
  Assistant administrators. Native EV charger buttons, selects, and numbers
  remain available to non-admin users according to Home Assistant's entity
  control permissions.
- Applied the administrator check before payload validation, dry-run handling,
  or any SolaX request so unknown and non-admin callers cannot use the direct
  EV service family.

### Changed
- Replaced the external `async-timeout` helper with Python's built-in
  `asyncio.timeout` while preserving timeout error classification.
- Removed `aiohttp` and `async-timeout` from integration requirements because
  Home Assistant provides the shared HTTP client and runtime packages.
- Retained the intentional 10-second Live View minimum. Live View remains an
  explicit, time-limited, API-budget-protected mode that automatically returns
  to normal polling.
- Expanded authorization and timeout coverage to `211` credential-free tests
  plus `7` Home Assistant lifecycle fixture tests, with `97.17%` measured
  stable coverage.

## [v0.4.1] - 2026-08-09

### Fixed
- Prevented independent alarm-state updates from cancelling and restarting the
  main realtime coordinator timer. This fixes intermittent polling starvation
  after the night profile changes the realtime interval to 600 seconds.
- Alarm-only state merges no longer mark a failed main coordinator as recovered;
  they retain their own success and error state independently.
- Updated static frontend path registration to use Home Assistant's current
  typed HTTP module while preserving runtime compatibility with Home Assistant
  2025.1.0.

### Changed
- Added polling-profile transition logs with the previous/new profile and
  interval, plus the latest alarm-state merge timestamp in diagnostics.
- Raised the Live View default and minimum polling interval to 10 seconds so
  calls are not spent faster than SolaX supplies useful realtime updates.

## [v0.4.0] - 2026-08-02

### Added
- Added a Home Assistant stable strict-mypy CI gate covering all integration
  modules against Home Assistant's current typed interfaces.
- Added focused Home Assistant lifecycle tests for config-entry setup,
  discovery, registries, options reloads, manual devices, stale-data retention,
  alarm notifications, diagnostics, and unload cleanup.
- The validation suite passes `207` credential-free tests plus `5` Home
  Assistant lifecycle fixture tests with `97.08%` measured stable coverage.
- Added a per-production-module coverage gate requiring more than `95%`
  coverage in every integration module, alongside the `96%` total CI floor.
- Added a separate System Totals `Device Connectivity` diagnostic sensor with
  per-device online, offline, stale, and unknown attribution.
- Added an independent active-alarm coordinator with a configurable
  `60`-`3600` second interval (`120` seconds by default). Alarm monitoring now
  continues during night and Live View polling and reserves its estimated calls
  in the Live View API budget.
- Added alarm scheduling, partial-failure retention, inventory-change, options
  reload, diagnostics metadata, and Live View budget tests.

### Changed
- Completed explicit typing for config flows, services, coordinators, API
  responses, diagnostics, and all entity platforms. The integration now meets
  every declared Platinum Quality Scale rule and is documented as
  Platinum-standard aligned.
- Extracted History, Alarm, and Live View behavior into focused internal
  managers while preserving the existing coordinator, entity, cache, and
  service contracts.
- Moved History, Alarm Viewer, cancellation, and Live View service adapters out
  of the integration setup module.
- Audited the Home Assistant and runtime catalogs for all 26 supported locales,
  including natural translations for all bundled Lovelace cards while
  preserving technical API terms and English fallback behavior.
- EV charger execution results now distinguish initial API acceptance from
  SolaX device acknowledgement. Request-result polling reports documented
  failure, acknowledgement, or pending/unconfirmed state without claiming
  physical charging completion.

### Fixed
- Business Type and Device Type sensors now show the translated SolaX appendix
  meaning together with the original API code, including realtime and inventory
  entities for manually added meters and EMS devices. Unknown codes remain
  explicit and the original raw value is retained in entity attributes.
- Fully redacted EV charger OCPP URLs, charger IDs, and QR access values from
  nested diagnostics payloads.
- Plant realtime, alarm, and statistics refreshes now retain each endpoint's
  last-good data independently when temporary API calls fail, while successful
  empty responses remain authoritative.
- Diagnostics now read migrated system-name and scan-interval settings from
  the canonical options-first configuration path.
- System Health now represents operational health from documented inverter,
  battery, and EV charger fault states plus active alarms. Normal Waiting,
  Idle, and Standby modes no longer make the system appear degraded; cloud
  connectivity is reported independently by Device Connectivity.
- Preserved defensive reconstruction of coordinator locks, EV charger staged
  state, and malformed capability/error cache handling while making those
  paths strictly typed.
- Alarm state now merges under a dedicated lock, retains last-good per-plant
  data after temporary failures, and accepts a successful zero-alarm response
  as authoritative without replacing unrelated coordinator state.

## [v0.3.3] - 2026-06-28

### Added
- Added optional SolaX alarm persistent notifications, enabled by default,
  with active-alarm summaries, up to three returned alarm details, and a
  cleared message when SolaX returns to zero active alarms.
- Added focused notification tests; the Home Assistant stable validation run
  now passes `161` credential-free tests with `95.80%` measured coverage.

### Fixed
- Alarm Viewer Lovelace card now uses light/dark-safe Home Assistant theme
  surfaces and registers a card-picker preview like the other bundled cards.
- Alarm and History Viewer cards now share a tighter header/control style,
  styled native dropdowns, clearer subtitles, and cooperative fetch
  cancellation through the new `cancel_fetch` service.
- Alarm Viewer now defaults to ongoing alarms and moves the fetch button below
  the dropdown row to avoid clipped controls on narrower dashboard columns.
- Alarm Viewer header text is now grouped with the icon, matching the History
  Viewer alignment.
- Alarm Viewer now uses its own alert-style icon instead of reusing the
  History Viewer chart icon.

## [v0.3.1] - 2026-06-28

### Added
- Added a display-only SolaX alarm Lovelace card for manual ongoing/closed
  alarm lookup through `alarm/page_alarm_info`, including plant/device target
  selectors, API-call summaries, and expandable returned alarm fields.
- Added `solax_developer_api.list_alarm_targets` and
  `solax_developer_api.fetch_alarm_information` services for alarm-card
  metadata and paged manual alarm reads.
- Added a Device History chart-scale control with `Zero baseline` and
  `Auto zoom` modes, making stable values such as grid frequency easier to
  read without changing the fetched API data.
- Added focused helper and validation tests, raising the Home Assistant stable
  validation run to `157` credential-free tests with `96.07%` measured
  coverage.

### Fixed
- Alarm viewer rows now resolve `deviceType` and contextual `deviceModel`
  values through the Developer API appendix mappings instead of showing only
  raw numeric codes.
- History viewer Device History graphs no longer draw synthetic calculated
  total lines. Per-device rows are now grouped into clock-aligned requested
  intervals and summarized per device/field before charting, avoiding false
  zero-to-value jumps when inverter timestamps differ.
- Device history fetches now query one serial per request. Live Developer API
  validation showed multi-serial history calls return incomplete per-device
  rows, so serial-isolated reads are required for correct multi-inverter
  history graphs.

## [v0.3.0] - 2026-06-27

### Added
- Added opt-in real execution support for all seven SolaX Developer API EV
  charger control endpoints. EV commands remain dry-run blocked by default,
  require discovered EV charger targets, validate v34 enum/range rules, and
  store sanitized command response metadata including per-device status and
  request IDs when returned by SolaX.
- Added native Home Assistant EV charger device controls for discovered EV
  chargers, including command buttons, work/start/scene selects, current
  numbers, QR/OCPP text fields, and reserve-charge time fields. These controls
  use the same validated EV execution path as the service actions and remain
  unavailable until `EV Charger Controls` is enabled.
- Added a display-only SolaX history/statistics Lovelace card that manually
  fetches Developer API device history, yearly plant statistics, or monthly
  daily plant statistics and charts returned numeric fields without writing to
  Home Assistant Recorder or long-term statistics.
- Added `solax_developer_api.list_history_devices` to expose currently
  discovered inverter, battery, meter, and EV charger devices for history-card
  selectors without making an outbound SolaX API call.
- Added `solax_developer_api.list_plant_statistics_targets` and
  `solax_developer_api.fetch_plant_year_statistics` for display-only yearly
  plant-statistics graphs built from monthly plant statistic reads.
- Added `solax_developer_api.fetch_plant_month_statistics` for display-only
  month graphs built from daily plant statistic rows.
- Added tests for history device listing, manual meter inclusion, EMS exclusion,
  plant target listing, yearly/monthly plant statistics, empty loaded-entry
  handling, and service response wiring.
- Expanded EV charger control tests; the current Home Assistant stable
  validation run passes `150` credential-free tests with `95.72%` measured
  coverage.

### Changed
- History viewer now has separate Device History and Plant Statistics modes.
- Device History now supports multiple selected devices, auto-selects all
  inverters by default, and charts total selected devices plus optional
  per-device breakdown lines.
- Device History mode is capped at Week; Month/Year views now use Plant
  Statistics mode instead.
- Plant Statistics mode now supports Year and Month views, clickable month
  drilldown, and clickable day-to-device-history drilldown.
- History/statistics charts now include pointer/touch tooltips with visible
  series values.
- Device History ranges use automatic resolution: short ranges keep
  5-minute detail, day uses 15 minutes, 2-3 day ranges use 30 minutes, and
  week uses 60 minutes.
- Long history fetches are paced when the estimated API request count exceeds
  the safe threshold, protecting the SolaX 100-calls/minute limit while still
  supporting API-windowed long ranges.

### Fixed
- Fixed multi-inverter history chart totals by aligning device samples to the
  requested API interval grid before calculating total series.

### Documentation
- Documented the upgraded two-mode history/statistics card resource and YAML examples.
- Documented automatic device-history resolution, the SolaX 12-hour-per-request
  history window behavior, multi-device history selection, and plant-statistics
  year/month drilldown graphs.
- Updated current README validation numbers to `150` tests and `95.72%`
  measured coverage.

### Validation
- `150` credential-free tests pass in the Home Assistant stable container.
- Measured integration coverage is `95.72%`.

## [v0.2.2] - 2026-06-24

### Added
- Added a visible SolaX Live View Lovelace controller card with Home Assistant
  light/dark theme support.
- Added a compact/minimal Live View card mode using `minimal: true`.
- Added Live View regular and compact README preview assets under
  `assets/live-view/`.
- Added German, Dutch, Czech, Polish, Portuguese, Italian, French, Danish,
  Norwegian Bokmål, Finnish, Lithuanian, Simplified Chinese, Japanese, Thai,
  Vietnamese, Bulgarian, Greek, Hungarian, Romanian, Turkish, Ukrainian,
  Brazilian Portuguese, and Latin American Spanish translation catalogs for
  both the Home Assistant translation layer and the runtime translation layer.
- Expanded translation validation to cover all supported locales.
- Raised automated test coverage to `96.00%`.

### Changed
- The Live View card now displays status, remaining time, polling interval
  metadata, API-budget state, heartbeat status, and detected Live View entity
  instead of rendering as an invisible heartbeat-only helper.
- The Live View card registers `window.customCards` metadata when the frontend
  resource is loaded.
- The README now documents both regular and compact Live View card layouts.

### Fixed
- The Live View card custom element registration is guarded so browser reloads
  or duplicate resource loads do not throw an already-defined error.
- Runtime translation loading now preserves supported regional locale variants
  such as `pt-BR`, `es-419`, and `zh-Hans` instead of collapsing them to their
  base language.

### Validation
- `131` credential-free tests are documented for the current release.
- Measured integration coverage is `96.00%`.

## [v0.2.1] - 2026-06-24

### Fixed
- Switched HACS packaging to the standard GitHub source archive.
- Removed the custom zip release asset requirement.

## [v0.2.0] - 2026-06-23

### Added
- First stable release of the standalone SolaX Developer API integration.
- Client-credentials authentication with automatic token renewal and official
  Home Assistant reauthentication.
- Automatic discovery for residential and commercial/industrial plants,
  inverters, batteries, meters, EV chargers, and confirmed EMS systems.
- Manually validated meter and EMS onboarding for devices omitted by inventory
  endpoints.
- Dynamic plant/device sensors, system totals, diagnostics download, status
  mappings, and capability-aware entity creation.
- Standard, night, and temporary Live View polling profiles with API call
  budgeting.
- Device history, request-result, master-control, and manual-refresh read
  services.
- Capability-gated control services with complete payload validation.
- Home Assistant Repairs for active API limits and incomplete permissions.
- Focused options pages for credentials, polling, manual devices, and advanced
  diagnostics.
- Complete English, Spanish, and Swedish translation catalogs with English as
  the fallback language.
- Home Assistant and local brand assets.
- CI for Home Assistant `2025.1.0` and current stable, Hassfest, HACS
  validation, and tagged zip releases.
- Home Assistant Integration Quality Scale declaration targeting Gold,
  including runtime data, reconfiguration, stale-device handling, translated
  exceptions/icons, and shared entity modules.
- Public credential-free unit tests with an enforced coverage threshold above
  `95%`.

### Interface
- Config-entry schema version is `2`; connection credentials stay in config
  data while user-adjustable settings stay in options.
- The coordinator receives the Home Assistant config entry explicitly, matching
  current Home Assistant runtime requirements and avoiding the upcoming
  `2026.8` coordinator context break.
- Home Assistant service fields use snake_case exclusively.
- SolaX API-native camelCase is generated internally only when constructing
  validated API payloads.
- Minimum supported Home Assistant version is `2025.1.0`.
- HACS packaging uses the normal GitHub release/source archive; no custom
  `solax_developer_api.zip` release asset is required.

### Safety
- All write/control paths are hard-blocked dry-runs.
- No outbound write request is sent to SolaX.

### Validation
- `130` tests pass on both Home Assistant `2025.1.0` and current stable.
- Measured integration coverage is `95.85%`.
- Live Home Assistant runtime smoke test passed against the SolaX Developer API
  in the current stable Home Assistant container.
- Live read-only SolaX Developer API probe completed with `23` calls:
  `20` successful read responses, `1` plant, and `3` auto-discovered devices.
- `get_master_control_device` returned `10200` for three devices in the tested
  account, matching the no-capability/no-master-control case and not blocking
  setup or normal reads.
- Official Home Assistant Hassfest validation reports zero invalid
  integrations.
