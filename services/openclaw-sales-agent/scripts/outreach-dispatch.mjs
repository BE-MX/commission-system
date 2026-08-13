#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";
import { DateTime } from "luxon";
import { dispatchDue } from "../src/outreach-queue.mjs";

function parseMessageId(stdout) {
  try {
    const parsed = JSON.parse(stdout);
    return parsed?.data?.message_id || parsed?.data?.message?.message_id || null;
  } catch {
    return null;
  }
}

export function agentMailSender(payload) {
  const cli = process.env.AGENTLY_CLI_BIN
    || join(homedir(), ".openclaw", "tools", "node", "bin", "agently-cli");
  const result = spawnSync(cli, [
    "message", "+send",
    "--to", payload.to,
    "--subject", payload.subject,
    "--body", payload.body,
    "--body-format", "plain",
    "--confirmed",
  ], {
    encoding: "utf8",
    env: { ...process.env, AGENTLY_WORKSPACE: process.env.AGENTLY_WORKSPACE || "ark-sales" },
    timeout: 120_000,
  });
  if (result.error) {
    const definitelyNotStarted = ["ENOENT", "EACCES"].includes(result.error.code);
    if (!definitelyNotStarted) throw result.error;
    return { ok: false, definitelyNotStarted: true, exitCode: null, error: result.error.message };
  }
  if (result.signal) throw new Error(`Agent Mail terminated by ${result.signal}; send outcome is unknown`);
  if (result.status !== 0) {
    return {
      ok: false,
      definitelyNotStarted: false,
      exitCode: result.status,
      error: (result.stderr || result.stdout || `exit ${result.status}`).trim(),
    };
  }
  return { ok: true, exitCode: 0, messageId: parseMessageId(result.stdout) };
}

dispatchDue({ send: agentMailSender, now: DateTime.utc() }).then((result) => {
  process.stdout.write(`${JSON.stringify({ ok: true, data: result })}\n`);
}).catch((error) => {
  process.stderr.write(`${JSON.stringify({ ok: false, error: error.message })}\n`);
  process.exitCode = 1;
});
