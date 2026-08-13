#!/usr/bin/env node

import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { lstatSync } from "node:fs";

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
if (modelPolicies?.["deepseek/deepseek-v4-pro"]?.agentRuntime?.id !== "openclaw") {
  throw new Error("deepseek/deepseek-v4-pro must be pinned to the built-in openclaw runtime");
}
process.stdout.write("Runtime policy OK: deepseek/deepseek-v4-pro -> openclaw (no Codex native shell).\n");

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
