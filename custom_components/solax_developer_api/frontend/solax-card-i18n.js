const DEFAULT_LANGUAGE = "en";
const TRANSLATION_BASE = "/api/solax_developer_api/frontend-translations";
const SUPPORTED_LANGUAGES = new Set([
  "bg", "cs", "da", "de", "el", "en", "es", "es-419", "fi", "fr", "hu",
  "it", "ja", "lt", "nb", "nl", "pl", "pt", "pt-BR", "ro", "sv", "th",
  "tr", "uk", "vi", "zh-Hans",
]);
const catalogCache = new Map();

export function cardLanguage(hass) {
  const raw = String(hass?.locale?.language || hass?.language || DEFAULT_LANGUAGE)
    .trim()
    .replaceAll("_", "-");
  const exact = [...SUPPORTED_LANGUAGES].find(
    (language) => language.toLowerCase() === raw.toLowerCase()
  );
  if (exact) return exact;
  const base = raw.split("-", 1)[0].toLowerCase();
  return [...SUPPORTED_LANGUAGES].find(
    (language) => language.toLowerCase() === base
  ) || DEFAULT_LANGUAGE;
}

async function fetchCatalog(language) {
  if (!catalogCache.has(language)) {
    catalogCache.set(
      language,
      fetch(`${TRANSLATION_BASE}/${encodeURIComponent(language)}.json`, {
        credentials: "same-origin",
      })
        .then((response) => {
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          return response.json();
        })
        .then((payload) => payload?.runtime?.cards || {})
        .catch(() => ({}))
    );
  }
  return catalogCache.get(language);
}

export async function loadCardTranslations(hass) {
  const language = cardLanguage(hass);
  const [english, localized] = await Promise.all([
    fetchCatalog(DEFAULT_LANGUAGE),
    language === DEFAULT_LANGUAGE ? Promise.resolve({}) : fetchCatalog(language),
  ]);
  return { language, english, localized };
}

function resolveKey(catalog, key) {
  return String(key || "")
    .split(".")
    .reduce((value, part) => value && typeof value === "object" ? value[part] : undefined, catalog);
}

export function translateCard(catalogs, key, fallback, placeholders = {}) {
  const template = resolveKey(catalogs?.localized, key)
    || resolveKey(catalogs?.english, key)
    || fallback
    || key;
  return String(template).replace(/\{([^{}]+)\}/g, (match, name) =>
    Object.prototype.hasOwnProperty.call(placeholders, name)
      ? String(placeholders[name])
      : match
  );
}

export function localizeCardMetadata(type, catalogs, section, name, description) {
  const card = window.customCards?.find((item) => item.type === type);
  if (!card) return;
  card.name = translateCard(catalogs, `${section}.title`, name);
  card.description = translateCard(catalogs, `${section}.subtitle`, description);
}
