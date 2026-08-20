#!/usr/bin/env node

import { lstat, readFile, realpath } from "node:fs/promises";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ALLOWED = new Map([
  ["outreach", ["ark-email-outreach", "SKILL.md"]],
  ["course", ["ark-email-outreach", "references", "course-methods.md"]],
  ["localization", ["ark-email-outreach", "references", "localization-and-timing.md"]],
  ["negotiation", ["ark-email-outreach", "references", "negotiation.md"]],
  ["agent-mail", ["agently-mail", "SKILL.md"]],
]);

async function trustedFile(root, segments) {
  const configuredRoot = resolve(root);
  const rootMetadata = await lstat(configuredRoot);
  if (!rootMetadata.isDirectory() || rootMetadata.isSymbolicLink()) {
    throw new Error("installed skill root must be a real directory");
  }
  const resolvedRoot = await realpath(configuredRoot);
  let current = resolvedRoot;
  for (const segment of segments) {
    current = join(current, segment);
    const metadata = await lstat(current);
    if (metadata.isSymbolicLink()) throw new Error("installed skill path must not contain symlinks");
  }
  const resolvedFile = await realpath(current);
  const rel = relative(resolvedRoot, resolvedFile);
  if (!rel || rel.startsWith("..") || rel.includes("/../")) {
    throw new Error("installed skill path escaped its trusted root");
  }
  const metadata = await lstat(resolvedFile);
  if (!metadata.isFile()) throw new Error("installed skill path must be a regular file");
  return resolvedFile;
}

export async function main(argv = process.argv.slice(2)) {
  if (argv.length !== 1 || !ALLOWED.has(argv[0])) {
    throw new Error(`usage: outreach-skill-reader <${[...ALLOWED.keys()].join("|")}>`);
  }
  const root = process.env.OUTREACH_SKILL_ROOT;
  if (!root) throw new Error("OUTREACH_SKILL_ROOT is not configured");
  process.stdout.write(await readFile(await trustedFile(root, ALLOWED.get(argv[0])), "utf8"));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 2;
  });
}
