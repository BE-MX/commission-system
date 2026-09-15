import { createServer as createHttpServer } from "node:http";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DateTime } from "luxon";
import { nextEligibleSend, validateLocale } from "./outreach-schedule.mjs";

const MAX_BODY_BYTES = 64 * 1024;

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolvePromise, rejectPromise) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        rejectPromise(new Error("request body exceeds 64KB"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolvePromise(Buffer.concat(chunks).toString("utf8")));
    req.on("error", rejectPromise);
  });
}

function isAuthorized(req, token) {
  if (!token) return true; // only reachable with MAIL_SCHEDULE_ALLOW_INSECURE=1
  return req.headers.authorization === `Bearer ${token}`;
}

export function createServer({ token = "" } = {}) {
  return createHttpServer(async (req, res) => {
    const path = new URL(req.url, "http://localhost").pathname;
    let status = 500;
    try {
      if (path === "/health") {
        if (req.method !== "GET") {
          status = 405;
          sendJson(res, status, { ok: false, error: { code: "method_not_allowed" } });
          return;
        }
        status = 200;
        sendJson(res, status, { ok: true, data: { service: "mail-schedule", version: "1" } });
        return;
      }
      if (path !== "/schedule/preview") {
        status = 404;
        sendJson(res, status, { ok: false, error: { code: "not_found" } });
        return;
      }
      if (req.method !== "POST") {
        status = 405;
        sendJson(res, status, { ok: false, error: { code: "method_not_allowed" } });
        return;
      }
      if (!isAuthorized(req, token)) {
        status = 401;
        sendJson(res, status, { ok: false, error: { code: "unauthorized" } });
        return;
      }

      let raw;
      try {
        raw = await readBody(req);
      } catch {
        status = 400;
        sendJson(res, status, { ok: false, error: { code: "invalid_json", message: "request body too large or unreadable" } });
        return;
      }
      let body;
      try {
        body = JSON.parse(raw);
      } catch {
        status = 400;
        sendJson(res, status, { ok: false, error: { code: "invalid_json", message: "request body must be valid JSON" } });
        return;
      }

      try {
        const locale = validateLocale({
          country: body.country,
          state: body.state,
          timezone: body.timezone,
          language: body.language,
          languageSource: body.languageSource,
          languageBasis: body.languageBasis,
        });
        const result = nextEligibleSend({
          ...locale,
          ...(body.officeStart !== undefined ? { officeStart: body.officeStart } : {}),
          ...(body.now !== undefined ? { now: DateTime.fromISO(String(body.now)) } : {}),
        });
        status = 200;
        sendJson(res, status, {
          ok: true,
          data: {
            country: result.country,
            state: result.state,
            timezone: result.timezone,
            language: result.language,
            officeStart: result.officeStart,
            scheduledAtUtc: result.scheduledAtUtc,
            scheduledAtLocal: result.scheduledAtLocal,
            localDate: result.localDate,
          },
        });
      } catch (error) {
        status = 400;
        sendJson(res, status, { ok: false, error: { code: "invalid_locale", message: error.message } });
      }
    } catch (error) {
      status = 500;
      sendJson(res, status, { ok: false, error: { code: "internal", message: error.message } });
    } finally {
      // Status-code level access log only; request bodies carry customer language evidence.
      process.stderr.write(`${req.method} ${path} ${status}\n`);
    }
  });
}

async function main() {
  const token = process.env.MAIL_SCHEDULE_TOKEN || "";
  if (!token && process.env.MAIL_SCHEDULE_ALLOW_INSECURE !== "1") {
    throw new Error("MAIL_SCHEDULE_TOKEN is required (set MAIL_SCHEDULE_ALLOW_INSECURE=1 only for local debugging)");
  }
  const bind = process.env.MAIL_SCHEDULE_BIND || "127.0.0.1";
  const port = Number.parseInt(process.env.MAIL_SCHEDULE_PORT || "7910", 10);
  const server = createServer({ token });
  await new Promise((resolvePromise, rejectPromise) => {
    server.once("error", rejectPromise);
    server.listen(port, bind, resolvePromise);
  });
  process.stderr.write(`mail-schedule listening on ${bind}:${port}\n`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
