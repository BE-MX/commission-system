import assert from "node:assert/strict";
import test from "node:test";

import { RuntimeHeartbeatReporter } from "../src/runtime-heartbeat.mjs";

test("runtime heartbeat sends the minimum contract without the Ark agent token", async () => {
  const requests = [];
  const reporter = new RuntimeHeartbeatReporter({
    baseUrl: "https://leshine.work",
    agentId: "openclaw-sales-01",
    token: "ark-agent-secret-must-not-be-sent",
    heartbeatToken: "runtime-heartbeat-secret",
  }, async (url, options) => {
    requests.push({ url, options });
    return { ok: true, status: 200 };
  });
  reporter.markActivity();
  await reporter.send();

  assert.equal(requests[0].url, "https://leshine.work/api/operations/heartbeats");
  assert.equal(requests[0].options.headers.Authorization, "Bearer runtime-heartbeat-secret");
  assert.doesNotMatch(JSON.stringify(requests), /ark-agent-secret-must-not-be-sent/);
  const body = JSON.parse(requests[0].options.body);
  assert.equal(body.service_id, "openclaw-sales-agent");
  assert.equal(body.instance_id, "openclaw-sales-01");
  assert.ok(body.last_activity_at);
  assert.ok(requests[0].options.signal instanceof AbortSignal);
});

test("runtime heartbeat is single-flight while a network request is pending", async () => {
  let resolveFetch;
  const reporter = new RuntimeHeartbeatReporter({
    baseUrl: "https://leshine.work",
    agentId: "openclaw-sales-01",
    timeoutMs: 10_000,
    heartbeatToken: "runtime-heartbeat-secret",
  }, () => new Promise((resolve) => { resolveFetch = resolve; }));

  const first = reporter.send();
  assert.equal(await reporter.send(), false);
  resolveFetch({ ok: true, status: 200 });
  assert.equal(await first, true);
});
