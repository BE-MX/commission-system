import assert from "node:assert/strict";
import test from "node:test";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { createServer } from "../src/server.mjs";

test("MCP exposes only the Ark workflow and never returns the lease token", async (t) => {
  const leaseToken = "lease-secret-that-must-remain-inside-the-sidecar";
  const researchLeaseToken = "research-lease-secret-that-stays-inside-sidecar";
  let submittedLease = null;
  let submittedResearchLease = null;
  const arkClient = {
    listSearchJobs: async () => ({ items: [] }),
    getSearchJobContext: async (jobId) => ({ job: { id: jobId } }),
    claimSearchJob: async (jobId) => ({
      job_id: jobId,
      attempt_count: 1,
      lease_token: leaseToken,
      lease_expires_at: "2026-08-11T12:00:00Z",
    }),
    heartbeatSearchJob: async () => ({ renewed: true }),
    submitCandidates: async (_jobId, receivedLease) => {
      submittedLease = receivedLease;
      return { received: 1, created: 1, updated: 0, deduplicated: 0 };
    },
    completeSearchJob: async () => ({ status: "completed" }),
    failSearchJob: async () => ({ status: "failed" }),
    searchKnowledge: async () => ([{ document_id: 7, title: "Target buyers", version_no: 2 }]),
    getKnowledgeDocument: async (documentId) => ({ document_id: documentId, title: "Target buyers", version_no: 2, content: "Salons" }),
    listResearchTasks: async () => ({ items: [] }),
    getResearchTaskContext: async (taskId) => ({ research_task_id: taskId, customer_id: 101 }),
    claimResearchTask: async (taskId) => ({
      research_task_id: taskId,
      customer_id: 101,
      input_hash: "a".repeat(64),
      lease_token: researchLeaseToken,
      lease_expires_at: "2026-08-11T12:00:00Z",
    }),
    heartbeatResearchTask: async () => ({ renewed: true }),
    submitResearchIndustryGate: async (_taskId, receivedLease) => {
      submittedResearchLease = receivedLease;
      return { gate_status: "passed" };
    },
    appendResearchFacts: async (_taskId, receivedLease) => {
      submittedResearchLease = receivedLease;
      return { evidence_refs: [{ evidence_ref: "fact:8", evidence_content_hash: "b".repeat(64) }] };
    },
    completeResearchTask: async (_taskId, receivedLease) => {
      submittedResearchLease = receivedLease;
      return { task_status: "completed" };
    },
    failResearchTask: async () => ({ task_status: "failed" }),
  };

  const server = createServer(arkClient);
  const client = new Client({ name: "ark-sales-test", version: "1.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  t.after(async () => {
    await client.close();
    await server.close();
  });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);

  const listed = await client.listTools();
  assert.deepEqual(
    listed.tools.map(({ name }) => name).sort(),
    [
      "ark_append_research_facts",
      "ark_claim_research_task",
      "ark_claim_search_job",
      "ark_complete_research_task",
      "ark_complete_search_job",
      "ark_fail_research_task",
      "ark_fail_search_job",
      "ark_get_knowledge_document",
      "ark_get_research_task_context",
      "ark_get_search_job_context",
      "ark_heartbeat_research_task",
      "ark_heartbeat_search_job",
      "ark_list_research_tasks",
      "ark_list_search_jobs",
      "ark_search_knowledge",
      "ark_submit_candidates",
      "ark_submit_research_industry_gate",
    ],
  );

  const claim = await client.callTool({ name: "ark_claim_search_job", arguments: { job_id: 42 } });
  assert.equal(claim.structuredContent.lease_held, true);
  assert.doesNotMatch(JSON.stringify(claim), new RegExp(leaseToken));

  await client.callTool({
    name: "ark_submit_candidates",
    arguments: {
      job_id: 42,
      request_key: "job-42-batch-1",
      candidates: [{
        name: "Example Industrial",
        website: "https://example-industrial.test",
        source_url: "https://example-industrial.test/about",
        captured_at: "2026-08-11T10:00:00+08:00",
      }],
    },
  });
  assert.equal(submittedLease, leaseToken);

  const researchClaim = await client.callTool({
    name: "ark_claim_research_task", arguments: { research_task_id: 7 },
  });
  assert.equal(researchClaim.structuredContent.lease_held, true);
  assert.equal(researchClaim.structuredContent.customer_id, 101);
  assert.doesNotMatch(JSON.stringify(researchClaim), new RegExp(researchLeaseToken));
  const gate = await client.callTool({
    name: "ark_submit_research_industry_gate",
    arguments: {
      research_task_id: 7,
      industry_relevance: "core",
      reason: "Official catalog match.",
    },
  });
  assert.equal(gate.structuredContent.gate_status, "passed");
  await client.callTool({
    name: "ark_append_research_facts",
    arguments: {
      research_task_id: 7,
      agent_run_id: 55,
      facts: [{
        fact_key: "business.industry",
        value_type: "string",
        value: "hair extensions",
        fact_layer: "source",
        confidence: 0.9,
        source_system: "public_web",
        source_entity_type: "company_page",
        external_record_id: "catalog-1",
        source_url: "https://example-industrial.test/catalog",
        observed_at: "2026-08-11T10:00:00+08:00",
      }],
    },
  });
  assert.equal(submittedResearchLease, researchLeaseToken);
});
