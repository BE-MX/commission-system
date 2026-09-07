import assert from "node:assert/strict";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createServer } from "../src/server.mjs";
import { ArkClient } from "../src/ark-client.mjs";
import { toCandidateInput } from "../src/candidate-contract.mjs";

const candidate = {
  name: "Private Label Extensions",
  website: "https://www.privatelabelextensions.com/",
  source_url: "https://www.privatelabelextensions.com/about",
  captured_at: "2026-09-07T11:08:45+08:00",
  score: 72.25,
  score_reasons: [{ dimension: "product_fit", reason: "Test fixture: catalog match", source_url: "https://www.privatelabelextensions.com/about" }],
};

test("source identities survive recapture, scoring changes and website spelling variants", () => {
  const first = toCandidateInput(candidate);
  const later = toCandidateInput({ ...candidate, name: "New display name", score: 60,
    website: "http://PRIVATELABELEXTENSIONS.COM./catalog", captured_at: "2026-09-08T03:08:45Z",
    source_url: `${candidate.source_url}#catalog` });
  assert.equal(first.external_record_id, later.external_record_id);
  assert.equal(first.external_context_id, later.external_context_id);
  assert.notEqual(first.external_record_id, toCandidateInput({ ...candidate, source_url: `${candidate.source_url}/other` }).external_record_id);
  assert.equal(first.company_name, candidate.name);
  assert.equal(first.name, undefined);
  assert.equal(first.score, 72.25);
  const longHost = ["a".repeat(63), "b".repeat(63), "c".repeat(63), "d".repeat(54), "com"].join(".");
  const longRecord = toCandidateInput({ ...candidate, website: `https://${longHost}` });
  assert.ok(longRecord.external_context_id.length <= 255);
  assert.match(longRecord.external_context_id, /^web-host-sha256:[a-f0-9]{64}$/u);
  assert.equal(longRecord.external_context_id, toCandidateInput({ ...candidate, website: `http://www.${longHost}/catalog` }).external_context_id);
});

test("MCP-to-HTTP maps the candidate and rejects incomplete or invalid scores before writing", async (t) => {
  const writes = [];
  const api = new ArkClient({ baseUrl: "https://ark.example", token: "test-secret", agentId: "test-agent" }, async (url, init) => {
    const body = JSON.parse(init.body);
    writes.push({ url, body });
    const data = url.endsWith("/claim")
      ? { job_id: 3, attempt_count: 2, lease_token: "private-lease-that-is-at-least-32-characters", lease_expires_at: "2099-01-01T00:00:00Z" }
      : { received: body.candidates.length, customer_ids: [101] };
    return new Response(JSON.stringify({ code: 200, data }));
  });
  const server = createServer(api);
  const client = new Client({ name: "contract-test", version: "1" });
  const [ct, st] = InMemoryTransport.createLinkedPair();
  t.after(async () => { await client.close(); await server.close(); });
  await Promise.all([server.connect(st), client.connect(ct)]);
  await client.callTool({ name: "ark_claim_search_job", arguments: { job_id: 3 } });
  const args = { job_id: 3, request_key: "job-3-attempt-2-batch-1", candidates: [candidate] };
  for (const invalid of [
    { ...candidate, score: undefined, score_reasons: undefined },
    { ...candidate, score: -1 }, { ...candidate, score: 101 },
    { ...candidate, score: 70.123 }, { ...candidate, score_reasons: [] },
    { ...candidate, captured_at: "2026-09-07T11:08:45" },
    { ...candidate, website: "https://user:secret@example.com" },
  ]) {
    const result = await client.callTool({ name: "ark_submit_candidates", arguments: { ...args, candidates: [invalid] } });
    assert.equal(result.isError, true);
  }
  assert.equal(writes.length, 1, "invalid records must never reach Ark");
  const result = await client.callTool({ name: "ark_submit_candidates", arguments: args });
  assert.deepEqual(result.structuredContent.customer_ids, [101]);
  assert.doesNotMatch(JSON.stringify(result), /private-lease/);
  assert.deepEqual(writes[1].body.candidates, [{ ...toCandidateInput(candidate), source_provider: "openclaw_web_search" }]);
  assert.equal(writes[1].body.lease_token, "private-lease-that-is-at-least-32-characters");
  await client.callTool({ name: "ark_submit_candidates", arguments: args });
  assert.deepEqual(writes[1], writes[2], "an identical retry keeps the whole wire payload stable");
  const unsupported = await client.callTool({ name: "ark_list_search_jobs", arguments: { status: "failed" } });
  assert.equal(unsupported.isError, true);
});
