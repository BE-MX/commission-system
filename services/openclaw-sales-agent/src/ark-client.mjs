const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;

export class ArkApiError extends Error {
  constructor(message, status = null, retryable = false) {
    super(message);
    this.name = "ArkApiError";
    this.status = status;
    this.retryable = retryable;
  }
}

function integerId(value, field) {
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    throw new ArkApiError(`${field} 必须是正整数`);
  }
  return parsed;
}

export class ArkClient {
  #baseUrl;
  #token;
  #agentId;
  #timeoutMs;
  #fetch;

  constructor(config, fetchImpl = globalThis.fetch) {
    this.#baseUrl = config.baseUrl;
    this.#token = config.token;
    this.#agentId = config.agentId;
    this.#timeoutMs = Number.isFinite(config.timeoutMs) && config.timeoutMs > 0
      ? config.timeoutMs
      : 30000;
    this.#fetch = fetchImpl;
  }

  get agentId() {
    return this.#agentId;
  }

  #redact(value) {
    return String(value || "").split(this.#token).join("[REDACTED]");
  }

  async request(path, { method = "GET", body } = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.#timeoutMs);
    let response;
    try {
      response = await this.#fetch(`${this.#baseUrl}${path}`, {
        method,
        redirect: "manual",
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${this.#token}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });

      if (response.status >= 300 && response.status < 400) {
        throw new ArkApiError(`Ark API 拒绝跨地址重定向 (HTTP ${response.status})`, response.status);
      }
      const declaredLength = Number.parseInt(response.headers.get("content-length") || "0", 10);
      if (declaredLength > MAX_RESPONSE_BYTES) {
        throw new ArkApiError("Ark API 响应超过安全上限", response.status);
      }
      const raw = await response.text();
      if (Buffer.byteLength(raw, "utf8") > MAX_RESPONSE_BYTES) {
        throw new ArkApiError("Ark API 响应超过安全上限", response.status);
      }

      let payload;
      try {
        payload = raw ? JSON.parse(raw) : null;
      } catch {
        throw new ArkApiError(`Ark API 返回了无效 JSON (HTTP ${response.status})`, response.status);
      }
      if (!response.ok) {
        const detail = Array.isArray(payload?.detail)
          ? payload.detail.slice(0, 8).map((issue) => {
            // Never echo FastAPI input/ctx/msg: they can contain credentials or raw records.
            const location = Array.isArray(issue?.loc) ? issue.loc.join(".") : "body";
            return `${location}: ${typeof issue?.type === "string" ? issue.type : "validation_error"}`;
          }).join("; ")
          : typeof payload?.detail === "string"
          ? payload.detail
          : (typeof payload?.message === "string" ? payload.message : "请求失败");
        throw new ArkApiError(
          `Ark API HTTP ${response.status}: ${this.#redact(detail).split(body?.lease_token || "\u0000").join("[REDACTED]").slice(0, 500)}`,
          response.status,
        );
      }
      if (!payload || payload.code !== 200 || !("data" in payload)) {
        throw new ArkApiError("Ark API 响应不符合统一信封契约", response.status);
      }
      return payload.data;
    } catch (error) {
      if (error instanceof ArkApiError) throw error;
      if (error?.name === "AbortError") {
        throw new ArkApiError("Ark API 请求超时", null, true);
      }
      throw new ArkApiError("Ark API 网络请求失败", null, true);
    } finally {
      clearTimeout(timeout);
    }

  }

  listSearchJobs(status = "claimable", page = 1, pageSize = 20) {
    const query = new URLSearchParams({ status, page: String(page), page_size: String(pageSize) });
    return this.request(`/api/sales-automation/agent/search-jobs?${query}`);
  }

  getSearchJobContext(jobId) {
    return this.request(`/api/sales-automation/agent/search-jobs/${integerId(jobId, "job_id")}/context`);
  }

  claimSearchJob(jobId) {
    return this.request(`/api/sales-automation/agent/search-jobs/${integerId(jobId, "job_id")}/claim`, {
      method: "POST",
      body: { agent_id: this.#agentId },
    });
  }

  heartbeatSearchJob(jobId, leaseToken) {
    return this.#leaseRequest(jobId, "heartbeat", leaseToken);
  }

  completeSearchJob(jobId, leaseToken) {
    return this.#leaseRequest(jobId, "complete", leaseToken);
  }

  failSearchJob(jobId, leaseToken, errorCode) {
    return this.request(`/api/sales-automation/agent/search-jobs/${integerId(jobId, "job_id")}/fail`, {
      method: "POST",
      body: {
        agent_id: this.#agentId,
        lease_token: leaseToken,
        error_code: String(errorCode || "").slice(0, 64),
      },
    });
  }

  async submitCandidates(jobId, leaseToken, requestKey, candidates) {
    const path = `/api/sales-automation/agent/search-jobs/${integerId(jobId, "job_id")}/candidates`;
    // Snapshot before awaiting: a lost response may still mean the batch committed.
    const body = JSON.parse(JSON.stringify({
      agent_id: this.#agentId, lease_token: leaseToken,
      request_key: requestKey, candidates,
    }));
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        return await this.request(path, { method: "POST", body });
      } catch (error) {
        if (!(error instanceof ArkApiError) || !error.retryable) throw error;
        if (attempt === 1) {
          throw new ArkApiError("候选提交结果未确认：已按原 request_key 和完整原批次重试；只能原样重试，不得换 key、拆分或修改候选", null, true);
        }
      }
    }
  }

  searchKnowledge(query, limit = 10) {
    const cleanQuery = String(query || "").trim();
    if (!cleanQuery) throw new ArkApiError("知识库检索词不能为空");
    const boundedLimit = Math.min(Math.max(Number(limit) || 10, 1), 20);
    const params = new URLSearchParams({ q: cleanQuery, limit: String(boundedLimit) });
    return this.request(`/api/sales-automation/agent/knowledge/search?${params}`);
  }

  getKnowledgeDocument(documentId) {
    return this.request(`/api/sales-automation/agent/knowledge/documents/${integerId(documentId, "document_id")}`);
  }

  listResearchTasks(page = 1, pageSize = 20) {
    const query = new URLSearchParams({
      page: String(integerId(page, "page")),
      page_size: String(integerId(pageSize, "page_size")),
    });
    if (Number(query.get("page_size")) > 100) throw new ArkApiError("page_size 不能超过100");
    return this.request(`/api/sales-automation/agent/research-tasks?${query}`);
  }

  getResearchTaskContext(taskId) {
    return this.request(`/api/sales-automation/agent/research-tasks/${integerId(taskId, "research_task_id")}/context`);
  }

  getCustomerOutreachContext(customerId) {
    return this.request(`/api/sales-automation/agent/customers/${integerId(customerId, "customer_id")}/outreach-context`);
  }

  claimResearchTask(taskId) {
    return this.request(`/api/sales-automation/agent/research-tasks/${integerId(taskId, "research_task_id")}/claim`, {
      method: "POST",
      body: { agent_id: this.#agentId },
    });
  }

  heartbeatResearchTask(taskId, leaseToken) {
    return this.#researchLeaseRequest(taskId, "heartbeat", leaseToken);
  }

  submitResearchIndustryGate(taskId, leaseToken, gate) {
    return this.request(`/api/sales-automation/agent/research-tasks/${integerId(taskId, "research_task_id")}/industry-gate`, {
      method: "POST",
      body: { ...gate, agent_id: this.#agentId, lease_token: leaseToken },
    });
  }

  appendResearchFacts(taskId, leaseToken, agentRunId, facts) {
    return this.request(`/api/sales-automation/agent/research-tasks/${integerId(taskId, "research_task_id")}/facts`, {
      method: "POST",
      body: {
        agent_id: this.#agentId,
        lease_token: leaseToken,
        agent_run_id: integerId(agentRunId, "agent_run_id"),
        facts,
      },
    });
  }

  completeResearchTask(taskId, leaseToken, research) {
    return this.request(`/api/sales-automation/agent/research-tasks/${integerId(taskId, "research_task_id")}/complete`, {
      method: "POST",
      body: { ...research, agent_id: this.#agentId, lease_token: leaseToken },
    });
  }

  failResearchTask(taskId, leaseToken, errorCode) {
    return this.request(`/api/sales-automation/agent/research-tasks/${integerId(taskId, "research_task_id")}/fail`, {
      method: "POST",
      body: {
        agent_id: this.#agentId,
        lease_token: leaseToken,
        error_code: String(errorCode || "").slice(0, 64),
      },
    });
  }

  #leaseRequest(jobId, action, leaseToken) {
    return this.request(`/api/sales-automation/agent/search-jobs/${integerId(jobId, "job_id")}/${action}`, {
      method: "POST",
      body: { agent_id: this.#agentId, lease_token: leaseToken },
    });
  }

  #researchLeaseRequest(taskId, action, leaseToken) {
    return this.request(`/api/sales-automation/agent/research-tasks/${integerId(taskId, "research_task_id")}/${action}`, {
      method: "POST",
      body: { agent_id: this.#agentId, lease_token: leaseToken },
    });
  }
}

export class LeaseStore {
  #leases = new Map();

  remember(jobId, leaseToken, leaseExpiresAt) {
    const id = integerId(jobId, "job_id");
    if (typeof leaseToken !== "string" || leaseToken.length < 32) {
      throw new ArkApiError("Ark API 未返回有效租约");
    }
    this.#leases.set(id, { token: leaseToken, expiresAt: leaseExpiresAt || null });
  }

  require(jobId) {
    const id = integerId(jobId, "job_id");
    const lease = this.#leases.get(id);
    if (!lease) {
      throw new ArkApiError("当前 MCP 进程不持有该任务租约，请先调用 ark_claim_search_job");
    }
    return lease;
  }

  forget(jobId) {
    this.#leases.delete(integerId(jobId, "job_id"));
  }
}
