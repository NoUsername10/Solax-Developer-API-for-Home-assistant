# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

_No unreleased changes._

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
