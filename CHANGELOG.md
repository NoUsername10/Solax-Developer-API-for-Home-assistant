# Changelog

All notable changes to this project will be documented in this file.

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
