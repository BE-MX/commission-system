import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";

import {
  ArkApiError,
  ArkClient,
  LeaseStore,
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
    await assert.rejects(() => client(baseUrl).getResearchTaskContext(1), /redirect|重定向/);
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
      await client(baseUrl, secret).getResearchTaskContext(1);
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

test("ArkClient uses the unified research-task endpoints", async () => {
  const requests = [];
  await withServer((request, response) => {
    requests.push(request.url);
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify({
      code: 200,
      message: "ok",
      data: { total: 1, page: 2, page_size: 10, items: [{ research_task_id: 7, customer_id: 101 }] },
    }));
  }, async (baseUrl) => {
    const result = await client(baseUrl).listResearchTasks(2, 10);
    assert.equal(result.items[0].customer_id, 101);
  });
  assert.deepEqual(requests, ["/api/sales-automation/agent/research-tasks?page=2&page_size=10"]);
});

test("ArkClient submits a unified research industry gate with the in-memory lease", async () => {
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
    await client(baseUrl).submitResearchIndustryGate(7, "l".repeat(32), {
      industry_relevance: "core", reason: "Catalog match",
    });
  });
  assert.equal(received.url, "/api/sales-automation/agent/research-tasks/7/industry-gate");
  assert.equal(received.body.agent_id, "test-agent");
  assert.equal(received.body.lease_token, "l".repeat(32));
});
