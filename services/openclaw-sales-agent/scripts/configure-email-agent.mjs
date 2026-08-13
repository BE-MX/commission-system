#!/usr/bin/env node

import { chmod, copyFile, lstat, mkdir, readFile, writeFile } from "node:fs/promises";
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
const emailAgentId = "email-outreach";
const emailWorkspace = join(stateDir, "workspace-email-outreach");
const emailAgentDir = join(stateDir, "agents", emailAgentId, "agent");
const binDir = join(stateDir, "bin");
const queueBin = join(binDir, "outreach-queue");
const dispatchBin = join(binDir, "outreach-dispatch");
const skillReaderBin = join(binDir, "outreach-skill-reader");
const queueDir = join(stateDir, "outreach-queue");
const secretsDir = join(stateDir, "secrets");
const envFile = join(stateDir, ".env");
const deepseekTokenFile = join(secretsDir, "deepseek-api-key");
const openclaw = process.env.OPENCLAW_BIN || join(home, ".openclaw", "bin", "openclaw");
const nodeDir = join(home, ".openclaw", "tools", "node", "bin");
const node = process.env.OPENCLAW_NODE || join(nodeDir, "node");
const launchAgentPath = join(home, "Library", "LaunchAgents", `com.leshine.${profile}.outreach-dispatch.plist`);

function validateProfileName(value) {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/u.test(value)) {
    throw new Error("OPENCLAW_PROFILE must be a safe 1-64 character identifier");
  }
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || repoRoot,
    env: { ...process.env, ...(options.env || {}), PATH: `${nodeDir}:${process.env.PATH || ""}` },
    encoding: "utf8",
    input: options.input,
    stdio: options.capture || options.input ? "pipe" : "inherit",
  });
  if (result.status !== 0) {
    if (result.stdout) process.stderr.write(result.stdout);
    if (result.stderr) process.stderr.write(result.stderr);
    throw new Error(`${command} exited with status ${result.status}`);
  }
  return result.stdout || "";
}

function getConfig(path) {
  try {
    return JSON.parse(run(openclaw, ["--profile", profile, "config", "get", path, "--json"], { capture: true }));
  } catch {
    return undefined;
  }
}

function setConfig(path, value) {
  run(openclaw, ["--profile", profile, "config", "set", path, JSON.stringify(value), "--strict-json"]);
}

async function installBinaries() {
  run(node, [join(scriptDir, "build-email-tools.mjs")], { cwd: serviceDir });
  await mkdir(binDir, { recursive: true, mode: 0o700 });
  await copyFile(join(serviceDir, "dist", "outreach-queue"), queueBin);
  await copyFile(join(serviceDir, "dist", "outreach-dispatch"), dispatchBin);
  await copyFile(join(serviceDir, "dist", "outreach-skill-reader"), skillReaderBin);
  await Promise.all([queueBin, dispatchBin, skillReaderBin].map((path) => chmod(path, 0o700)));
  await mkdir(queueDir, { recursive: true, mode: 0o700 });
}

async function configureModelSecret() {
  await mkdir(secretsDir, { recursive: true, mode: 0o700 });
  let contents = "";
  try {
    contents = await readFile(envFile, "utf8");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  let key = null;
  const retained = [];
  for (const line of contents.split(/\r?\n/u)) {
    if (line.startsWith("DEEPSEEK_API_KEY=") && line.slice("DEEPSEEK_API_KEY=".length).trim()) {
      key = line.slice("DEEPSEEK_API_KEY=".length).trim().replace(/^['"]|['"]$/gu, "");
      continue;
    }
    retained.push(line);
  }
  if (key) {
    await writeFile(deepseekTokenFile, `${key}\n`, { encoding: "utf8", mode: 0o600 });
    await writeFile(envFile, `${retained.join("\n").replace(/\n+$/u, "")}\n`, {
      encoding: "utf8", mode: 0o600,
    });
  }
  const metadata = await lstat(deepseekTokenFile).catch(() => {
    throw new Error(`DeepSeek key is missing; store it as the only line in ${deepseekTokenFile}`);
  });
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    throw new Error(`${deepseekTokenFile} must be a regular file, not a symlink`);
  }
  if (typeof process.getuid === "function" && metadata.uid !== process.getuid()) {
    throw new Error(`${deepseekTokenFile} must belong to the current user`);
  }
  const secretValue = (await readFile(deepseekTokenFile, "utf8")).trim();
  if (!secretValue) throw new Error(`${deepseekTokenFile} must contain one non-empty key`);
  await chmod(deepseekTokenFile, 0o600);
  setConfig("secrets.providers.deepseek_key_file", {
    source: "file", path: deepseekTokenFile, mode: "singleValue",
  });
  setConfig("models.providers.deepseek.apiKey", {
    source: "file", provider: "deepseek_key_file", id: "value",
  });
}

async function installWorkspace() {
  await mkdir(emailWorkspace, { recursive: true, mode: 0o700 });
  for (const name of ["AGENTS", "SOUL", "USER", "TOOLS"]) {
    const template = await readFile(join(serviceDir, "email-workspace-template", `${name}.template.md`), "utf8");
    const content = template.replaceAll("{{OUTREACH_QUEUE_BIN}}", queueBin);
    const rendered = content
      .replaceAll("{{OUTREACH_SKILL_READER_BIN}}", skillReaderBin)
      .replaceAll("{{EMAIL_WORKSPACE}}", emailWorkspace);
    await writeFile(join(emailWorkspace, `${name}.md`), rendered, { encoding: "utf8", mode: 0o600 });
  }
}

function configureAgents() {
  const agents = getConfig("agents.list") || [];
  const byId = new Map(agents.map((agent) => [agent.id, agent]));
  const unexpected = [...byId.keys()].filter((id) => !["main", emailAgentId].includes(id));
  if (unexpected.length) {
    throw new Error(`Dedicated ${profile} profile has unexpected agents: ${unexpected.join(", ")}`);
  }
  const main = byId.get("main") || { id: "main" };
  byId.set("main", {
    ...main,
    tools: {
      profile: "minimal",
      alsoAllow: ["web_search", "web_fetch", "ark-sales__*"],
      deny: ["exec", "process", "group:fs", "browser", "group:messaging", "group:sessions", "cron"],
    },
  });
  const model = getConfig("agents.defaults.model")?.primary || "deepseek/deepseek-v4-pro";
  byId.set(emailAgentId, {
    ...(byId.get(emailAgentId) || {}),
    id: emailAgentId,
    name: "方舟邮件外联专员",
    workspace: emailWorkspace,
    agentDir: emailAgentDir,
    model,
    identity: {
      name: "方舟邮件外联专员",
      theme: "证据优先、母语化表达、收件人本地工作时间发送",
      emoji: "✉️",
    },
    skills: ["ark-email-outreach", "agently-mail"],
    tools: {
      profile: "minimal",
      alsoAllow: ["exec", "ark-sales__ark_get_lead"],
      deny: ["process", "group:fs", "browser", "group:messaging", "group:sessions", "cron", "web_search", "web_fetch"],
      exec: { host: "gateway", security: "allowlist", ask: "on-miss", strictInlineEval: true },
    },
  });
  setConfig("agents.list", [...byId.values()]);
  setConfig("tools.profile", "minimal");
  setConfig("tools.alsoAllow", ["web_search", "web_fetch"]);
  setConfig("tools.deny", ["process", "group:fs", "browser", "group:messaging", "group:sessions", "cron"]);
  setConfig("tools.exec", { host: "gateway", security: "allowlist", ask: "off", strictInlineEval: true });
  setConfig("tools.agentToAgent.enabled", false);
  setConfig("env.vars.AGENTLY_WORKSPACE", "ark-sales");
  setConfig("env.vars.OPENCLAW_PROFILE", profile);
  setConfig("env.vars.OUTREACH_QUEUE_DIR", queueDir);
  setConfig("env.vars.OUTREACH_SKILL_ROOT", join(emailWorkspace, "skills"));
}

function installSkills() {
  run(openclaw, [
    "--profile", profile, "skills", "install", join(repoRoot, ".agents", "skills", "ark-email-outreach"),
    "--agent", emailAgentId, "--as", "ark-email-outreach", "--force",
  ]);
  run(openclaw, [
    "--profile", profile, "skills", "install", join(home, ".agents", "skills", "agently-mail"),
    "--agent", emailAgentId, "--as", "agently-mail", "--force",
  ]);
}

function configureApprovals() {
  const response = JSON.parse(run(openclaw, ["--profile", profile, "approvals", "get", "--json"], { capture: true }));
  const file = response.file || {};
  const unexpected = Object.keys(file.agents || {}).filter((id) => !["main", emailAgentId].includes(id));
  if (unexpected.length) {
    throw new Error(`Dedicated ${profile} profile has unexpected exec-approval agents: ${unexpected.join(", ")}`);
  }
  const approvals = {
    version: 1,
    socket: file.socket || {},
    defaults: file.defaults || {},
    agents: {
      main: {
        security: "deny",
        ask: "off",
        askFallback: "deny",
        autoAllowSkills: false,
        allowlist: [],
      },
      [emailAgentId]: {
        security: "allowlist",
        ask: "on-miss",
        askFallback: "deny",
        autoAllowSkills: false,
        allowlist: [
          {
            id: "70a095a0-da22-4dda-a9ae-81f0729ac407",
            pattern: queueBin,
            argPattern: "^(?:schedule|preview|list)(?:[\\s\\S]*)$",
          },
          {
            id: "96d599bb-3bfa-4449-a32c-e6b7f232c3d4",
            pattern: skillReaderBin,
            argPattern: "^(?:outreach|course|localization|negotiation|agent-mail)$",
          },
        ],
      },
    },
  };
  run(openclaw, ["--profile", profile, "approvals", "set", "--stdin"], {
    input: JSON.stringify(approvals),
  });
}

function xmlEscape(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

async function installDispatcher() {
  const label = `com.leshine.${profile}.outreach-dispatch`;
  const logDir = join(stateDir, "logs");
  await mkdir(logDir, { recursive: true, mode: 0o700 });
  const plist = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${label}</string>
<key>ProgramArguments</key><array><string>${xmlEscape(dispatchBin)}</string></array>
<key>EnvironmentVariables</key><dict>
<key>AGENTLY_WORKSPACE</key><string>ark-sales</string>
<key>OUTREACH_QUEUE_DIR</key><string>${xmlEscape(queueDir)}</string>
<key>PATH</key><string>${xmlEscape(`${nodeDir}:/usr/bin:/bin:/usr/sbin:/sbin`)}</string>
</dict>
<key>StartInterval</key><integer>60</integer>
<key>RunAtLoad</key><true/>
<key>StandardOutPath</key><string>${xmlEscape(join(logDir, "outreach-dispatch.log"))}</string>
<key>StandardErrorPath</key><string>${xmlEscape(join(logDir, "outreach-dispatch.error.log"))}</string>
<key>ProcessType</key><string>Background</string>
</dict></plist>\n`;
  await writeFile(launchAgentPath, plist, { encoding: "utf8", mode: 0o600 });
  const domain = `gui/${process.getuid()}`;
  spawnSync("launchctl", ["bootout", domain, launchAgentPath], { encoding: "utf8" });
  run("launchctl", ["bootstrap", domain, launchAgentPath]);
  run("launchctl", ["enable", `${domain}/${label}`]);
}

function verifyMailbox() {
  const cli = join(nodeDir, "agently-cli");
  const output = run(cli, ["+me"], { capture: true, env: { AGENTLY_WORKSPACE: "ark-sales" } });
  const parsed = JSON.parse(output);
  return parsed?.data?.email || parsed?.data?.mailbox?.email
    || parsed?.data?.aliases?.find((item) => item.is_primary)?.email
    || parsed?.data?.aliases?.[0]?.email || parsed?.email || "authorized";
}

async function main() {
  validateProfileName(profile);
  const mailbox = verifyMailbox();
  await installBinaries();
  await installWorkspace();
  await configureModelSecret();
  configureApprovals();
  configureAgents();
  installSkills();
  await installDispatcher();
  setConfig("agents.defaults.skills", ["ark-lead-discovery", "ark-company-research", "ark-public-pool-research"]);
  run(openclaw, ["--profile", profile, "config", "validate"]);
  run(openclaw, ["--profile", profile, "secrets", "audit", "--check"]);
  run(openclaw, ["--profile", profile, "gateway", "restart"]);
  process.stdout.write(`Email outreach agent configured. Mailbox: ${mailbox}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
