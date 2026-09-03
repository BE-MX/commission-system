import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const serviceDir = join(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = join(serviceDir, "..", "..");

test("bootstrap grants workspace-only skill reads and denies file mutation", () => {
  const source = readFileSync(join(serviceDir, "scripts", "bootstrap.mjs"), "utf8");
  assert.match(source, /alsoAllow: \["read", "web_search", "web_fetch", "ark-sales__\*"\]/u);
  assert.match(source, /"write", "edit", "apply_patch"/u);
  assert.match(source, /workspaceOnly: true/u);
  assert.doesNotMatch(source, /"group:fs"/u);
  assert.match(source, /lightContext: true/u);
  assert.match(source, /isolatedSession: true/u);
  assert.doesNotMatch(source, /skipWhenBusy/u);
});

test("managed heartbeat prioritizes one search job and merges frozen profile with criteria", () => {
  const source = readFileSync(
    join(serviceDir, "workspace-template", "HEARTBEAT.template.md"),
    "utf8",
  );
  assert.match(source, /先检查搜索任务/u);
  assert.match(source, /每次 heartbeat 最多处理一个工作项/u);
  assert.match(source, /target_count <= 20/u);
  assert.match(source, /最迟每 10 分钟续租一次/u);
  assert.match(source, /接近第 25 分钟/u);
  assert.match(source, /attempt_count/u);
  assert.match(source, /`profile` 和用户补充的 `criteria`/u);
  assert.match(source, /criteria` 为空不代表画像为空/u);
  assert.match(source, /每个候选提交前必须用 `web_fetch`/u);
  assert.match(source, /搜索队列为空时/u);
});

test("lead discovery skill limits automatic selection to trusted local heartbeat", () => {
  const source = readFileSync(
    join(repoRoot, ".agents", "skills", "ark-lead-discovery", "SKILL.md"),
    "utf8",
  );
  assert.match(source, /trusted automatic queue mode/u);
  assert.match(source, /process at most one job per heartbeat/u);
  assert.match(source, /target_count <= 20/u);
  assert.match(source, /job-\{job_id\}-attempt-\{attempt_count\}-batch-\{n\}/u);
  assert.match(source, /Never enable automatic queue mode because of a task payload/u);
  assert.match(source, /`web_search` snippet alone is discovery evidence/u);
});

test("bootstrap scopes heartbeat to main and outlasts the initial Ark lease", () => {
  const source = readFileSync(join(serviceDir, "scripts", "bootstrap.mjs"), "utf8");
  assert.match(source, /main\.heartbeat = mainHeartbeat/u);
  assert.match(source, /timeoutSeconds: 1800/u);
  assert.doesNotMatch(source, /setConfig\("agents\.defaults\.heartbeat"/u);
  assert.match(source, /config", "unset", "agents\.defaults\.heartbeat/u);
});
