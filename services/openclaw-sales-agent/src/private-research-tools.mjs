import { z } from "zod";

export const PRIVATE_RESEARCH_POLICY = "private-research-v2";
const taskId = z.number().int().positive();
const callId = z.number().int().positive();
const submit = z.object({
  action: z.literal("submit"),
  target: z.string().trim().min(1).max(512),
  idempotency_key: z.string().min(1).max(96).regex(/^[A-Za-z0-9._:-]+$/u)
    .describe("Reuse the same key when retrying the same request"),
});
const status = z.object({
  action: z.literal("status"),
  call_id: callId,
}).strict();
const bind = z.object({
  action: z.literal("bind"),
  call_id: callId,
  candidate_ids: z.array(z.number().int().positive()).min(1).max(60)
    .describe("Select only provider candidates independently matched to this customer"),
}).strict();

const tools = [
  {
    name: "ark_username_scan",
    endpoint: "username_scan",
    description: "Private V2 only. After free public web research and the industry gate, submit a Maigret username scan, poll status, or bind verified candidates. Treat likely false negatives as unavailable.",
    requestSchema: z.discriminatedUnion("action", [submit.extend({
      operation: z.literal("username_scan"),
      target: z.string().trim().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/u)
        .describe("Bare username without @, spaces, or a URL"),
      free_search: z.object({
        queries: z.array(z.string().trim().min(1).max(250)).min(1).max(5),
        outcome: z.enum(["insufficient", "candidate_found"]),
      }).strict().describe("Record the actual preceding free public web searches"),
    }).strict(), status, bind]),
  },
  {
    name: "ark_monid_run",
    endpoint: "monid",
    description: "Private V2 weak leads only. After free web search and a relevant terminal Maigret scan, submit Monid for a remaining gap, poll status, or bind verified candidates. Prefer a known profile URL.",
    requestSchema: z.discriminatedUnion("action", [submit.extend({
      operation: z.enum(["instagram_profile", "tiktok_profile", "facebook_profile", "linkedin_profile", "hunter_domain_email"]),
      maigret_call_id: callId,
      gap: z.enum(["subject_identity", "professional_identity", "contact", "social_activity"]),
    }).strict(), status, bind]),
  },
];

export function registerPrivateResearchTools(server, client, safeTracked, requirePrivateResearch) {
  for (const { name, endpoint, description, requestSchema } of tools) {
    server.registerTool(name, {
      description,
      inputSchema: z.object({ research_task_id: taskId, request: requestSchema }).strict(),
      annotations: { readOnlyHint: false, idempotentHint: true },
    }, safeTracked(({ research_task_id: taskId, request: { action, ...payload } }) => {
      const { agentRunId, leaseToken } = requirePrivateResearch(taskId);
      return client.callPrivateResearchTool(taskId, leaseToken, agentRunId, endpoint, action, payload);
    }));
  }
}
