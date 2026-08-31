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
    "--customer-id": "11",
    "--contact-id": "22",
    "--contact-point-id": "23",
    "--profile-version-id": "33",
    "--fact-ids": "44,45",
    "--evidence-ids": "55,56",
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
    customerId: flags["--customer-id"],
    contactId: flags["--contact-id"],
    contactPointId: flags["--contact-point-id"],
    profileVersionId: flags["--profile-version-id"],
    factIds: ["44", "45"],
    evidenceIds: ["55", "56"],
    emailStatus: flags["--email-status"],
    languageEvidenceUrl: flags["--language-evidence-url"],
    officeStart: flags["--office-start"],
  });
});
