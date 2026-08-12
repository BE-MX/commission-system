import assert from "node:assert/strict";
import { chmod, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { ArkConfigurationError, loadConfig } from "../src/config.mjs";

const BASE_ENV = {
  ARK_BASE_URL: "https://leshine.work",
  ARK_ALLOWED_ORIGIN: "https://leshine.work",
  ARK_AGENT_ID: "openclaw-sales-01",
};

async function privateTokenEnv(t, token = "t".repeat(32)) {
  const directory = await mkdtemp(join(tmpdir(), "ark-config-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const tokenFile = join(directory, "token");
  await writeFile(tokenFile, token, { mode: 0o600 });
  await chmod(tokenFile, 0o600);
  return { ...BASE_ENV, ARK_AGENT_TOKEN_FILE: tokenFile };
}

test("loadConfig accepts an exact trusted origin", async (t) => {
  const config = loadConfig(await privateTokenEnv(t));
  assert.equal(config.baseUrl, "https://leshine.work");
  assert.equal(config.allowedOrigin, "https://leshine.work");
  assert.equal(config.agentId, "openclaw-sales-01");
});

test("loadConfig rejects origin confusion and short tokens", async (t) => {
  const env = await privateTokenEnv(t);
  assert.throws(
    () => loadConfig({ ...env, ARK_ALLOWED_ORIGIN: "https://attacker.example" }),
    /must|same origin|同源/,
  );
  const shortTokenEnv = await privateTokenEnv(t, "short");
  assert.throws(
    () => loadConfig(shortTokenEnv),
    ArkConfigurationError,
  );
});

test("loadConfig reads a token only from a private regular file", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "ark-config-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const tokenFile = join(directory, "token");
  await writeFile(tokenFile, "f".repeat(40), { mode: 0o600 });
  await chmod(tokenFile, 0o600);

  const config = loadConfig({ ...BASE_ENV, ARK_AGENT_TOKEN_FILE: tokenFile });
  assert.equal(config.token, "f".repeat(40));
});

test("loadConfig rejects permissive token files and symlinks", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "ark-config-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const tokenFile = join(directory, "token");
  const tokenLink = join(directory, "token-link");
  await writeFile(tokenFile, "f".repeat(40), { mode: 0o600 });
  await chmod(tokenFile, 0o640);
  assert.throws(
    () => loadConfig({ ...BASE_ENV, ARK_AGENT_TOKEN_FILE: tokenFile }),
    /0600/,
  );

  await chmod(tokenFile, 0o600);
  await symlink(tokenFile, tokenLink);
  assert.throws(
    () => loadConfig({ ...BASE_ENV, ARK_AGENT_TOKEN_FILE: tokenLink }),
    /普通文件|符号链接/,
  );
});

test("loadConfig never accepts a token directly from the process environment", () => {
  assert.throws(
    () => loadConfig({ ...BASE_ENV, ARK_AGENT_TOKEN: "t".repeat(40) }),
    /ARK_AGENT_TOKEN_FILE/,
  );
});

test("loadConfig accepts an optional private heartbeat token file", async (t) => {
  const env = await privateTokenEnv(t);
  const directory = await mkdtemp(join(tmpdir(), "ark-heartbeat-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const heartbeatFile = join(directory, "heartbeat-token");
  await writeFile(heartbeatFile, "h".repeat(32), { mode: 0o600 });
  await chmod(heartbeatFile, 0o600);

  const config = loadConfig({ ...env, ARK_HEARTBEAT_TOKEN_FILE: heartbeatFile });
  assert.equal(config.heartbeatToken, "h".repeat(32));
});
