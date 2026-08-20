#!/usr/bin/env node

import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { lstatSync, readFileSync } from "node:fs";

const home = homedir();
const profile = process.env.OPENCLAW_PROFILE || "ark-sales";
const openclaw = process.env.OPENCLAW_BIN || join(home, ".openclaw/bin/openclaw");
const node = process.env.OPENCLAW_NODE || join(home, ".openclaw/tools/node/bin/node");

function run(command, args, { allowFailure = false } = {}) {
  const result = spawnSync(command, args, {
    env: { ...process.env, PATH: `${dirname(node)}:${process.env.PATH || ""}` },
    encoding: "utf8",
    stdio: "inherit",
  });
  if (!allowFailure && result.status !== 0) {
    throw new Error(`${command} exited with status ${result.status}`);
  }
  return result.status;
}

function captureJson(command, args) {
  const result = spawnSync(command, args, {
    env: { ...process.env, PATH: `${dirname(node)}:${process.env.PATH || ""}` },
    encoding: "utf8",
    stdio: "pipe",
  });
  if (result.status !== 0) {
    if (result.stderr) process.stderr.write(result.stderr);
    throw new Error(`${command} exited with status ${result.status}`);
  }
  return JSON.parse(result.stdout);
}

const modelPolicies = captureJson(openclaw, [
  "--profile", profile, "config", "get", "agents.defaults.models",
]);
const defaultModel = captureJson(openclaw, [
  "--profile", profile, "config", "get", "agents.defaults.model",
]);
if (defaultModel?.primary !== "deepseek/deepseek-v4-flash") {
  throw new Error("default model must be deepseek/deepseek-v4-flash");
}
if (modelPolicies?.["deepseek/deepseek-v4-flash"]?.agentRuntime?.id !== "openclaw") {
  throw new Error("deepseek/deepseek-v4-flash must be pinned to the built-in openclaw runtime");
}
process.stdout.write("Runtime policy OK: default deepseek/deepseek-v4-flash -> openclaw (no Codex native shell).\n");

const requiredReadTools = ["read", "web_search", "web_fetch", "ark-sales__*"];
const requiredDeniedTools = ["exec", "process", "write", "edit", "apply_patch"];

function assertReadOnlySkillPolicy(tools, label) {
  if (tools?.profile !== "minimal") throw new Error(`${label} tools.profile must be minimal`);
  if (tools?.fs?.workspaceOnly !== true) {
    throw new Error(`${label} tools.fs.workspaceOnly must be true`);
  }
  for (const tool of requiredReadTools) {
    if (!tools?.alsoAllow?.includes(tool)) throw new Error(`${label} must allow ${tool}`);
  }
  for (const tool of requiredDeniedTools) {
    if (!tools?.deny?.includes(tool)) throw new Error(`${label} must deny ${tool}`);
  }
  if (tools?.deny?.includes("group:fs")) {
    throw new Error(`${label} must not deny group:fs because skills require read`);
  }
}

const globalTools = captureJson(openclaw, [
  "--profile", profile, "config", "get", "tools",
]);
assertReadOnlySkillPolicy(globalTools, "global");
const agents = captureJson(openclaw, [
  "--profile", profile, "config", "get", "agents.list",
]);
const mainAgent = agents.find((agent) => agent.id === "main");
if (!mainAgent) throw new Error("main agent is missing");
assertReadOnlySkillPolicy(mainAgent.tools, "main agent");

const heartbeatFile = join(home, `.openclaw-${profile}`, "workspace", "HEARTBEAT.md");
const heartbeatPolicy = readFileSync(heartbeatFile, "utf8");
for (const marker of [
  "$ark-lead-discovery", "ark_list_search_jobs", "profile", "criteria", "target_count <= 20",
]) {
  if (!heartbeatPolicy.includes(marker)) {
    throw new Error(`HEARTBEAT.md is missing search queue marker: ${marker}`);
  }
}
const defaultAgentConfig = captureJson(openclaw, [
  "--profile", profile, "config", "get", "agents.defaults",
]);
if (Object.hasOwn(defaultAgentConfig, "heartbeat")) {
  throw new Error("heartbeat must not be configured in agents.defaults");
}
const unexpectedHeartbeatAgents = agents.filter(
  (agent) => agent.id !== "main" && Object.hasOwn(agent, "heartbeat"),
);
if (unexpectedHeartbeatAgents.length > 0) {
  throw new Error(`heartbeat must be main-only; found: ${unexpectedHeartbeatAgents.map((agent) => agent.id).join(", ")}`);
}
const heartbeatConfig = mainAgent.heartbeat;
if (heartbeatConfig?.lightContext !== true || heartbeatConfig?.isolatedSession !== true) {
  throw new Error("heartbeat must use a light, isolated session so stale chat history cannot override policy");
}
if (heartbeatConfig?.every !== "5m" || heartbeatConfig?.target !== "none") {
  throw new Error("main heartbeat must run every 5 minutes without sending chat messages");
}
if (heartbeatConfig?.skipWhenBusy !== true || heartbeatConfig?.timeoutSeconds <= 900) {
  throw new Error("heartbeat must avoid overlap and outlast Ark's 15-minute initial lease");
}
process.stdout.write("Skill read policy and main-only search heartbeat policy OK.\n");

const tokenFile = join(home, `.openclaw-${profile}`, "secrets", "ark-agent-token");
try {
  const info = lstatSync(tokenFile);
  if (!info.isFile() || info.isSymbolicLink() || (info.mode & 0o777) !== 0o600) {
    throw new Error("Ark token file must be a regular non-symlink file with mode 0600");
  }
  process.stdout.write("Ark token file permissions OK.\n");
} catch (error) {
  if (error?.code === "ENOENT") {
    process.stdout.write("Credential pending: Ark token file is intentionally absent.\n");
  } else {
    throw error;
  }
}

run(openclaw, ["--profile", profile, "config", "validate"]);
run(openclaw, ["--profile", profile, "skills", "check"]);
run(openclaw, ["--profile", profile, "mcp", "doctor", "ark-sales"]);
run(openclaw, ["--profile", profile, "infer", "web", "providers", "--json"]);
run(openclaw, ["--profile", profile, "gateway", "status", "--require-rpc", "--json"]);

process.stdout.write("Local runtime verification complete. A hardened full Ark turn requires ARK_AGENT_TOKEN + model provider API auth.\n");
