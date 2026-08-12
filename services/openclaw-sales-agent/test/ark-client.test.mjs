import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";

import { ArkApiError, ArkClient, LeaseStore } from "../src/ark-client.mjs";

async function withServer(handler, run) {
  const server = createServer(handler);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    await run(`http://127.0.0.1:${port}`);
  } finally {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
}

function client(baseUrl, token = "s".repeat(40)) {
  return new ArkClient({ baseUrl, token, agentId: "test-agent", timeoutMs: 2000 });
}

test("ArkClient sends bearer auth and unwraps the Ark response envelope", async () => {
  await withServer((request, response) => {
    assert.equal(request.headers.authorization, `Bearer ${"s".repeat(40)}`);
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify({ code: 200, message: "ok", data: { items: [] } }));
  }, async (baseUrl) => {
    assert.deepEqual(await client(baseUrl).listSearchJobs(), { items: [] });
  });
});

test("ArkClient refuses redirects and never forwards authorization", async () => {
  let redirectedRequests = 0;
  await withServer((_request, response) => {
    redirectedRequests += 1;
    response.writeHead(302, { location: "https://attacker.example/capture" });
    response.end();
  }, async (baseUrl) => {
    await assert.rejects(() => client(baseUrl).getLead(1), /redirect|重定向/);
  });
  assert.equal(redirectedRequests, 1);
});

test("ArkClient errors do not include the bearer token", async () => {
  const secret = "never-print-this-secret-token-value";
  await withServer((_request, response) => {
    response.writeHead(500, { "content-type": "application/json" });
    response.end(JSON.stringify({ detail: `debug echoed ${secret}` }));
  }, async (baseUrl) => {
    try {
      await client(baseUrl, secret).getLead(1);
      assert.fail("request should fail");
    } catch (error) {
      assert.ok(error instanceof ArkApiError);
      assert.doesNotMatch(error.message, new RegExp(secret));
    }
  });
});

test("LeaseStore retains lease secrets in memory and requires an explicit claim", () => {
  const leases = new LeaseStore();
  assert.throws(() => leases.require(9), /claim|租约/);
  leases.remember(9, "l".repeat(32), "2026-08-11T10:00:00Z");
  assert.equal(leases.require(9).token, "l".repeat(32));
  leases.forget(9);
  assert.throws(() => leases.require(9), /claim|租约/);
});
