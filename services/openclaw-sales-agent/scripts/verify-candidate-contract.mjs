// Read-only integration check against the repository's real Pydantic boundary.
// ARK_CONTRACT_PYTHON must point to Python with pydantic installed; no DB/network.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { ArkClient } from "../src/ark-client.mjs";
import { createServer } from "../src/server.mjs";

const backend = fileURLToPath(new URL("../../../backend/", import.meta.url));
let validated = 0;
const api = new ArkClient({ baseUrl: "https://contract.test", token: "fixture-token", agentId: "contract-test" }, async (url, options) => {
  const body = JSON.parse(options.body);
  let data;
  if (url.endsWith("/claim")) {
    data = { job_id: 3, attempt_count: 2, lease_token: "fixture-lease-that-is-at-least-32-characters", lease_expires_at: "2099-01-01T00:00:00Z" };
  } else {
    const run = spawnSync(process.env.ARK_CONTRACT_PYTHON || "python3", ["-c", `
import json,sys
from app.sales_automation.schemas import CandidateBatch
data=json.load(sys.stdin)
batch=CandidateBatch.model_validate(data)
for actual,expected in zip(batch.candidates,data['candidates']):
    assert actual.company_name == expected['company_name']
    assert actual.external_record_id and actual.external_context_id
    assert float(actual.score) == expected['score']
print(len(batch.candidates))
`], { cwd: backend, input: JSON.stringify(body), encoding: "utf8" });
    assert.equal(run.status, 0, run.stderr);
    validated += Number(run.stdout.trim());
    data = { received: body.candidates.length, customer_ids: [101] };
  }
  return new Response(JSON.stringify({ code: 200, data }));
});
const server = createServer(api);
const client = new Client({ name: "pydantic-contract", version: "1" });
const [ct, st] = InMemoryTransport.createLinkedPair();
try {
  await Promise.all([server.connect(st), client.connect(ct)]);
  await client.callTool({ name: "ark_claim_search_job", arguments: { job_id: 3 } });
  for (const count of [7, 20]) {
    const result = await client.callTool({ name: "ark_submit_candidates", arguments: {
      job_id: 3, request_key: `job-3-attempt-2-batch-${count}`,
      candidates: Array.from({ length: count }, (_, i) => ({
        name: `Contract fixture ${i}`, website: `https://fixture-${i}.example.com`,
        source_url: `https://fixture-${i}.example.com/about`,
        captured_at: "2026-09-07T11:08:45+08:00", score: 72.25,
        score_reasons: [{ dimension: "product_fit", reason: "Offline test fixture only", source_url: `https://fixture-${i}.example.com/about` }],
      })),
    } });
    assert.notEqual(result.isError, true, JSON.stringify(result));
    assert.equal(result.structuredContent.received, count);
  }
  assert.equal(validated, 27);
  console.log("PASS: 7 + 20 candidates passed MCP → ArkClient → real CandidateBatch; no network or database writes.");
} finally {
  await client.close();
  await server.close();
}
