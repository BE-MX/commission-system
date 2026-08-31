import { createHash, randomBytes } from "node:crypto";
import { link, mkdir, open, readFile, readdir, rename, stat, unlink, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { DateTime } from "luxon";
import { nextEligibleSend } from "./outreach-schedule.mjs";

const PREVIEW_TTL_MS = 5 * 60 * 1000;
const MAX_LATE_MINUTES = 30;
const STALE_LOCK_MS = 5 * 60 * 1000;

export function queueRoot() {
  return process.env.OUTREACH_QUEUE_DIR
    || join(homedir(), `.openclaw-${process.env.OPENCLAW_PROFILE || "ark-sales"}`, "outreach-queue");
}

function safeToken() {
  return `oqt_${randomBytes(24).toString("base64url")}`;
}

function safeId() {
  return `oq_${Date.now()}_${randomBytes(8).toString("hex")}`;
}

function payloadHash(payload) {
  return createHash("sha256").update(JSON.stringify(payload)).digest("hex");
}

async function atomicJson(path, data, { exclusive = false } = {}) {
  const temporary = `${path}.${process.pid}.${randomBytes(4).toString("hex")}.tmp`;
  await writeFile(temporary, `${JSON.stringify(data, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
    flag: "wx",
  });
  try {
    if (exclusive) {
      await link(temporary, path);
      await unlink(temporary);
    } else {
      await rename(temporary, path);
    }
  } catch (error) {
    await unlink(temporary).catch(() => {});
    throw error;
  }
}

async function ensureDirectories(root) {
  await mkdir(root, { recursive: true, mode: 0o700 });
  for (const name of ["previews", "jobs"]) {
    await mkdir(join(root, name), { recursive: true, mode: 0o700 });
  }
}

function validatePositiveId(value, field) {
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) throw new Error(`${field} must be a positive integer`);
  return parsed;
}

function validateIdList(value, field) {
  if (!Array.isArray(value) || value.length === 0) throw new Error(`${field} must contain positive integers`);
  const ids = value.map((item) => validatePositiveId(item, field));
  if (new Set(ids).size !== ids.length) throw new Error(`${field} must not contain duplicates`);
  return ids.sort((left, right) => left - right);
}

function validateEvidenceUrl(value) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw new Error("language-evidence-url must be a public HTTP(S) URL without credentials");
  }
  return url.href;
}

function validateBodyScript(body, language) {
  const primary = String(language || "").toLowerCase().split("-")[0];
  const requiredScripts = new Map([
    ["ar", /\p{Script=Arabic}/u], ["fa", /\p{Script=Arabic}/u], ["ur", /\p{Script=Arabic}/u],
    ["el", /\p{Script=Greek}/u], ["he", /\p{Script=Hebrew}/u], ["hi", /\p{Script=Devanagari}/u],
    ["ja", /[\p{Script=Hiragana}\p{Script=Katakana}]/u], ["ko", /\p{Script=Hangul}/u],
    ["ru", /\p{Script=Cyrillic}/u], ["th", /\p{Script=Thai}/u], ["uk", /\p{Script=Cyrillic}/u],
    ["zh", /\p{Script=Han}/u],
  ]);
  const expected = requiredScripts.get(primary);
  if (expected && !expected.test(body)) {
    throw new Error(`body does not contain the expected script for ${language}`);
  }
}

function validateEmailPayload({
  to, subject, body, customerId, contactId, contactPointId, profileVersionId, factIds, evidenceIds,
  emailStatus, languageEvidenceUrl, language,
}) {
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/u.test(to || "") || to.length > 320) {
    throw new Error("to must be one valid email address");
  }
  if (!subject || subject.length > 998 || /[\r\n]/u.test(subject)) {
    throw new Error("subject must be 1-998 characters without line breaks");
  }
  if (!body || Buffer.byteLength(body, "utf8") > 20_000) {
    throw new Error("body must be 1-20000 UTF-8 bytes");
  }
  validateBodyScript(body, language);
  if (emailStatus !== "valid") throw new Error("sending requires a currently valid email status");
  return {
    customerId: validatePositiveId(customerId, "customer-id"),
    contactId: validatePositiveId(contactId, "contact-id"),
    contactPointId: validatePositiveId(contactPointId, "contact-point-id"),
    profileVersionId: validatePositiveId(profileVersionId, "profile-version-id"),
    factIds: validateIdList(factIds, "fact-ids"),
    evidenceIds: validateIdList(evidenceIds, "evidence-ids"),
    languageEvidenceUrl: validateEvidenceUrl(languageEvidenceUrl),
  };
}

export async function previewOutreach(input, { root = queueRoot(), now = DateTime.utc() } = {}) {
  const customerBinding = validateEmailPayload(input);
  const schedule = nextEligibleSend({ ...input, now });
  await ensureDirectories(root);
  const createdAt = now.toUTC();
  const preview = {
    version: 1,
    id: safeId(),
    token: safeToken(),
    createdAt: createdAt.toISO({ suppressMilliseconds: true }),
    expiresAt: createdAt.plus({ milliseconds: PREVIEW_TTL_MS }).toISO({ suppressMilliseconds: true }),
    payload: { to: input.to, subject: input.subject, body: input.body },
    schedule: {
      country: schedule.country,
      state: schedule.state,
      timezone: schedule.timezone,
      officeStart: schedule.officeStart,
      scheduledAtUtc: schedule.scheduledAtUtc,
      scheduledAtLocal: schedule.scheduledAtLocal,
      localDate: schedule.localDate,
    },
    localization: {
      language: schedule.language,
      languageSource: schedule.languageSource,
      languageBasis: schedule.languageBasis,
      countryLanguages: schedule.countryLanguages,
    },
    customerBinding: {
      ...customerBinding,
      emailStatus: input.emailStatus,
    },
  };
  preview.payloadHash = payloadHash({
    payload: preview.payload,
    schedule: preview.schedule,
    localization: preview.localization,
    customerBinding: preview.customerBinding,
  });
  await atomicJson(join(root, "previews", `${preview.token}.json`), preview);
  return preview;
}

export async function confirmOutreach(token, {
  root = queueRoot(), now = DateTime.utc(), verifyCustomer,
} = {}) {
  if (!/^oqt_[A-Za-z0-9_-]{20,}$/u.test(token || "")) throw new Error("invalid preview token");
  await ensureDirectories(root);
  const previewPath = join(root, "previews", `${token}.json`);
  const claimedPreviewPath = `${previewPath}.confirming.${process.pid}.${randomBytes(4).toString("hex")}`;
  try {
    await rename(previewPath, claimedPreviewPath);
  } catch (error) {
    if (error.code === "ENOENT") throw new Error("preview token is missing, expired, or already being confirmed");
    throw error;
  }
  let preview;
  try {
    preview = JSON.parse(await readFile(claimedPreviewPath, "utf8"));
  } catch (error) {
    await rename(claimedPreviewPath, previewPath).catch(() => {});
    throw error;
  }
  try {
    if (preview.token !== token) throw new Error("preview token binding check failed");
    const expectedHash = payloadHash({
      payload: preview.payload,
      schedule: preview.schedule,
      localization: preview.localization,
      customerBinding: preview.customerBinding,
    });
    if (preview.payloadHash !== expectedHash) throw new Error("preview integrity check failed");
    if (now >= DateTime.fromISO(preview.expiresAt)) throw new Error("preview token expired; create a new preview");
    if (now >= DateTime.fromISO(preview.schedule.scheduledAtUtc)) {
      throw new Error("reviewed send window has passed; create a new preview");
    }
    if (typeof verifyCustomer !== "function") {
      throw new Error("confirmation requires trusted Ark customer verification outside the email Agent");
    }
    await verifyCustomer({
      ...preview.customerBinding,
      to: preview.payload.to,
    });

    const job = {
      version: 1,
      id: preview.id,
      status: "queued",
      confirmedAt: now.toUTC().toISO({ suppressMilliseconds: true }),
      attempts: 0,
      ...Object.fromEntries(["payload", "schedule", "localization", "customerBinding", "payloadHash"].map((key) => [key, preview[key]])),
    };
    const jobPath = join(root, "jobs", `${job.id}.json`);
    try {
      await atomicJson(jobPath, job, { exclusive: true });
    } catch (error) {
      if (error.code !== "EEXIST") throw error;
      const existing = JSON.parse(await readFile(jobPath, "utf8"));
      if (existing.payloadHash !== job.payloadHash) throw new Error("queue id collision");
      return existing;
    }
    return job;
  } finally {
    await unlink(claimedPreviewPath).catch(() => {});
  }
}

export async function listOutreach({ root = queueRoot() } = {}) {
  await ensureDirectories(root);
  const names = (await readdir(join(root, "jobs"))).filter((name) => name.endsWith(".json"));
  const jobs = await Promise.all(names.map(async (name) => JSON.parse(
    await readFile(join(root, "jobs", name), "utf8"),
  )));
  return jobs.sort((a, b) => a.schedule.scheduledAtUtc.localeCompare(b.schedule.scheduledAtUtc)).map((job) => ({
    id: job.id,
    status: job.status,
    to: job.payload.to,
    subject: job.payload.subject,
    language: job.localization.language,
    scheduledAtLocal: job.schedule.scheduledAtLocal,
    scheduledAtUtc: job.schedule.scheduledAtUtc,
    sentAt: job.sentAt || null,
    lastError: job.lastError || null,
  }));
}

async function acquireDispatchLock(lockPath, nowMs, allowStaleRecovery = true) {
  try {
    const handle = await open(lockPath, "wx", 0o600);
    await handle.writeFile(`${JSON.stringify({ pid: process.pid, createdAt: new Date(nowMs).toISOString() })}\n`);
    return handle;
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
  }
  if (!allowStaleRecovery) return null;
  const metadata = await stat(lockPath).catch((error) => {
    if (error.code === "ENOENT") return null;
    throw error;
  });
  if (!metadata) return acquireDispatchLock(lockPath, nowMs, false);
  if (nowMs - metadata.mtimeMs <= STALE_LOCK_MS) return null;
  const stalePath = `${lockPath}.stale.${process.pid}.${randomBytes(4).toString("hex")}`;
  try {
    await rename(lockPath, stalePath);
    await unlink(stalePath).catch(() => {});
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  return acquireDispatchLock(lockPath, nowMs, false);
}

async function withDispatchLock(root, now, callback) {
  await ensureDirectories(root);
  const lockPath = join(root, "dispatch.lock");
  const handle = await acquireDispatchLock(lockPath, now.toMillis());
  if (!handle) return { skipped: "dispatcher already running" };
  try {
    return await callback();
  } finally {
    await handle.close();
    await unlink(lockPath).catch(() => {});
  }
}

export async function dispatchDue({
  root = queueRoot(),
  now = DateTime.utc(),
  send,
} = {}) {
  if (typeof send !== "function") throw new Error("dispatcher requires a send function");
  return withDispatchLock(root, now, async () => {
    const names = (await readdir(join(root, "jobs"))).filter((name) => name.endsWith(".json")).sort();
    const results = [];
    for (const name of names) {
      const path = join(root, "jobs", name);
      const job = JSON.parse(await readFile(path, "utf8"));
      if (job.status === "sending") {
        job.status = "ambiguous";
        job.lastError = "previous dispatcher stopped after send began; inspect Sent before any manual retry";
        await atomicJson(path, job);
        results.push({ id: job.id, status: job.status });
        continue;
      }
      if (job.status !== "queued") continue;
      const expectedHash = payloadHash({
        payload: job.payload,
        schedule: job.schedule,
        localization: job.localization,
        customerBinding: job.customerBinding,
      });
      if (job.payloadHash !== expectedHash) {
        job.status = "blocked";
        job.lastError = "job integrity check failed";
        await atomicJson(path, job);
        results.push({ id: job.id, status: job.status });
        continue;
      }
      const due = DateTime.fromISO(job.schedule.scheduledAtUtc);
      if (!due.isValid) {
        job.status = "blocked";
        job.lastError = "invalid scheduledAtUtc";
        await atomicJson(path, job);
        results.push({ id: job.id, status: job.status });
        continue;
      }
      const nextAttemptAt = job.nextAttemptAt ? DateTime.fromISO(job.nextAttemptAt) : null;
      if (nextAttemptAt?.isValid && now < nextAttemptAt) continue;
      if (now < due) continue;
      if (now.diff(due, "minutes").minutes > MAX_LATE_MINUTES) {
        const next = nextEligibleSend({
          ...job.schedule,
          ...job.localization,
          now,
        });
        job.schedule.scheduledAtUtc = next.scheduledAtUtc;
        job.schedule.scheduledAtLocal = next.scheduledAtLocal;
        job.schedule.localDate = next.localDate;
        job.payloadHash = payloadHash({
          payload: job.payload,
          schedule: job.schedule,
          localization: job.localization,
          customerBinding: job.customerBinding,
        });
        job.rescheduledAt = now.toUTC().toISO({ suppressMilliseconds: true });
        job.nextAttemptAt = null;
        job.rescheduleReason = "missed local opening window by more than 30 minutes";
        await atomicJson(path, job);
        results.push({ id: job.id, status: "rescheduled", scheduledAtUtc: next.scheduledAtUtc });
        continue;
      }

      const sendStartedAt = now.toUTC().toISO({ suppressMilliseconds: true });
      job.status = "sending";
      job.lastSendStartedAt = sendStartedAt;
      job.sendStartedAt = sendStartedAt;
      job.attempts += 1;
      await atomicJson(path, job);
      let outcome;
      try {
        outcome = await send(job.payload);
      } catch (error) {
        job.status = "ambiguous";
        job.lastError = `send outcome unknown: ${String(error?.message || error).slice(0, 900)}`;
        await atomicJson(path, job);
        results.push({ id: job.id, status: job.status });
        continue;
      }
      if (outcome.ok) {
        job.status = "sent";
        job.sentAt = DateTime.utc().toISO({ suppressMilliseconds: true });
        job.messageId = outcome.messageId || null;
        job.lastError = null;
        job.nextAttemptAt = null;
      } else {
        job.lastError = String(outcome.error || "Agent Mail send failed").slice(0, 1000);
        job.lastExitCode = outcome.exitCode ?? null;
        job.status = outcome.definitelyNotStarted ? "failed" : "ambiguous";
        if (job.status === "ambiguous") {
          job.lastError = `send may have been accepted; inspect Sent before any manual retry: ${job.lastError}`;
        }
      }
      await atomicJson(path, job);
      results.push({ id: job.id, status: job.status });
    }
    return { processed: results.length, results };
  });
}
