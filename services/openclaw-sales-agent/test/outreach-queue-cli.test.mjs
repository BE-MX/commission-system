import assert from "node:assert/strict";
import test from "node:test";
import { previewInputFromFlags } from "../scripts/outreach-queue.mjs";

test("preview CLI forwards every Ark approval binding", () => {
  const flags = {
    "--to": "buyer@example.de",
    "--subject": "Kurze Frage",
    "--body": "Guten Tag,\n\neine kurze Frage.",
    "--country": "DE",
    "--state": "BE",
    "--timezone": "Europe/Berlin",
    "--language": "de-DE",
    "--language-source": "company",
    "--language-basis": "German company contact page",
    "--company-id": "11",
    "--contact-id": "22",
    "--research-id": "33",
    "--lead-updated-at": "2026-08-13T12:00:00Z",
    "--email-status": "valid",
    "--language-evidence-url": "https://example.de/kontakt",
    "--office-start": "08:30",
  };

  assert.deepEqual(previewInputFromFlags(flags), {
    to: flags["--to"],
    subject: flags["--subject"],
    body: flags["--body"],
    country: flags["--country"],
    state: flags["--state"],
    timezone: flags["--timezone"],
    language: flags["--language"],
    languageSource: flags["--language-source"],
    languageBasis: flags["--language-basis"],
    companyId: flags["--company-id"],
    contactId: flags["--contact-id"],
    researchId: flags["--research-id"],
    leadUpdatedAt: flags["--lead-updated-at"],
    emailStatus: flags["--email-status"],
    languageEvidenceUrl: flags["--language-evidence-url"],
    officeStart: flags["--office-start"],
  });
});
