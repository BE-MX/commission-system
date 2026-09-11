import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "../src/mail-schedule-service.mjs";

const TOKEN = "test-schedule-token";

async function startServer(t) {
  const server = createServer({ token: TOKEN });
  await new Promise((resolvePromise) => server.listen(0, "127.0.0.1", resolvePromise));
  t.after(() => new Promise((resolvePromise) => server.close(resolvePromise)));
  return `http://127.0.0.1:${server.address().port}`;
}

function preview(baseUrl, body, headers = {}) {
  return fetch(`${baseUrl}/schedule/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${TOKEN}`, ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

const validPreview = {
  country: "US",
  state: "NY",
  timezone: "America/New_York",
  language: "en",
  languageSource: "company",
  languageBasis: "The New York office contact page is written in English",
  officeStart: "09:00",
  now: "2026-08-14T06:00:00Z",
};

test("GET /health responds without authentication", async (t) => {
  const baseUrl = await startServer(t);
  const res = await fetch(`${baseUrl}/health`);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("content-type"), "application/json");
  assert.deepEqual(await res.json(), { ok: true, data: { service: "mail-schedule", version: "1" } });
});

test("preview rejects missing and wrong bearer tokens", async (t) => {
  const baseUrl = await startServer(t);
  const noToken = await fetch(`${baseUrl}/schedule/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(validPreview),
  });
  assert.equal(noToken.status, 401);
  assert.deepEqual(await noToken.json(), { ok: false, error: { code: "unauthorized" } });

  const wrongToken = await preview(baseUrl, validPreview, { Authorization: "Bearer wrong" });
  assert.equal(wrongToken.status, 401);
  assert.deepEqual(await wrongToken.json(), { ok: false, error: { code: "unauthorized" } });
});

test("preview returns the next eligible local opening", async (t) => {
  const baseUrl = await startServer(t);
  const res = await preview(baseUrl, validPreview);
  assert.equal(res.status, 200);
  const payload = await res.json();
  assert.equal(payload.ok, true);
  assert.equal(payload.data.country, "US");
  assert.equal(payload.data.state, "NY");
  assert.equal(payload.data.timezone, "America/New_York");
  assert.equal(payload.data.language, "en");
  assert.equal(payload.data.officeStart, "09:00");
  assert.equal(payload.data.scheduledAtLocal, "2026-08-14T09:05:00-04:00");
  assert.equal(payload.data.scheduledAtUtc, "2026-08-14T13:05:00Z");
  assert.equal(payload.data.localDate, "2026-08-14");
  assert.equal(payload.data.holidays, undefined);
});

test("preview rejects a timezone outside the recipient country", async (t) => {
  const baseUrl = await startServer(t);
  const res = await preview(baseUrl, { ...validPreview, timezone: "Europe/Berlin" });
  assert.equal(res.status, 400);
  const payload = await res.json();
  assert.equal(payload.ok, false);
  assert.equal(payload.error.code, "invalid_locale");
  assert.match(payload.error.message, /not compatible/u);
});

test("preview rejects country-language fallback in multilingual countries", async (t) => {
  const baseUrl = await startServer(t);
  const res = await preview(baseUrl, {
    country: "CA",
    state: "ON",
    timezone: "America/Toronto",
    language: "en-CA",
    languageSource: "country",
    languageBasis: "Canada is the recipient country",
  });
  assert.equal(res.status, 400);
  const payload = await res.json();
  assert.equal(payload.ok, false);
  assert.equal(payload.error.code, "invalid_locale");
  assert.match(payload.error.message, /multilingual/u);
});

test("preview rejects a malformed JSON body", async (t) => {
  const baseUrl = await startServer(t);
  const res = await preview(baseUrl, "{not json");
  assert.equal(res.status, 400);
  const payload = await res.json();
  assert.equal(payload.ok, false);
  assert.equal(payload.error.code, "invalid_json");
});

test("unknown paths get 404 and wrong methods get 405", async (t) => {
  const baseUrl = await startServer(t);
  const missing = await fetch(`${baseUrl}/nope`);
  assert.equal(missing.status, 404);
  const wrongMethod = await fetch(`${baseUrl}/schedule/preview`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
  });
  assert.equal(wrongMethod.status, 405);
});
