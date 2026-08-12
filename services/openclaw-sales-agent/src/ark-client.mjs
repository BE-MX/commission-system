const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;

export class ArkApiError extends Error {
  constructor(message, status = null) {
    super(message);
    this.name = "ArkApiError";
    this.status = status;
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
    } catch (error) {
      if (error?.name === "AbortError") {
        throw new ArkApiError("Ark API 请求超时");
      }
      throw new ArkApiError("Ark API 网络请求失败");
    } finally {
      clearTimeout(timeout);
    }

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
      const detail = typeof payload?.detail === "string"
        ? payload.detail
        : (typeof payload?.message === "string" ? payload.message : "请求失败");
      throw new ArkApiError(
        `Ark API HTTP ${response.status}: ${this.#redact(detail).slice(0, 500)}`,
        response.status,
      );
    }
    if (!payload || payload.code !== 200 || !("data" in payload)) {
      throw new ArkApiError("Ark API 响应不符合统一信封契约", response.status);
    }
    return payload.data;
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

  failSearchJob(jobId, leaseToken, errorMessage) {
    return this.request(`/api/sales-automation/agent/search-jobs/${integerId(jobId, "job_id")}/fail`, {
      method: "POST",
      body: {
        agent_id: this.#agentId,
        lease_token: leaseToken,
        error_message: String(errorMessage || "").slice(0, 2000),
      },
    });
  }

  submitCandidates(jobId, leaseToken, requestKey, candidates) {
    return this.request(`/api/sales-automation/agent/search-jobs/${integerId(jobId, "job_id")}/candidates`, {
      method: "POST",
      body: {
        agent_id: this.#agentId,
        lease_token: leaseToken,
        request_key: requestKey,
        candidates,
      },
    });
  }

  getLead(companyId) {
    return this.request(`/api/sales-automation/agent/leads/${integerId(companyId, "company_id")}`);
  }

  saveContacts(companyId, contacts) {
    return this.request(`/api/sales-automation/agent/leads/${integerId(companyId, "company_id")}/contacts`, {
      method: "POST",
      body: { contacts },
    });
  }

  saveResearch(companyId, research) {
    return this.request(`/api/sales-automation/agent/leads/${integerId(companyId, "company_id")}/research`, {
      method: "POST",
      body: research,
    });
  }

  listPublicPoolTasks(page = 1, pageSize = 20) {
    const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    return this.request(`/api/sales-automation/agent/public-pool/tasks?${query}`);
  }

  getPublicPoolTaskContext(taskId) {
    return this.request(`/api/sales-automation/agent/public-pool/tasks/${integerId(taskId, "task_id")}/context`);
  }

  claimPublicPoolTask(taskId) {
    return this.request(`/api/sales-automation/agent/public-pool/tasks/${integerId(taskId, "task_id")}/claim`, {
      method: "POST",
      body: { agent_id: this.#agentId },
    });
  }

  heartbeatPublicPoolTask(taskId, leaseToken) {
    return this.#publicPoolLeaseRequest(taskId, "heartbeat", leaseToken);
  }

  completePublicPoolTask(taskId, leaseToken, research) {
    return this.request(`/api/sales-automation/agent/public-pool/tasks/${integerId(taskId, "task_id")}/complete`, {
      method: "POST",
      body: { ...research, agent_id: this.#agentId, lease_token: leaseToken },
    });
  }

  failPublicPoolTask(taskId, leaseToken, errorMessage) {
    return this.request(`/api/sales-automation/agent/public-pool/tasks/${integerId(taskId, "task_id")}/fail`, {
      method: "POST",
      body: {
        agent_id: this.#agentId,
        lease_token: leaseToken,
        error_message: String(errorMessage || "").slice(0, 2000),
      },
    });
  }

  #leaseRequest(jobId, action, leaseToken) {
    return this.request(`/api/sales-automation/agent/search-jobs/${integerId(jobId, "job_id")}/${action}`, {
      method: "POST",
      body: { agent_id: this.#agentId, lease_token: leaseToken },
    });
  }

  #publicPoolLeaseRequest(taskId, action, leaseToken) {
    return this.request(`/api/sales-automation/agent/public-pool/tasks/${integerId(taskId, "task_id")}/${action}`, {
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
