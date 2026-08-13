import Holidays from "date-holidays";
import { DateTime } from "luxon";

const MULTILINGUAL_COUNTRIES = new Set([
  "BE", "BO", "CA", "CH", "CY", "FI", "IN", "IE", "LU", "MT", "MU", "MY", "NZ", "PH", "SG", "ZA",
]);

const LANGUAGE_ALIASES = new Map([
  ["cz", "cs"],
  ["ge", "ka"],
  ["jp", "ja"],
]);

function normalizeLanguage(value) {
  const primary = value.toLowerCase().split("-")[0];
  return LANGUAGE_ALIASES.get(primary) || primary;
}

function weekendDays(country) {
  const weekend = new Intl.Locale(`und-${country}`).getWeekInfo?.().weekend;
  if (!Array.isArray(weekend) || weekend.length === 0
    || weekend.some((day) => !Number.isInteger(day) || day < 1 || day > 7)) {
    throw new Error(`workweek data is unavailable for ${country}`);
  }
  return new Set(weekend);
}

function parseOfficeStart(value) {
  const match = /^(?<hour>[01]\d|2[0-3]):(?<minute>[0-5]\d)$/u.exec(value);
  if (!match) throw new Error("office-start must use 24-hour HH:MM");
  const opening = {
    hour: Number.parseInt(match.groups.hour, 10),
    minute: Number.parseInt(match.groups.minute, 10),
  };
  if (opening.hour < 6 || opening.hour > 11) {
    throw new Error("office-start must be a sourced business opening between 06:00 and 11:59");
  }
  return opening;
}

function createHolidays(country, state) {
  const code = country.toUpperCase();
  const base = new Holidays();
  const countries = base.getCountries();
  if (!countries[code]) throw new Error(`unsupported ISO country code: ${code}`);
  let canonicalState = null;
  if (state) {
    const states = base.getStates(code) || {};
    const normalized = state.trim().toLocaleLowerCase("en-US");
    const matched = Object.entries(states).find(([key, name]) => (
      key.toLocaleLowerCase("en-US") === normalized
      || String(name).toLocaleLowerCase("en-US") === normalized
    ))?.[0];
    if (!matched) throw new Error(`unsupported state/subdivision for ${code}: ${state}`);
    canonicalState = matched;
  }
  try {
    return { holidays: new Holidays(code, canonicalState || undefined), state: canonicalState };
  } catch (error) {
    throw new Error(`invalid country/state combination: ${error.message}`);
  }
}

export function validateLocale({
  country,
  state,
  timezone,
  language,
  languageSource,
  languageBasis,
}) {
  const code = String(country || "").toUpperCase();
  if (!/^[A-Z]{2}$/u.test(code)) throw new Error("country must be ISO 3166-1 alpha-2");
  if (!DateTime.local().setZone(timezone).isValid) throw new Error(`invalid IANA timezone: ${timezone}`);
  if (!/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/u.test(language || "")) {
    throw new Error("language must be a BCP 47 tag");
  }
  if (!["recipient", "company", "country"].includes(languageSource)) {
    throw new Error("language-source must be recipient, company, or country");
  }
  if (typeof languageBasis !== "string" || languageBasis.trim().length < 8 || languageBasis.length > 500) {
    throw new Error("language-basis must contain 8-500 characters of evidence");
  }

  const localeHolidays = createHolidays(code, state);
  const { holidays } = localeHolidays;
  const countryTimezones = holidays.getTimezones?.() || [];
  if (countryTimezones.length > 1 && !state) {
    throw new Error(`${code} spans multiple timezones; provide a sourced state/subdivision`);
  }
  if (!countryTimezones.includes(timezone)) {
    throw new Error(`${timezone} is not compatible with country ${code}`);
  }

  const countryLanguages = (holidays.getLanguages?.() || []).map(normalizeLanguage);
  const primaryLanguage = normalizeLanguage(language);
  if (languageSource === "country") {
    const localizedLanguages = [...new Set(countryLanguages.filter((item, index) => (
      item !== "en" || index === 0
    )))];
    if (MULTILINGUAL_COUNTRIES.has(code) || localizedLanguages.length > 1) {
      throw new Error(`${code} is multilingual; use recipient or company language evidence`);
    }
    if (countryLanguages[0] !== primaryLanguage) {
      throw new Error(`country-default language for ${code} is ${countryLanguages[0] || "unknown"}`);
    }
  }

  return {
    country: code,
    state: localeHolidays.state,
    timezone,
    language,
    languageSource,
    languageBasis: languageBasis.trim(),
    countryLanguages: [...new Set(countryLanguages)],
    holidays,
  };
}

export function nextEligibleSend({
  country,
  state,
  timezone,
  language,
  languageSource,
  languageBasis,
  officeStart = "09:00",
  now = DateTime.utc(),
}) {
  const locale = validateLocale({
    country, state, timezone, language, languageSource, languageBasis,
  });
  const opening = parseOfficeStart(officeStart);
  const localNow = DateTime.isDateTime(now) ? now.setZone(timezone) : DateTime.fromJSDate(now).setZone(timezone);
  if (!localNow.isValid) throw new Error("now must be a valid instant");
  const weekends = weekendDays(locale.country);

  for (let offset = 0; offset < 370; offset += 1) {
    const day = localNow.startOf("day").plus({ days: offset });
    if (weekends.has(day.weekday)) continue;
    const holiday = locale.holidays.isHoliday(day.toJSDate());
    const closedHoliday = Array.isArray(holiday)
      ? holiday.find((item) => ["public", "bank"].includes(item.type))
      : null;
    if (closedHoliday) continue;

    const candidate = day.set(opening).plus({ minutes: 5 });
    if (candidate <= localNow) continue;
    return {
      ...locale,
      holidays: undefined,
      officeStart,
      scheduledAtUtc: candidate.toUTC().toISO({ suppressMilliseconds: true }),
      scheduledAtLocal: candidate.toISO({ suppressMilliseconds: true }),
      localDate: candidate.toISODate(),
    };
  }
  throw new Error("no eligible workday found in the next 370 days");
}
