import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { DateTime } from "luxon";
import { confirmOutreach, dispatchDue, previewOutreach } from "../src/outreach-queue.mjs";

const input = {
  to: "buyer@example.de",
  subject: "Eine kurze Frage zu Ihrem Sortiment",
  body: "Guten Tag Frau Müller,\n\nich habe eine kurze, konkrete Frage.",
  country: "DE",
  timezone: "Europe/Berlin",
  language: "de-DE",
  languageSource: "company",
  languageBasis: "The German contact page and recipient profile are in German",
  officeStart: "09:00",
  companyId: 11,
  contactId: 22,
  researchId: 33,
  leadUpdatedAt: "2026-08-13T12:00:00Z",
  emailStatus: "valid",
  languageEvidenceUrl: "https://example.de/kontakt",
};

const verifyLead = async () => {};

async function temporaryQueue(t) {
  const root = await mkdtemp(join(tmpdir(), "outreach-queue-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  return root;
}

test("preview and confirmation preserve the exact reviewed payload", async (t) => {
  const root = await temporaryQueue(t);
  const now = DateTime.fromISO("2026-08-14T06:00:00Z");
  const preview = await previewOutreach(input, { root, now });
  assert.match(preview.token, /^oqt_/u);
  assert.equal(preview.schedule.scheduledAtLocal, "2026-08-14T09:05:00+02:00");

  const job = await confirmOutreach(preview.token, { root, now: now.plus({ minutes: 1 }), verifyLead });
  assert.equal(job.status, "queued");
  assert.deepEqual(job.payload, { to: input.to, subject: input.subject, body: input.body });
  await assert.rejects(
    () => confirmOutreach(preview.token, { root, now, verifyLead }),
    /missing, expired, or already/u,
  );
});

test("expired preview cannot authorize a queue job", async (t) => {
  const root = await temporaryQueue(t);
  const now = DateTime.fromISO("2026-08-14T06:00:00Z");
  const preview = await previewOutreach(input, { root, now });
  await assert.rejects(
    () => confirmOutreach(preview.token, { root, now: now.plus({ minutes: 6 }), verifyLead }),
    /expired/u,
  );
});

test("tampering with reviewed content blocks confirmation", async (t) => {
  const root = await temporaryQueue(t);
  const now = DateTime.fromISO("2026-08-14T06:00:00Z");
  const preview = await previewOutreach(input, { root, now });
  const path = join(root, "previews", `${preview.token}.json`);
  const stored = JSON.parse(await readFile(path, "utf8"));
  stored.payload.body = "Changed after review";
  await writeFile(path, JSON.stringify(stored));
  await assert.rejects(() => confirmOutreach(preview.token, { root, now, verifyLead }), /integrity/u);
});

test("a preview file cannot be renamed to authorize a different token", async (t) => {
  const root = await temporaryQueue(t);
  const now = DateTime.fromISO("2026-08-14T06:00:00Z");
  const preview = await previewOutreach(input, { root, now });
  const forgedToken = "oqt_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
  const stored = await readFile(join(root, "previews", `${preview.token}.json`), "utf8");
  await writeFile(join(root, "previews", `${forgedToken}.json`), stored);
  await assert.rejects(() => confirmOutreach(forgedToken, { root, now, verifyLead }), /token binding/u);
});

test("dispatcher sends a due job exactly through the injected sender", async (t) => {
  const root = await temporaryQueue(t);
  const now = DateTime.fromISO("2026-08-14T06:00:00Z");
  const preview = await previewOutreach(input, { root, now });
  const job = await confirmOutreach(preview.token, { root, now: now.plus({ minutes: 1 }), verifyLead });
  const sent = [];
  const result = await dispatchDue({
    root,
    now: DateTime.fromISO(job.schedule.scheduledAtUtc).plus({ minutes: 1 }),
    send: async (payload) => {
      sent.push(payload);
      return { ok: true, messageId: "msg_test" };
    },
  });
  assert.equal(result.processed, 1);
  assert.deepEqual(sent, [job.payload]);
  const stored = JSON.parse(await readFile(join(root, "jobs", `${job.id}.json`), "utf8"));
  assert.equal(stored.status, "sent");
  assert.equal(stored.messageId, "msg_test");
});

test("dispatcher reschedules instead of sending late", async (t) => {
  const root = await temporaryQueue(t);
  await mkdir(join(root, "jobs"), { recursive: true });
  const now = DateTime.fromISO("2026-08-14T06:00:00Z");
  const preview = await previewOutreach(input, { root, now });
  const job = await confirmOutreach(preview.token, { root, now: now.plus({ minutes: 1 }), verifyLead });
  let called = false;
  const result = await dispatchDue({
    root,
    now: DateTime.fromISO(job.schedule.scheduledAtUtc).plus({ hours: 2 }),
    send: async () => {
      called = true;
      return { ok: true };
    },
  });
  assert.equal(called, false);
  assert.equal(result.results[0].status, "rescheduled");
});

test("a nonzero send result is ambiguous and never automatically retried", async (t) => {
  const root = await temporaryQueue(t);
  const now = DateTime.fromISO("2026-08-14T06:00:00Z");
  const preview = await previewOutreach(input, { root, now });
  const job = await confirmOutreach(preview.token, { root, now: now.plus({ minutes: 1 }), verifyLead });
  const due = DateTime.fromISO(job.schedule.scheduledAtUtc).plus({ minutes: 1 });
  let calls = 0;
  await dispatchDue({
    root,
    now: due,
    send: async () => {
      calls += 1;
      return { ok: false, exitCode: 4, error: "temporary network error" };
    },
  });
  const stored = JSON.parse(await readFile(join(root, "jobs", `${job.id}.json`), "utf8"));
  assert.equal(stored.status, "ambiguous");
  await dispatchDue({
    root,
    now: due.plus({ minutes: 2 }),
    send: async () => {
      calls += 1;
      return { ok: true };
    },
  });
  assert.equal(calls, 1);
});

test("a dispatcher crash after send begins is marked ambiguous, never auto-retried", async (t) => {
  const root = await temporaryQueue(t);
  const now = DateTime.fromISO("2026-08-14T06:00:00Z");
  const preview = await previewOutreach(input, { root, now });
  const job = await confirmOutreach(preview.token, { root, now: now.plus({ minutes: 1 }), verifyLead });
  const due = DateTime.fromISO(job.schedule.scheduledAtUtc).plus({ minutes: 1 });
  const first = await dispatchDue({
    root,
    now: due,
    send: async () => { throw new Error("simulated process crash"); },
  });
  assert.equal(first.results[0].status, "ambiguous");
  let retried = false;
  const result = await dispatchDue({
    root,
    now: due.plus({ minutes: 1 }),
    send: async () => {
      retried = true;
      return { ok: true };
    },
  });
  assert.equal(retried, false);
  assert.equal(result.processed, 0);
});

test("confirmation requires a trusted out-of-agent Ark recheck", async (t) => {
  const root = await temporaryQueue(t);
  const now = DateTime.fromISO("2026-08-14T06:00:00Z");
  const preview = await previewOutreach(input, { root, now });
  await assert.rejects(
    () => confirmOutreach(preview.token, { root, now: now.plus({ minutes: 1 }) }),
    /trusted Ark lead verification/u,
  );
});

test("preview requires a currently valid Ark email binding", async (t) => {
  const root = await temporaryQueue(t);
  await assert.rejects(
    () => previewOutreach({ ...input, emailStatus: "risky" }, { root, now: DateTime.utc() }),
    /currently valid/u,
  );
});

test("preview checks the expected script for non-Latin languages", async (t) => {
  const root = await temporaryQueue(t);
  await assert.rejects(
    () => previewOutreach({
      ...input,
      country: "JP",
      timezone: "Asia/Tokyo",
      language: "ja-JP",
      languageSource: "country",
      languageBasis: "Japan is the sourced recipient country",
      body: "Hello, this is still English.",
    }, { root, now: DateTime.utc() }),
    /expected script/u,
  );
});

test("stale dispatcher lock is recovered safely", async (t) => {
  const root = await temporaryQueue(t);
  await mkdir(root, { recursive: true });
  await writeFile(join(root, "dispatch.lock"), "stale\n");
  const old = new Date(Date.now() - 10 * 60 * 1000);
  const { utimes } = await import("node:fs/promises");
  await utimes(join(root, "dispatch.lock"), old, old);
  const result = await dispatchDue({ root, now: DateTime.utc(), send: async () => ({ ok: true }) });
  assert.equal(result.processed, 0);
});
