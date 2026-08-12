export class RuntimeHeartbeatReporter {
  constructor(config, fetchImpl = globalThis.fetch) {
    this.config = config;
    this.fetchImpl = fetchImpl;
    this.startedAt = new Date().toISOString();
    this.lastActivityAt = null;
    this.timer = null;
    this.inFlight = false;
  }

  markActivity() {
    this.lastActivityAt = new Date().toISOString();
  }

  async send() {
    if (!this.config.heartbeatToken || this.inFlight) return false;
    this.inFlight = true;
    try {
      const timeoutMs = Math.max(1_000, Math.min(this.config.timeoutMs || 10_000, 10_000));
      const response = await this.fetchImpl(`${this.config.baseUrl}/api/operations/heartbeats`, {
        method: "POST",
        redirect: "error",
        signal: AbortSignal.timeout(timeoutMs),
        headers: {
          Authorization: `Bearer ${this.config.heartbeatToken}`,
          "Content-Type": "application/json",
          "User-Agent": "ark-openclaw-heartbeat/1.0",
        },
        body: JSON.stringify({
          service_id: "openclaw-sales-agent",
          instance_id: this.config.agentId,
          service_name: "OpenClaw 销售 Agent",
          environment: "OpenClaw",
          version: "0.1.0",
          status: "healthy",
          started_at: this.startedAt,
          last_activity_at: this.lastActivityAt,
          capabilities: ["lead-discovery", "company-research", "public-pool-research"],
          dependencies: ["ark-api", "ark-sales-mcp"],
        }),
      });
      if (!response.ok) throw new Error(`heartbeat returned HTTP ${response.status}`);
      return true;
    } finally {
      this.inFlight = false;
    }
  }

  start(intervalMs = 60_000) {
    if (!this.config.heartbeatToken || this.timer) return;
    const report = () => this.send().catch((error) => {
      console.error(`ark-sales heartbeat failed: ${error instanceof Error ? error.name : "unknown"}`);
    });
    void report();
    this.timer = setInterval(report, intervalMs);
    this.timer.unref?.();
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
}
