#!/usr/bin/env node

import { access, lstat, readFile } from "node:fs/promises";
import { constants } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const home = homedir();
const profile = process.env.OPENCLAW_PROFILE || "ark-sales";
const stateDir = join(home, `.openclaw-${profile}`);
const openclaw = process.env.OPENCLAW_BIN || join(home, ".openclaw", "bin", "openclaw");
const nodeDir = join(home, ".openclaw", "tools", "node", "bin");
const queueBin = join(stateDir, "bin", "outreach-queue");
const dispatchBin = join(stateDir, "bin", "outreach-dispatch");
const skillReaderBin = join(stateDir, "bin", "outreach-skill-reader");

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    env: { ...process.env, ...(options.env || {}), PATH: `${nodeDir}:${process.env.PATH || ""}` },
    stdio: options.capture ? "pipe" : "inherit",
  });
  if (result.status !== 0) throw new Error(`${command} ${args.join(" ")} failed: ${(result.stderr || result.stdout).trim()}`);
  return result.stdout || "";
}

function json(command, args, options = {}) {
  return JSON.parse(run(command, args, { ...options, capture: true }));
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function assertPrivateExecutable(path) {
  await access(path, constants.X_OK);
  const metadata = await lstat(path);
  assert(metadata.isFile() && !metadata.isSymbolicLink(), `${path} must be a regular non-symlink file`);
  assert((metadata.mode & 0o077) === 0, `${path} must not grant group/other permissions`);
}

async function main() {
  const args = ["--profile", profile];
  const agents = json(openclaw, [...args, "config", "get", "agents.list", "--json"]);
  const mainAgent = agents.find((item) => item.id === "main");
  const emailAgent = agents.find((item) => item.id === "email-outreach");
  assert(emailAgent, "email-outreach agent is missing");
  assert(mainAgent?.tools?.deny?.includes("exec"), "main research agent must deny exec");
  assert(emailAgent.skills?.includes("ark-email-outreach"), "email agent skill allowlist is missing ark-email-outreach");
  assert(emailAgent.skills?.includes("agently-mail"), "email agent skill allowlist is missing agently-mail");
  assert(emailAgent.tools?.alsoAllow?.includes("ark-sales__ark_get_lead"), "email agent lacks read-only Ark lead access");
  assert(emailAgent.tools?.deny?.includes("web_search"), "email agent must not conduct fresh web research");
  assert(emailAgent.tools?.deny?.includes("process"), "email agent must not manage background shell sessions");

  for (const path of [queueBin, dispatchBin, skillReaderBin]) await assertPrivateExecutable(path);
  const approvals = json(openclaw, [...args, "approvals", "get", "--json"]).file;
  assert(approvals.agents.main.security === "deny", "main exec approval policy must be deny");
  const emailPolicy = approvals.agents["email-outreach"];
  assert(emailPolicy.security === "allowlist", "email exec approval policy must be allowlist");
  assert(emailPolicy.ask === "on-miss" && emailPolicy.askFallback === "deny",
    "email confirm must require a reachable human approval surface");
  const queueApproval = emailPolicy.allowlist.find((item) => item.pattern === queueBin);
  const skillReaderApproval = emailPolicy.allowlist.find((item) => item.pattern === skillReaderBin);
  assert(emailPolicy.allowlist.length === 2 && queueApproval,
    "email agent must only execute the queue command and its skill reader");
  assert(queueApproval.argPattern === "^(?:schedule|preview|list)(?:[\\s\\S]*)$",
    "email queue approval must restrict the allowed subcommands");
  assert(!queueApproval.argPattern.includes("confirm"),
    "email agent must not be able to self-confirm a preview");
  assert(skillReaderApproval?.argPattern === "^(?:outreach|course|localization|negotiation|agent-mail)$",
    "email skill reader must be restricted to the installed skill files");

  for (const skill of ["ark-email-outreach", "agently-mail"]) {
    const info = json(openclaw, [...args, "skills", "info", skill, "--agent", "email-outreach", "--json"]);
    assert(info.eligible !== false, `${skill} is not eligible for the email agent`);
  }
  const toolsText = await readFile(join(stateDir, "workspace-email-outreach", "TOOLS.md"), "utf8");
  assert(toolsText.includes(queueBin), "email workspace does not contain the installed queue path");
  assert(toolsText.includes(skillReaderBin), "email workspace does not contain the installed skill-reader path");

  run(openclaw, [...args, "config", "validate"]);
  run(openclaw, [...args, "secrets", "audit", "--check"]);
  run(openclaw, [...args, "gateway", "status", "--require-rpc"]);
  const launchLabel = `com.leshine.${profile}.outreach-dispatch`;
  const launch = run("launchctl", ["print", `gui/${process.getuid()}/${launchLabel}`], { capture: true });
  assert(launch.includes(`program = ${dispatchBin}`), "dispatcher LaunchAgent does not use the installed binary");

  const mailbox = json(join(nodeDir, "agently-cli"), ["+me"], { env: { AGENTLY_WORKSPACE: "ark-sales" } });
  const email = mailbox?.data?.email || mailbox?.data?.mailbox?.email
    || mailbox?.data?.aliases?.find((item) => item.is_primary)?.email
    || mailbox?.data?.aliases?.[0]?.email || mailbox?.email;
  assert(email, "Agent Mail mailbox identity is unavailable");
  process.stdout.write(`Email agent verification passed. Mailbox: ${email}\n`);
  process.stdout.write(`Queue: ${queueBin}\nDispatcher: ${launchLabel}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
