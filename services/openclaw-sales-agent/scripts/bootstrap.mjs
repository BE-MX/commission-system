#!/usr/bin/env node

import { randomBytes } from "node:crypto";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const serviceDir = resolve(scriptDir, "..");
const repoRoot = resolve(serviceDir, "../..");
const home = homedir();
const profile = process.env.OPENCLAW_PROFILE || "ark-sales";
const stateDir = join(home, `.openclaw-${profile}`);
const workspace = join(stateDir, "workspace");
const secretsDir = join(stateDir, "secrets");
const arkTokenFile = join(secretsDir, "ark-agent-token");
const openclaw = process.env.OPENCLAW_BIN || join(home, ".openclaw/bin/openclaw");
const node = process.env.OPENCLAW_NODE || join(home, ".openclaw/tools/node/bin/node");
const parallelPlugin = process.env.OPENCLAW_PARALLEL_PLUGIN
  || "@openclaw/parallel-plugin@2026.7.1";
const envFile = join(stateDir, ".env");

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || repoRoot,
    env: { ...process.env, PATH: `${dirname(node)}:${process.env.PATH || ""}` },
    encoding: "utf8",
    stdio: options.capture ? "pipe" : "inherit",
  });
  if (result.status !== 0) {
    if (options.capture && result.stderr) process.stderr.write(result.stderr);
    throw new Error(`${command} exited with status ${result.status}`);
  }
  return result.stdout || "";
}

async function ensureEnvFile() {
  await mkdir(stateDir, { recursive: true, mode: 0o700 });
  await mkdir(secretsDir, { recursive: true, mode: 0o700 });
  let current = "";
  try {
    current = await readFile(envFile, "utf8");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  if (current) return;
  const gatewayToken = randomBytes(32).toString("hex");
  const template = [
    `OPENCLAW_GATEWAY_TOKEN=${gatewayToken}`,
    "ARK_BASE_URL=https://leshine.work",
    "ARK_ALLOWED_ORIGIN=https://leshine.work",
    "ARK_AGENT_ID=openclaw-sales-01",
    "ARK_API_TIMEOUT_MS=30000",
    "",
    "# Required by the hardened built-in OpenClaw runtime (current default provider):",
    "# DEEPSEEK_API_KEY=",
    "# Optional alternative providers:",
    "# OPENAI_API_KEY=",
    "# ANTHROPIC_API_KEY=",
    "# GEMINI_API_KEY=",
    "",
    "# Parallel Free is the default key-free search provider.",
    "# Optional paid collection-source upgrades:",
    "# BRAVE_API_KEY=",
    "# TAVILY_API_KEY=",
    "# FIRECRAWL_API_KEY=",
    "",
  ].join("\n");
  await writeFile(envFile, template, { encoding: "utf8", mode: 0o600, flag: "wx" });
}

async function installWorkspaceTemplates() {
  await mkdir(workspace, { recursive: true, mode: 0o700 });
  const mappings = [
    ["AGENTS.template.md", "AGENTS.md"],
    ["SOUL.template.md", "SOUL.md"],
    ["USER.template.md", "USER.md"],
  ];
  for (const [source, target] of mappings) {
    try {
      await readFile(join(workspace, target));
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      await copyFile(join(serviceDir, "workspace-template", source), join(workspace, target));
    }
  }
}

async function loadArkRuntimeSettings() {
  const values = {};
  const contents = await readFile(envFile, "utf8");
  for (const rawLine of contents.split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator < 1) continue;
    const key = line.slice(0, separator).trim();
    let value = line.slice(separator + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"'))
      || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    values[key] = value;
  }

  const baseUrl = values.ARK_BASE_URL || "https://leshine.work";
  const allowedOrigin = values.ARK_ALLOWED_ORIGIN || "https://leshine.work";
  const parsedBase = new URL(baseUrl);
  const parsedAllowed = new URL(allowedOrigin);
  if (!["http:", "https:"].includes(parsedBase.protocol)
    || parsedBase.username
    || parsedBase.password
    || parsedBase.search
    || parsedBase.hash
    || parsedBase.origin !== parsedAllowed.origin
    || parsedAllowed.username
    || parsedAllowed.password
    || parsedAllowed.pathname !== "/"
    || parsedAllowed.search
    || parsedAllowed.hash) {
    throw new Error("ARK_BASE_URL and ARK_ALLOWED_ORIGIN must use the same exact HTTP(S) origin");
  }

  const timeoutMs = Number.parseInt(values.ARK_API_TIMEOUT_MS || "30000", 10);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1000 || timeoutMs > 120000) {
    throw new Error("ARK_API_TIMEOUT_MS must be an integer between 1000 and 120000");
  }
  const agentId = values.ARK_AGENT_ID || "openclaw-sales-01";
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/u.test(agentId)) {
    throw new Error("ARK_AGENT_ID must be 1-96 safe identifier characters");
  }

  return {
    ARK_BASE_URL: parsedBase.href.replace(/\/+$/, ""),
    ARK_ALLOWED_ORIGIN: parsedAllowed.origin,
    ARK_AGENT_ID: agentId,
    ARK_AGENT_TOKEN_FILE: arkTokenFile,
    ARK_API_TIMEOUT_MS: String(timeoutMs),
  };
}

function setConfig(path, value) {
  run(openclaw, ["--profile", profile, "config", "set", path, JSON.stringify(value), "--strict-json"]);
}

async function main() {
  await ensureEnvFile();
  await installWorkspaceTemplates();
  const arkRuntimeSettings = await loadArkRuntimeSettings();

  run(openclaw, ["--profile", profile, "setup", "--baseline", "--workspace", workspace, "--skip-ui"]);
  run(openclaw, [
    "--profile", profile, "plugins", "install", parallelPlugin, "--pin", "--force",
  ]);
  setConfig("gateway.mode", "local");
  setConfig("gateway.port", 18791);
  setConfig("gateway.bind", "loopback");
  setConfig("gateway.auth.mode", "token");
  run(openclaw, [
    "--profile", profile, "config", "set", "gateway.auth.token",
    "--ref-provider", "default", "--ref-source", "env", "--ref-id", "OPENCLAW_GATEWAY_TOKEN",
  ]);
  setConfig("gateway.terminal.enabled", false);
  setConfig("gateway.controlUi.enabled", true);
  setConfig("agents.defaults.workspace", workspace);
  setConfig("agents.defaults.model", { primary: "deepseek/deepseek-v4-flash" });
  setConfig("agents.defaults.models", {
    "deepseek/deepseek-v4-flash": { agentRuntime: { id: "openclaw" } },
  });
  setConfig("agents.defaults.skills", [
    "ark-lead-discovery", "ark-company-research", "ark-public-pool-research",
  ]);
  setConfig("plugins.entries.codex.config.appServer", {
    mode: "guardian",
    approvalPolicy: "on-request",
    approvalsReviewer: "auto_review",
    sandbox: "workspace-write",
    clearEnv: [
      "OPENCLAW_GATEWAY_TOKEN",
      "DEEPSEEK_API_KEY",
      "OPENAI_API_KEY",
      "ARK_AGENT_TOKEN",
      "ARK_AGENT_TOKEN_FILE",
      "ARK_BASE_URL",
      "ARK_ALLOWED_ORIGIN",
      "ARK_AGENT_ID",
    ],
  });
  setConfig("tools.profile", "minimal");
  setConfig("tools.alsoAllow", ["web_search", "web_fetch", "ark-sales__*"]);
  setConfig("tools.deny", [
    "exec", "process", "group:fs", "browser", "group:messaging", "group:sessions", "cron",
  ]);
  setConfig("plugins.entries.parallel.enabled", true);
  // Keep DuckDuckGo installed as a manual fallback, but Parallel Free is the
  // tested default on networks where DuckDuckGo HTML is unavailable.
  setConfig("plugins.entries.duckduckgo.enabled", true);
  setConfig("tools.web.search", {
    enabled: true,
    provider: "parallel-free",
    maxResults: 8,
    timeoutSeconds: 30,
    cacheTtlMinutes: 15,
  });
  setConfig("tools.web.fetch.enabled", true);
  setConfig("browser.enabled", false);

  const mcpDefinition = {
    command: node,
    args: [join(serviceDir, "src/server.mjs")],
    cwd: serviceDir,
    env: arkRuntimeSettings,
    toolFilter: { include: ["ark_*"] },
  };
  run(openclaw, ["--profile", profile, "mcp", "set", "ark-sales", JSON.stringify(mcpDefinition)]);

  for (const skill of [
    "ark-lead-discovery", "ark-company-research", "ark-public-pool-research",
  ]) {
    run(openclaw, [
      "--profile", profile,
      "skills", "install", join(repoRoot, ".agents/skills", skill),
      "--as", skill, "--force",
    ]);
  }

  run(openclaw, ["--profile", profile, "config", "validate"]);
  run(openclaw, ["--profile", profile, "gateway", "install", "--force", "--json"]);
  process.stdout.write(`\nOpenClaw profile '${profile}' prepared at ${stateDir}.\n`);
  process.stdout.write(`Add the Ark token to ${arkTokenFile} (mode 0600).\n`);
  process.stdout.write(`Add DEEPSEEK_API_KEY to ${envFile} for the hardened OpenClaw runtime.\n`);
}

main().catch((error) => {
  process.stderr.write(`Bootstrap failed: ${error.message}\n`);
  process.exitCode = 1;
});
