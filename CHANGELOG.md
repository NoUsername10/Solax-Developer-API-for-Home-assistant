# Changelog

All notable changes to this project will be documented in this file.

## [v0.1.0-beta.1] - 2026-06-22

### Added
- First beta release of the standalone SolaX Developer API integration.
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

### Interface
- Config-entry schema starts at version `1`.
- Home Assistant service fields use snake_case exclusively.
- SolaX API-native camelCase is generated internally only when constructing
  validated API payloads.
- Minimum supported Home Assistant version is `2025.1.0`.

### Safety
- All write/control paths are hard-blocked dry-runs.
- No outbound write request is sent to SolaX.

### Validation
- `72` tests pass on both Home Assistant `2025.1.0` and current stable.
- Official Home Assistant Hassfest validation reports zero invalid
  integrations.
