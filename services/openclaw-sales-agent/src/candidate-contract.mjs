import { createHash } from "node:crypto";

// Public-web source identity only. Ark remains the authority for customer_id.
// Do not use a job, attempt, batch position, score or company name as identity.
export function toCandidateInput({ name, ...candidate }) {
  const source = new URL(candidate.source_url);
  source.hash = "";
  const host = new URL(candidate.website).hostname.toLowerCase().replace(/^www\./u, "").replace(/\.$/u, "");
  return {
    ...candidate,
    company_name: name,
    source_system: "public_web",
    source_account_key: "global",
    source_entity_type: "company_page",
    external_record_id: `web-page:${createHash("sha256").update(source.href).digest("hex")}`,
    external_context_id: host.length <= 246
      ? `web-host:${host}`
      : `web-host-sha256:${createHash("sha256").update(host).digest("hex")}`,
  };
}
