import assert from "node:assert/strict";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createServer } from "../src/server.mjs";

async function fixture(t, overrides = {}) {
  const sent = [];
  const server = createServer({
    getResearchTaskContext: async () => ({ execution_contract: "external_research_run_v1" }),
    claimResearchTask: async taskId => ({ research_task_id: taskId, customer_id: 101,
      agent_run_id: 9001, input_hash: "a".repeat(64), lease_token: "private-lease-".repeat(4) }),
    appendResearchFacts: async (...args) => { sent.push(args); return { evidence_refs: [] }; },
    completeResearchTask: async (...args) => { sent.push(args); return { task_status: "completed" }; },
    failResearchTask: async () => ({ task_status: "failed" }),
    submitResearchIndustryGate: async () => ({ gate_status: "stopped" }),
    searchKnowledge: async () => [],
    ...overrides,
  });
  const client = new Client({ name: "test", version: "1" });
  const [a, b] = InMemoryTransport.createLinkedPair();
  await Promise.all([client.connect(a), server.connect(b)]);
  t.after(async () => { await client.close(); await server.close(); });
  return { client, sent, call: (name, args) => client.callTool({ name, arguments: args }) };
}
const fact = { fact_key: "business.industry", value_type: "string", value: "hair",
  fact_layer: "source", confidence: 0.9, source_system: "public_web", source_entity_type: "company_page",
  external_record_id: "page", source_url: "https://example.com", observed_at: "2026-09-08T10:00:00+08:00" };

test("MCP injects the server Run and does not expose a writable run argument", async t => {
  const {client,call,sent} = await fixture(t);
  const tools = await client.listTools();
  for (const name of ["ark_append_research_facts", "ark_complete_research_task"]) {
    assert.equal(tools.tools.find(x => x.name === name).inputSchema.properties.agent_run_id, undefined);
  }
  assert.equal((await call("ark_claim_research_task", {research_task_id: 11})).structuredContent.agent_run_id, 9001);
  assert.equal((await call("ark_append_research_facts", {research_task_id: 11, agent_run_id: 1, facts: [fact]})).isError, undefined);
  assert.equal(sent[0][2],9001);
  const receipt = await call("ark_search_knowledge", {query: "products"});
  assert.deepEqual(receipt.structuredContent,{items:[]});
});

test("claim failure circuit and active task boundary prevent bulk failures", async t => {
  const {call} = await fixture(t);
  await call("ark_claim_research_task", {research_task_id: 11});
  assert.equal((await call("ark_claim_research_task", {research_task_id: 12})).isError,true);
  assert.equal((await call("ark_fail_research_task", {research_task_id: 12,error_code:"agent_execution_failed"})).isError,true);
  await call("ark_fail_research_task", {research_task_id: 11,error_code:"agent_execution_failed"});
  assert.equal((await call("ark_claim_research_task", {research_task_id: 12})).isError,true);
});

test("missing Run from old backend fails closed without claiming another task", async t => {
  let claims = 0;
  const {call} = await fixture(t,{claimResearchTask: async () => { claims++; return {}; }});
  assert.equal((await call("ark_claim_research_task", {research_task_id: 11})).isError,true);
  assert.equal((await call("ark_claim_research_task", {research_task_id: 12})).isError,true);
  assert.equal(claims,1);
});

test("terminal industry gate releases the local task", async t => {
  const {call} = await fixture(t);
  await call("ark_claim_research_task", {research_task_id: 11});
  await call("ark_submit_research_industry_gate", {research_task_id:11,industry_relevance:"irrelevant",reason:"Unrelated official business"});
  assert.equal((await call("ark_claim_research_task", {research_task_id: 12})).isError,undefined);
});


test("old backend is detected before creating any task lease", async t => {
  let calls = 0;
  const {call} = await fixture(t,{getResearchTaskContext: async () => ({}),
    claimResearchTask: async () => { calls++; return {}; }});
  assert.equal((await call("ark_claim_research_task", {research_task_id: 11})).isError,true);
  assert.equal(calls,0);
});

test("lost claim response stops subsequent claims until the process restarts", async t => {
  let calls = 0;
  const {call} = await fixture(t,{claimResearchTask: async () => {
    calls++; throw new Error("Response lost after server commit");
  }});
  assert.equal((await call("ark_claim_research_task", {research_task_id:11})).isError,true);
  assert.equal((await call("ark_claim_research_task", {research_task_id:12})).isError,true);
  assert.equal(calls,1);
});

test("completion injects the claimed Run and clears the active task", async t => {
  const {call,sent} = await fixture(t);
  await call("ark_claim_research_task", {research_task_id:11});
  const response = await call("ark_complete_research_task", {research_task_id:11, agent_run_id:1,
    result_json:{schema_version:"customer_research_v1",input_hash:"a".repeat(64),
      claims:[{claim_id:"claim_1",section:"identity",statement:"Company operates a store.",citation_ids:["citation_1"]}],
      citations:[{citation_id:"citation_1",claim_id:"claim_1",tool_call_id:"receipt-1",
        evidence_ref:"fact:1",evidence_content_hash:"b".repeat(64)}]}});
  assert.equal(response.isError,undefined);
  assert.equal(sent[0][2].agent_run_id,9001);
  assert.equal((await call("ark_claim_research_task",{research_task_id:12})).isError,undefined);
});
