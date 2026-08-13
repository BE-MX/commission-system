import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";

import {
  ArkApiError,
  ArkClient,
  LeaseStore,
  isRecentPublicPoolReactivationTask,
} from "../src/ark-client.mjs";

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

test("ArkClient exposes published knowledge search and document reads through the agent API", async () => {
  const paths = [];
  await withServer((request, response) => {
    paths.push(request.url);
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify({
      code: 200,
      message: "ok",
      data: request.url.includes("/search")
        ? [{ document_id: 7, title: "Target buyers", version_no: 2 }]
        : { document_id: 7, title: "Target buyers", version_no: 2, content: "Salons and distributors" },
    }));
  }, async (baseUrl) => {
    const api = client(baseUrl);
    assert.equal((await api.searchKnowledge("hair buyers", 5))[0].document_id, 7);
    assert.equal((await api.getKnowledgeDocument(7)).version_no, 2);
  });
  assert.equal(paths[0], "/api/sales-automation/agent/knowledge/search?q=hair+buyers&limit=5");
  assert.equal(paths[1], "/api/sales-automation/agent/knowledge/documents/7");
});

test("LeaseStore retains lease secrets in memory and requires an explicit claim", () => {
  const leases = new LeaseStore();
  assert.throws(() => leases.require(9), /claim|租约/);
  leases.remember(9, "l".repeat(32), "2026-08-11T10:00:00Z");
  assert.equal(leases.require(9).token, "l".repeat(32));
  leases.forget(9);
  assert.throws(() => leases.require(9), /claim|租约/);
});

test("public-pool recent-order guard excludes stale T1 rows before local pagination", async () => {
  const seenPages = [];
  await withServer((request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    seenPages.push(url.searchParams.get("page"));
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify({
      code: 200,
      message: "ok",
      data: {
        total: 4,
        page: 1,
        page_size: 100,
        items: [
          { id: 1, tier: "T1", subject: { last_order_at: "2026-07-28T00:00:00" } },
          { id: 2, tier: "T1", subject: { last_order_at: "2026-06-13T00:00:00" } },
          { id: 3, tier: "T2", subject: { last_order_at: "2026-08-01T00:00:00" } },
          { id: 4, tier: "T3", subject: { last_order_at: null } },
        ],
      },
    }));
  }, async (baseUrl) => {
    const result = await client(baseUrl).listPublicPoolTasks(1, 2);
    assert.deepEqual(result.items.map(({ id }) => id), [2, 3]);
    assert.equal(result.total, 3);
    assert.equal(result.page, 1);
    assert.equal(result.page_size, 2);
  });
  assert.deepEqual(seenPages, ["1"]);
});

test("public-pool recent-order guard treats the 60-day cutoff as excluded", () => {
  const now = new Date("2026-08-13T10:00:00+08:00");
  assert.equal(isRecentPublicPoolReactivationTask(
    { tier: "T1", subject: { last_order_at: "2026-06-14T23:59:59" } }, now,
  ), true);
  assert.equal(isRecentPublicPoolReactivationTask(
    { tier: "T1", subject: { last_order_at: "2026-06-13T23:59:59" } }, now,
  ), false);
  assert.equal(isRecentPublicPoolReactivationTask(
    { tier: "T2", subject: { last_order_at: "2026-08-12T00:00:00" } }, now,
  ), false);
});

test("public-pool claim guard blocks recent T1 before sending a claim", async () => {
  const methods = [];
  await withServer((request, response) => {
    methods.push(request.method);
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify({
      code: 200,
      message: "ok",
      data: {
        task: { id: 9, tier: "T1", subject: { last_order_at: new Date().toISOString() } },
      },
    }));
  }, async (baseUrl) => {
    await assert.rejects(() => client(baseUrl).claimPublicPoolTask(9), /最近60天/);
  });
  assert.deepEqual(methods, ["GET"]);
});

test("ArkClient submits the staged public-pool industry gate with the in-memory lease", async () => {
  let received = null;
  await withServer(async (request, response) => {
    received = { url: request.url, body: JSON.parse(await new Promise((resolve) => {
      let value = "";
      request.on("data", (chunk) => { value += chunk; });
      request.on("end", () => resolve(value));
    })) };
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify({ code: 200, message: "ok", data: { deep_research_authorized: true } }));
  }, async (baseUrl) => {
    await client(baseUrl).submitPublicPoolIndustryGate(7, "l".repeat(32), {
      summary: "Matched", identity_decision: "confirmed", facts: [],
      industry_relevance: "core", industry_relevance_reason: "Catalog match",
    });
  });
  assert.equal(received.url, "/api/sales-automation/agent/public-pool/tasks/7/industry-gate");
  assert.equal(received.body.agent_id, "test-agent");
  assert.equal(received.body.lease_token, "l".repeat(32));
});
