#!/usr/bin/env node

import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { lstatSync, readFileSync } from "node:fs";

const home = homedir();
const profile = process.env.OPENCLAW_PROFILE || "ark-sales";
const stateDir = join(home, `.openclaw-${profile}`);
const openclaw = process.env.OPENCLAW_BIN || join(home, ".openclaw/bin/openclaw");
const node = process.env.OPENCLAW_NODE || join(home, ".openclaw/tools/node/bin/node");
const rawConfig = JSON.parse(readFileSync(join(stateDir, "openclaw.json"), "utf8"));

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
const mimoProvider = rawConfig?.models?.providers?.mimo;
const mimoSecretProvider = rawConfig?.secrets?.providers?.mimo_key_file;
if (defaultModel?.primary !== "mimo/mimo-v2.5") {
  throw new Error("default model must be mimo/mimo-v2.5");
}
if (modelPolicies?.["mimo/mimo-v2.5"]?.agentRuntime?.id !== "openclaw") {
  throw new Error("mimo/mimo-v2.5 must be pinned to the built-in openclaw runtime");
}
if (mimoProvider?.baseUrl !== "https://token-plan-cn.xiaomimimo.com/v1"
  || mimoProvider?.api !== "openai-completions"
  || mimoProvider?.apiKey?.source !== "file"
  || mimoProvider?.apiKey?.provider !== "mimo_key_file"
  || mimoProvider?.apiKey?.id !== "value"
  || mimoProvider?.models?.[0]?.id !== "mimo-v2.5") {
  throw new Error("MiMo provider must use the pinned endpoint, model, and file SecretRef");
}
const expectedMimoKeyFile = join(stateDir, "secrets", "mimo-api-key");
if (mimoSecretProvider?.source !== "file" || mimoSecretProvider?.mode !== "singleValue"
  || mimoSecretProvider?.path !== expectedMimoKeyFile) {
  throw new Error("MiMo key provider must read the profile-private mimo-api-key file");
}
const modelList = captureJson(openclaw, ["--profile", profile, "models", "list", "--json"]);
const listedMimo = modelList?.models?.find((model) => model.key === "mimo/mimo-v2.5");
if (!listedMimo?.available || !listedMimo?.tags?.includes("default")) {
  throw new Error("mimo/mimo-v2.5 must be available and tagged as the default model");
}
process.stdout.write("Runtime policy OK: default mimo/mimo-v2.5 -> openclaw (no Codex native shell).\n");

const requiredReadTools = ["read", "web_search", "web_fetch", "ark-sales__*"];
const requiredDeniedTools = ["process", "write", "edit", "apply_patch"];

function assertReadOnlySkillPolicy(tools, label, { requireExecDenied = false } = {}) {
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
  if (requireExecDenied && !tools?.deny?.includes("exec")) {
    throw new Error(`${label} must deny exec`);
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
assertReadOnlySkillPolicy(mainAgent.tools, "main agent", { requireExecDenied: true });
const emailAgent = agents.find((agent) => agent.id === "email-outreach");
if (!emailAgent) throw new Error("email-outreach agent is missing");
if (emailAgent.model !== "deepseek/deepseek-v4-pro") {
  throw new Error("email-outreach agent must keep its deepseek/deepseek-v4-pro override");
}

const heartbeatFile = join(stateDir, "workspace", "HEARTBEAT.md");
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

function assertPrivateSecretFile(tokenFile, label) {
  const info = lstatSync(tokenFile);
  if (!info.isFile() || info.isSymbolicLink() || (info.mode & 0o777) !== 0o600) {
    throw new Error(`${label} must be a regular non-symlink file with mode 0600`);
  }
  if (typeof process.getuid === "function" && info.uid !== process.getuid()) {
    throw new Error(`${label} must be owned by the current user`);
  }
}

const secretsDir = join(stateDir, "secrets");
assertPrivateSecretFile(join(secretsDir, "mimo-api-key"), "MiMo key file");
assertPrivateSecretFile(join(secretsDir, "deepseek-api-key"), "DeepSeek key file");
try {
  assertPrivateSecretFile(join(secretsDir, "ark-agent-token"), "Ark token file");
  process.stdout.write("Ark and model secret file permissions OK.\n");
} catch (error) {
  if (error?.code === "ENOENT") {
    process.stdout.write("Model secret file permissions OK; Ark token file is intentionally absent.\n");
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
