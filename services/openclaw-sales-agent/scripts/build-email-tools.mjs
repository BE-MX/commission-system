#!/usr/bin/env node

import { build } from "esbuild";
import { chmod, mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const serviceDir = resolve(fileURLToPath(new URL("..", import.meta.url)));
const outputDir = resolve(serviceDir, "dist");
const nodeBin = process.env.OPENCLAW_NODE || join(homedir(), ".openclaw", "tools", "node", "bin", "node");
await mkdir(outputDir, { recursive: true });

for (const name of ["outreach-queue", "outreach-dispatch", "outreach-skill-reader"]) {
  const outfile = resolve(outputDir, name);
  await build({
    entryPoints: [resolve(serviceDir, "scripts", `${name}.mjs`)],
    outfile,
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node24",
    sourcemap: false,
    legalComments: "none",
  });
  const contents = await readFile(outfile, "utf8");
  await writeFile(outfile, `#!${nodeBin}\n${contents.replace(/^#![^\n]*\n/u, "")}`, {
    encoding: "utf8", mode: 0o700,
  });
  await chmod(outfile, 0o700);
}
