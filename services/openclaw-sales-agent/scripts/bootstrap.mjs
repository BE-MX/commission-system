#!/usr/bin/env node

import { randomBytes } from "node:crypto";
import { chmod, copyFile, lstat, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
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
const mainWorkspace = join(workspace, "main");
const secretsDir = join(stateDir, "secrets");
const arkTokenFile = join(secretsDir, "ark-agent-token");
const heartbeatTokenFile = join(secretsDir, "runtime-heartbeat-token");
const mimoTokenFile = join(secretsDir, "mimo-api-key");
const deepseekTokenFile = join(secretsDir, "deepseek-api-key");
const openclaw = process.env.OPENCLAW_BIN || join(home, ".openclaw/bin/openclaw");
const node = process.env.OPENCLAW_NODE || join(home, ".openclaw/tools/node/bin/node");
const parallelPlugin = process.env.OPENCLAW_PARALLEL_PLUGIN
  || "@openclaw/parallel-plugin@2026.8.1";
const envFile = join(stateDir, ".env");
const mainHeartbeat = {
  every: "5m",
  target: "none",
  lightContext: true,
  isolatedSession: true,
  timeoutSeconds: 1800,
};

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

function getConfig(path) {
  return JSON.parse(run(openclaw, ["--profile", profile, "config", "get", path, "--json"], { capture: true }));
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
    "# Set true after creating secrets/runtime-heartbeat-token (0600) and registering its SHA-256 in Ark.",
    "ARK_HEARTBEAT_ENABLED=false",
    "",
    "# Model keys belong in private files under secrets/; see README.",
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

async function migrateModelKeyToSecretFile(envName, tokenFile, providerLabel) {
  const contents = await readFile(envFile, "utf8");
  let key = null;
  const retained = [];
  for (const line of contents.split(/\r?\n/u)) {
    const prefix = `${envName}=`;
    if (line.startsWith(prefix) && line.slice(prefix.length).trim()) {
      key = line.slice(prefix.length).trim();
      continue;
    }
    retained.push(line);
  }
  if (key) {
    try {
      const existing = await lstat(tokenFile);
      if (!existing.isFile() || existing.isSymbolicLink()
        || (typeof process.getuid === "function" && existing.uid !== process.getuid())) {
        throw new Error(`${tokenFile} must be a current-user regular file, not a symlink`);
      }
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    const temporaryFile = `${tokenFile}.${process.pid}.${randomBytes(8).toString("hex")}.tmp`;
    try {
      await writeFile(temporaryFile, `${key.replace(/^['"]|['"]$/gu, "")}\n`, {
        encoding: "utf8", mode: 0o600, flag: "wx",
      });
      await rename(temporaryFile, tokenFile);
    } catch (error) {
      await rm(temporaryFile, { force: true });
      throw error;
    }
    await writeFile(envFile, `${retained.join("\n").replace(/\n+$/u, "")}\n`, {
      encoding: "utf8", mode: 0o600,
    });
  }
  let metadata;
  try {
    metadata = await lstat(tokenFile);
  } catch {
    throw new Error(`${providerLabel} key is missing; store it as the only line in ${tokenFile} before bootstrap`);
  }
  if (!metadata.isFile() || metadata.isSymbolicLink()
    || (typeof process.getuid === "function" && metadata.uid !== process.getuid())) {
    throw new Error(`${tokenFile} must be a current-user regular file, not a symlink`);
  }
  if (!(await readFile(tokenFile, "utf8")).trim()) {
    throw new Error(`${tokenFile} must contain one non-empty key`);
  }
  await chmod(tokenFile, 0o600);
}

async function installWorkspaceTemplates() {
  await mkdir(mainWorkspace, { recursive: true, mode: 0o700 });
  const mappings = [
    ["AGENTS.template.md", "AGENTS.md", false],
    ["SOUL.template.md", "SOUL.md", false],
    ["USER.template.md", "USER.md", false],
    // HEARTBEAT.md is managed automation policy, not user-authored memory.
    ["HEARTBEAT.template.md", "HEARTBEAT.md", true],
  ];
  for (const [source, target, managed] of mappings) {
    if (managed) {
      await copyFile(join(serviceDir, "workspace-template", source), join(mainWorkspace, target));
      continue;
    }
    try {
      await readFile(join(mainWorkspace, target));
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      await copyFile(join(serviceDir, "workspace-template", source), join(mainWorkspace, target));
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
    ...(values.ARK_HEARTBEAT_ENABLED === "true"
      ? { ARK_HEARTBEAT_TOKEN_FILE: heartbeatTokenFile }
      : {}),
  };
}

function setConfig(path, value, { replace = false } = {}) {
  const args = ["--profile", profile, "config", "set", path, JSON.stringify(value), "--strict-json"];
  if (replace) args.push("--replace");
  run(openclaw, args);
}

function clearDefaultHeartbeat() {
  const defaults = JSON.parse(run(openclaw, [
    "--profile", profile, "config", "get", "agents.defaults",
  ], { capture: true }));
  if (Object.hasOwn(defaults, "heartbeat")) {
    run(openclaw, ["--profile", profile, "config", "unset", "agents.defaults.heartbeat"]);
  }
}

function configureMainAgentTools() {
  const main = JSON.parse(run(openclaw, [
    "--profile", profile, "config", "get", "agents.entries.main",
  ], { capture: true }));
  if (!main) throw new Error("OpenClaw baseline did not create the main agent");
  main.workspace = mainWorkspace;
  main.tools = {
    ...(main.tools || {}),
    profile: "minimal",
    alsoAllow: ["read", "web_search", "web_fetch", "ark-sales__*"],
    deny: [
      "exec", "process", "write", "edit", "apply_patch", "browser",
      "group:messaging", "group:sessions", "cron",
    ],
    fs: { ...(main.tools?.fs || {}), workspaceOnly: true },
  };
  // Keep queue automation scoped to the sales agent. A defaults-level
  // heartbeat would silently schedule unrelated agents such as email outreach.
  main.heartbeat = mainHeartbeat;
  setConfig("agents.entries.main", main);
}

async function main() {
  await ensureEnvFile();
  await migrateModelKeyToSecretFile("MIMO_API_KEY", mimoTokenFile, "MiMo");
  await migrateModelKeyToSecretFile("DEEPSEEK_API_KEY", deepseekTokenFile, "DeepSeek");
  await installWorkspaceTemplates();
  const arkRuntimeSettings = await loadArkRuntimeSettings();

  if (Object.keys(getConfig("agents.entries") || {}).length === 0) {
    run(openclaw, ["--profile", profile, "setup", "--baseline", "--workspace", workspace]);
  }
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
  setConfig("agents.defaults.model", { primary: "mimo/mimo-v2.5" });
  setConfig("agents.defaults.models", {
    "mimo/mimo-v2.5": { agentRuntime: { id: "openclaw" } },
    "deepseek/deepseek-v4-flash": { agentRuntime: { id: "openclaw" } },
    "deepseek/deepseek-v4-pro": { agentRuntime: { id: "openclaw" } },
  }, { replace: true });
  setConfig("secrets.providers.mimo_key_file", {
    source: "file", path: mimoTokenFile, mode: "singleValue",
  });
  setConfig("models.providers.mimo", {
    baseUrl: "https://token-plan-cn.xiaomimimo.com/v1",
    apiKey: { source: "file", provider: "mimo_key_file", id: "value" },
    api: "openai-completions",
    agentRuntime: { id: "openclaw" },
    models: [{
      id: "mimo-v2.5",
      name: "MiMo V2.5",
      reasoning: true,
      input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 200000,
      maxTokens: 8192,
      api: "openai-completions",
    }],
  });
  setConfig("secrets.providers.deepseek_key_file", {
    source: "file", path: deepseekTokenFile, mode: "singleValue",
  });
  setConfig("models.providers.deepseek.apiKey", {
    source: "file", provider: "deepseek_key_file", id: "value",
  });
  setConfig("agents.defaults.skills", [
    "ark-lead-discovery", "ark-company-research", "ark-public-pool-research",
  ]);
  setConfig("tools.profile", "minimal");
  setConfig("tools.alsoAllow", ["read", "web_search", "web_fetch", "ark-sales__*"]);
  setConfig("tools.deny", [
    "process", "write", "edit", "apply_patch", "browser",
    "group:messaging", "group:sessions", "cron",
  ]);
  setConfig("tools.exec", {
    host: "gateway", security: "allowlist", ask: "off", strictInlineEval: true,
  });
  setConfig("tools.agentToAgent.enabled", false);
  clearDefaultHeartbeat();
  configureMainAgentTools();
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
      "--agent", "main", "--as", skill, "--force",
    ]);
  }

  run(openclaw, ["--profile", profile, "config", "validate"]);
  run(openclaw, ["--profile", profile, "gateway", "install", "--force", "--json"]);
  process.stdout.write(`\nOpenClaw profile '${profile}' prepared at ${stateDir}.\n`);
  process.stdout.write(`Add the Ark token to ${arkTokenFile} (mode 0600).\n`);
  process.stdout.write(`Optional runtime heartbeat token file: ${heartbeatTokenFile} (mode 0600).\n`);
  process.stdout.write(`Add the MiMo API key as the only line in ${mimoTokenFile} (mode 0600).\n`);
  process.stdout.write(`Add the DeepSeek API key as the only line in ${deepseekTokenFile} (mode 0600).\n`);
}

main().catch((error) => {
  process.stderr.write(`Bootstrap failed: ${error.message}\n`);
  process.exitCode = 1;
});
