import assert from "node:assert/strict";
import test from "node:test";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { createServer } from "../src/server.mjs";

test("MCP exposes only the Ark workflow and never returns the lease token", async (t) => {
  const leaseToken = "lease-secret-that-must-remain-inside-the-sidecar";
  const poolLeaseToken = "pool-lease-secret-that-stays-inside-sidecar";
  let submittedLease = null;
  let submittedPoolLease = null;
  const arkClient = {
    listSearchJobs: async () => ({ items: [] }),
    getSearchJobContext: async (jobId) => ({ job: { id: jobId } }),
    claimSearchJob: async (jobId) => ({
      job: { id: jobId, status: "running" },
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
    getLead: async (companyId) => ({ company: { id: companyId } }),
    searchKnowledge: async () => ([{ document_id: 7, title: "Target buyers", version_no: 2 }]),
    getKnowledgeDocument: async (documentId) => ({ document_id: documentId, title: "Target buyers", version_no: 2, content: "Salons" }),
    saveContacts: async () => ({ created: 1 }),
    saveResearch: async () => ({ saved: true }),
    listPublicPoolTasks: async () => ({ items: [] }),
    getPublicPoolTaskContext: async (taskId) => ({ task: { id: taskId } }),
    claimPublicPoolTask: async (taskId) => ({
      task_id: taskId,
      lease_token: poolLeaseToken,
      lease_expires_at: "2026-08-11T12:00:00Z",
    }),
    heartbeatPublicPoolTask: async () => ({ renewed: true }),
    submitPublicPoolIndustryGate: async (_taskId, receivedLease) => {
      submittedPoolLease = receivedLease;
      return { gate_status: "passed", deep_research_authorized: true };
    },
    completePublicPoolTask: async (_taskId, receivedLease) => {
      submittedPoolLease = receivedLease;
      return { status: "completed", assessment: { grade: "B" } };
    },
    failPublicPoolTask: async () => ({ status: "failed" }),
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
      "ark_claim_public_pool_task",
      "ark_claim_search_job",
      "ark_complete_public_pool_task",
      "ark_complete_search_job",
      "ark_fail_public_pool_task",
      "ark_fail_search_job",
      "ark_get_knowledge_document",
      "ark_get_lead",
      "ark_get_public_pool_task_context",
      "ark_get_search_job_context",
      "ark_heartbeat_public_pool_task",
      "ark_heartbeat_search_job",
      "ark_list_public_pool_tasks",
      "ark_list_search_jobs",
      "ark_save_contacts",
      "ark_save_research",
      "ark_search_knowledge",
      "ark_submit_candidates",
      "ark_submit_public_pool_industry_gate",
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

  const poolClaim = await client.callTool({
    name: "ark_claim_public_pool_task", arguments: { task_id: 7 },
  });
  assert.equal(poolClaim.structuredContent.lease_held, true);
  assert.doesNotMatch(JSON.stringify(poolClaim), new RegExp(poolLeaseToken));
  const gate = await client.callTool({
    name: "ark_submit_public_pool_industry_gate",
    arguments: {
      task_id: 7,
      summary: "Official catalog matches the target industry.",
      identity_decision: "confirmed",
      facts: [{
        claim: "The catalog lists target products.",
        source_url: "https://example-industrial.test/catalog",
        captured_at: "2026-08-11T10:00:00+08:00",
        confidence: 0.9,
      }],
      industry_relevance: "core",
      industry_relevance_reason: "Official catalog match.",
      knowledge_references: [{ document_id: 7, revision_id: 21, version_no: 2 }],
    },
  });
  assert.equal(gate.structuredContent.deep_research_authorized, true);
  await client.callTool({
    name: "ark_complete_public_pool_task",
    arguments: {
      task_id: 7,
      summary: "Identity and fit were checked against the official website.",
      identity_decision: "confirmed",
      facts: [{
        fact_type: "business",
        claim: "The company publishes an industrial distribution catalog.",
        source_url: "https://example-industrial.test/catalog",
        captured_at: "2026-08-11T10:00:00+08:00",
        confidence: 0.9,
      }],
      score_components: { industry_fit: 20, reasons: { industry_fit: "Official catalog" } },
      industry_relevance: "core",
      industry_relevance_reason: "The official catalog matches the target category.",
      recommended_strategy: "Lead with the matched catalog segment.",
      outreach_type: "new_development",
    },
  });
  assert.equal(submittedPoolLease, poolLeaseToken);
});
