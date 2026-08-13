#!/usr/bin/env node

import { DateTime } from "luxon";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { confirmOutreach, listOutreach, previewOutreach } from "../src/outreach-queue.mjs";
import { nextEligibleSend } from "../src/outreach-schedule.mjs";
import { ArkClient } from "../src/ark-client.mjs";
import { loadConfig } from "../src/config.mjs";

const VALUE_FLAGS = new Set([
  "--to", "--subject", "--body", "--country", "--state", "--timezone",
  "--language", "--language-source", "--language-basis", "--office-start", "--token",
  "--company-id", "--contact-id", "--research-id", "--lead-updated-at",
  "--email-status", "--language-evidence-url",
]);

function parseFlags(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (!VALUE_FLAGS.has(flag) || values[flag] !== undefined) throw new Error(`unsupported or repeated flag: ${flag}`);
    const value = argv[index + 1];
    if (value === undefined || value.startsWith("--")) throw new Error(`missing value for ${flag}`);
    values[flag] = value;
    index += 1;
  }
  return values;
}

function print(data) {
  process.stdout.write(`${JSON.stringify({ ok: true, data }, null, 2)}\n`);
}

async function loadArkClient() {
  const profile = process.env.OPENCLAW_PROFILE || "ark-sales";
  const stateDir = resolve(homedir(), `.openclaw-${profile}`);
  const env = { ...process.env };
  let contents = "";
  try {
    contents = await readFile(resolve(stateDir, ".env"), "utf8");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  for (const rawLine of contents.split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator < 1) continue;
    const key = line.slice(0, separator).trim();
    if (!["ARK_BASE_URL", "ARK_ALLOWED_ORIGIN", "ARK_AGENT_ID", "ARK_API_TIMEOUT_MS"].includes(key)) continue;
    let value = line.slice(separator + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"'))
      || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    env[key] = value;
  }
  env.ARK_AGENT_TOKEN_FILE ||= resolve(stateDir, "secrets", "ark-agent-token");
  return new ArkClient(loadConfig(env));
}

function comparableUrl(value) {
  try {
    const url = new URL(value);
    url.hash = "";
    if (url.pathname === "/") url.pathname = "";
    return url.href.replace(/\/$/u, "");
  } catch {
    return null;
  }
}

async function verifyLead(binding) {
  const lead = await (await loadArkClient()).getLead(binding.companyId);
  if (lead?.id !== binding.companyId || lead.status !== "approved" || !lead.country
    || lead.updated_at !== binding.leadUpdatedAt) {
    throw new Error("Ark lead is no longer an approved, country-resolved company");
  }
  const contact = lead.contacts?.find((item) => item.id === binding.contactId);
  if (!contact || contact.email?.toLowerCase() !== binding.to.toLowerCase()
    || contact.email_status !== "valid" || !contact.verified_at) {
    throw new Error("Ark contact no longer has the same verified valid email");
  }
  const research = lead.research;
  if (!research || research.id !== binding.researchId || research.status !== "completed"
    || !Array.isArray(research.facts) || research.facts.length === 0) {
    throw new Error("Ark research changed or is no longer completed and evidence-backed");
  }
  const allowedEvidence = new Set([
    lead.website,
    contact.source_url,
    ...research.facts.map((fact) => fact.source_url),
  ].map(comparableUrl).filter(Boolean));
  if (!allowedEvidence.has(comparableUrl(binding.languageEvidenceUrl))) {
    throw new Error("language evidence URL is not bound to the current Ark lead snapshot");
  }
}

export async function main(argv = process.argv.slice(2)) {
  const [command, ...rest] = argv;
  if (command === "schedule") {
    const flags = parseFlags(rest);
    const result = nextEligibleSend({
      country: flags["--country"],
      state: flags["--state"],
      timezone: flags["--timezone"],
      language: flags["--language"],
      languageSource: flags["--language-source"],
      languageBasis: flags["--language-basis"],
      companyId: flags["--company-id"],
      contactId: flags["--contact-id"],
      researchId: flags["--research-id"],
      leadUpdatedAt: flags["--lead-updated-at"],
      emailStatus: flags["--email-status"],
      languageEvidenceUrl: flags["--language-evidence-url"],
      officeStart: flags["--office-start"] || "09:00",
      now: DateTime.utc(),
    });
    print(result);
    return;
  }
  if (command === "preview") {
    const flags = parseFlags(rest);
    print(await previewOutreach({
      to: flags["--to"],
      subject: flags["--subject"],
      body: flags["--body"],
      country: flags["--country"],
      state: flags["--state"],
      timezone: flags["--timezone"],
      language: flags["--language"],
      languageSource: flags["--language-source"],
      languageBasis: flags["--language-basis"],
      officeStart: flags["--office-start"] || "09:00",
    }));
    return;
  }
  if (command === "confirm") {
    const flags = parseFlags(rest);
    print(await confirmOutreach(flags["--token"], { now: DateTime.utc(), verifyLead }));
    return;
  }
  if (command === "list" && rest.length === 0) {
    print(await listOutreach());
    return;
  }
  throw new Error("usage: outreach-queue <schedule|preview|confirm|list> [flags]");
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  main().catch((error) => {
    process.stderr.write(`${JSON.stringify({ ok: false, error: error.message })}\n`);
    process.exitCode = 2;
  });
}
