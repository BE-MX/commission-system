import assert from "node:assert/strict";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createServer } from "../src/server.mjs";

const lease = "secret-".repeat(8);
const inputHash = "a".repeat(64);
const privatePolicy = "private-research-v2";
const taskId = 7;

async function fixture(t, policyVersion = privatePolicy, gateStatus = "pending") {
  const calls = [];
  const server = createServer({
    getResearchTaskContext: async (id, token) => {
      calls.push(["context", id, token]);
      return {
        execution_contract: "external_research_run_v1",
        policy_version: policyVersion,
        task_type: "full_research",
        gate_status: gateStatus,
        ...(policyVersion !== privatePolicy || token !== undefined
          ? { fact_contract: { version: policyVersion === privatePolicy
            ? "registered_research_facts_v2" : "registered_research_facts_v1" } }
          : { requires_lease_for_context: true }),
        ...(token !== undefined ? {
          input_snapshot: { contact: "test@example.com" },
          result_contract: { schema_version: "private_research_v2" },
        } : {}),
      };
    },
    claimResearchTask: async (id) => ({
      research_task_id: id, customer_id: 11, agent_run_id: 123, input_hash: inputHash, lease_token: lease,
    }),
    submitResearchIndustryGate: async () => ({ gate_status: "passed" }),
    callPrivateResearchTool: async (...args) => {
      calls.push(args);
      return { call_id: 65, status: "succeeded" };
    },
    completeResearchTask: async (...args) => {
      calls.push(args);
      return { task_status: "completed" };
    },
  });
  const client = new Client({ name: "test", version: "1" });
  const [a, b] = InMemoryTransport.createLinkedPair();
  await Promise.all([client.connect(a), server.connect(b)]);
  t.after(async () => { await client.close(); await server.close(); });
  return {
    client, calls,
    call: (name, args = {}) => client.callTool({ name, arguments: { research_task_id: taskId, ...args } }),
  };
}

const scan = {
  action: "submit", operation: "username_scan", target: "stylist",
  idempotency_key: "scan-1", free_search: { queries: ["stylist hair"], outcome: "insufficient" },
};
const paid = {
  action: "submit", operation: "instagram_profile", target: "https://www.instagram.com/stylist/",
  idempotency_key: "paid-1", maigret_call_id: 65, gap: "professional_identity",
};
const gate = { industry_relevance: "uncertain", reason: "Some relevant evidence but identity is unclear" };
const report = {
  schema_version: "private_research_v2", input_hash: inputHash, report_markdown: "## 主体待核实",
  missing_information: ["官网"], claims: [], citations: [],
};

test("private task context uses a leased POST only after claim", async (t) => {
  const { call, calls } = await fixture(t);
  assert.equal((await call("ark_get_research_task_context")).structuredContent.input_snapshot, undefined);
  const claim = (await call("ark_claim_research_task")).structuredContent;
  assert.equal(claim.policy_version, privatePolicy);
  assert.equal(JSON.stringify(claim).includes(lease), false);
  assert.equal((await call("ark_get_research_task_context")).structuredContent.input_snapshot.contact, "test@example.com");
  assert.deepEqual(calls, [["context", taskId, undefined], ["context", taskId, undefined], ["context", taskId, lease]]);
});

test("provider tools are discoverable and require a current private task with a passed gate", async (t) => {
  const { client, call, calls } = await fixture(t);
  const tools = (await client.listTools()).tools;
  const tool = tools.find(({ name }) => name === "ark_username_scan");
  assert.ok(tool.inputSchema.properties.request);
  assert.equal(tool.inputSchema.properties.lease_token, undefined);
  assert.equal((await call("ark_username_scan", { request: scan })).isError, true);
  await call("ark_claim_research_task");
  assert.equal((await call("ark_username_scan", { request: scan })).isError, true);
  await call("ark_submit_research_industry_gate", gate);
  assert.equal((await call("ark_username_scan", { request: scan, research_task_id: 9 })).isError, true);
  assert.equal((await call("ark_username_scan", { request: { ...scan, agent_run_id: 1 } })).isError, true);
  assert.equal((await call("ark_monid_run", { request: { ...paid, maigret_call_id: undefined } })).isError, true);
  assert.equal(calls.length, 1);

  assert.equal((await call("ark_username_scan", { request: scan })).isError, undefined);
  assert.equal((await call("ark_monid_run", { request: paid })).isError, undefined);
  assert.equal((await call("ark_monid_run", { request: { action: "status", call_id: 65 } })).isError, undefined);
  assert.equal((await call("ark_monid_run", { request: { action: "bind", call_id: 65, candidate_ids: [1] } })).isError, undefined);
  const { action: _scanAction, ...scanPayload } = scan;
  const { action: _paidAction, ...paidPayload } = paid;
  assert.deepEqual(calls.slice(1), [
    [taskId, lease, 123, "username_scan", "submit", scanPayload],
    [taskId, lease, 123, "monid", "submit", paidPayload],
    [taskId, lease, 123, "monid", "status", { call_id: 65 }],
    [taskId, lease, 123, "monid", "bind", { call_id: 65, candidate_ids: [1] }],
  ]);

  assert.equal((await call("ark_complete_research_task", { result_json: report })).isError, undefined);
  assert.equal(calls.at(-1)[2].data_classification, "personal_contact");
  assert.equal(calls.at(-1)[2].visibility_scope, "customer_team");
  assert.equal((await call("ark_monid_run", { request: { action: "status", call_id: 65 } })).isError, true);
});

test("a reclaimed private task can reuse the passed gate from its leased context", async (t) => {
  const { call } = await fixture(t, privatePolicy, "passed");
  await call("ark_claim_research_task");
  assert.equal((await call("ark_get_research_task_context")).structuredContent.gate_status, "passed");
  assert.equal((await call("ark_username_scan", { request: scan })).isError, undefined);
});

test("old tasks cannot call provider tools or submit private V2 reports", async (t) => {
  const { call, calls } = await fixture(t, "private-enrichment-v1");
  await call("ark_claim_research_task");
  await call("ark_submit_research_industry_gate", gate);
  assert.equal((await call("ark_username_scan", { request: scan })).isError, true);
  assert.equal((await call("ark_monid_run", { request: paid })).isError, true);
  assert.equal((await call("ark_complete_research_task", { result_json: report })).isError, true);
  assert.equal(calls.length, 1);
});
