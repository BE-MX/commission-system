import assert from "node:assert/strict";
import test from "node:test";
import { DateTime } from "luxon";
import { nextEligibleSend, validateLocale } from "../src/outreach-schedule.mjs";

const germanLocale = {
  country: "DE",
  timezone: "Europe/Berlin",
  language: "de-DE",
  languageSource: "country",
  languageBasis: "German market office in Berlin",
};

test("uses five minutes after the next local office opening", () => {
  const result = nextEligibleSend({
    ...germanLocale,
    now: DateTime.fromISO("2026-08-14T06:00:00Z"),
  });
  assert.equal(result.scheduledAtLocal, "2026-08-14T09:05:00+02:00");
  assert.equal(result.scheduledAtUtc, "2026-08-14T07:05:00Z");
});

test("rolls after the opening window to Monday", () => {
  const result = nextEligibleSend({
    ...germanLocale,
    now: DateTime.fromISO("2026-08-14T08:00:00Z"),
  });
  assert.equal(result.scheduledAtLocal, "2026-08-17T09:05:00+02:00");
});

test("skips public holidays and observes daylight-saving offsets", () => {
  const result = nextEligibleSend({
    ...germanLocale,
    now: DateTime.fromISO("2026-12-31T10:00:00Z"),
  });
  assert.equal(result.scheduledAtLocal, "2027-01-04T09:05:00+01:00");
  assert.equal(result.scheduledAtUtc, "2027-01-04T08:05:00Z");
});

test("uses the Friday-Saturday weekend where configured", () => {
  const result = nextEligibleSend({
    country: "SA",
    timezone: "Asia/Riyadh",
    language: "ar-SA",
    languageSource: "country",
    languageBasis: "Saudi office and Arabic market",
    now: DateTime.fromISO("2026-08-13T10:00:00Z"),
  });
  assert.equal(result.scheduledAtLocal, "2026-08-16T09:05:00+03:00");
});

for (const [country, timezone, language] of [
  ["TH", "Asia/Bangkok", "th-TH"],
  ["TR", "Europe/Istanbul", "tr-TR"],
  ["NG", "Africa/Lagos", "en-NG"],
]) {
  test(`${country} keeps Sunday as weekend`, () => {
    const result = nextEligibleSend({
      country,
      timezone,
      language,
      languageSource: "company",
      languageBasis: "The recipient company's official page uses this language",
      now: DateTime.fromISO("2026-08-14T10:00:00Z"),
    });
    assert.equal(result.localDate, "2026-08-17");
  });
}

test("accepts canonical Japanese despite the holiday library's legacy jp code", () => {
  const result = validateLocale({
    country: "JP",
    timezone: "Asia/Tokyo",
    language: "ja-JP",
    languageSource: "country",
    languageBasis: "Japan is the sourced recipient country",
  });
  assert.equal(result.language, "ja-JP");
  assert(result.countryLanguages.includes("ja"));
});

test("rejects a timezone outside the recipient country", () => {
  assert.throws(() => validateLocale({
    ...germanLocale,
    timezone: "Asia/Shanghai",
  }), /not compatible/u);
});

test("rejects country-only language guesses in multilingual markets", () => {
  assert.throws(() => validateLocale({
    country: "CA",
    state: "ON",
    timezone: "America/Toronto",
    language: "en-CA",
    languageSource: "country",
    languageBasis: "Canada is the recipient country",
  }), /multilingual/u);
});

test("requires a subdivision for countries spanning multiple timezones", () => {
  assert.throws(() => validateLocale({
    country: "US",
    timezone: "America/New_York",
    language: "en-US",
    languageSource: "company",
    languageBasis: "The company contact page is written in English",
  }), /multiple timezones/u);
});

test("accepts a sourced subdivision and its matching timezone", () => {
  const result = validateLocale({
    country: "US",
    state: "NY",
    timezone: "America/New_York",
    language: "en-US",
    languageSource: "company",
    languageBasis: "The New York office contact page is written in English",
  });
  assert.equal(result.state, "NY");
});

test("normalizes a subdivision name to its official code", () => {
  const result = validateLocale({
    country: "DE",
    state: "Berlin",
    timezone: "Europe/Berlin",
    language: "de-DE",
    languageSource: "company",
    languageBasis: "The Berlin office contact page is written in German",
  });
  assert.equal(result.state, "BE");
});

test("rejects implausible office-opening times", () => {
  assert.throws(() => nextEligibleSend({
    ...germanLocale,
    officeStart: "02:00",
    now: DateTime.utc(),
  }), /between 06:00 and 11:59/u);
});
