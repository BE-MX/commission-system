const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const PUBLIC_POOL_REACTIVATION_INACTIVE_DAYS = 60;

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

function publicPoolItems(data) {
  return Array.isArray(data?.items) ? data.items : [];
}

function parseDateOnly(value) {
  const match = String(value || "").trim().match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return null;
  const timestamp = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isFinite(timestamp) ? timestamp : null;
}

function localDateOnly(now) {
  return Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
}

export function isRecentPublicPoolReactivationTask(task, now = new Date()) {
  if (task?.tier !== "T1") return false;
  const lastOrderAt = parseDateOnly(task?.subject?.last_order_at);
  if (lastOrderAt === null) return false;
  const cutoff = localDateOnly(now) - PUBLIC_POOL_REACTIVATION_INACTIVE_DAYS * 24 * 60 * 60 * 1000;
  return lastOrderAt >= cutoff;
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

  async listPublicPoolTasks(page = 1, pageSize = 20) {
    const requestedPage = integerId(page, "page");
    const requestedPageSize = integerId(pageSize, "page_size");
    if (requestedPageSize > 100) throw new ArkApiError("page_size 不能超过100");

    // Old production batches can still contain T1 customers who ordered within
    // the 60-day reactivation exclusion window. Fetch the current claimable
    // queue before paginating locally so those stale rows never reach the model.
    const eligible = [];
    let upstreamPage = 1;
    let upstreamTotal = null;
    do {
      const query = new URLSearchParams({ page: String(upstreamPage), page_size: "100" });
      const data = await this.request(`/api/sales-automation/agent/public-pool/tasks?${query}`);
      const items = publicPoolItems(data);
      if (upstreamTotal === null) upstreamTotal = Number(data?.total ?? items.length);
      eligible.push(...items.filter((task) => !isRecentPublicPoolReactivationTask(task)));
      upstreamPage += 1;
      if (!items.length) break;
    } while ((upstreamPage - 1) * 100 < upstreamTotal);

    const offset = (requestedPage - 1) * requestedPageSize;
    return {
      items: eligible.slice(offset, offset + requestedPageSize),
      total: eligible.length,
      page: requestedPage,
      page_size: requestedPageSize,
    };
  }

  getPublicPoolTaskContext(taskId) {
    return this.request(`/api/sales-automation/agent/public-pool/tasks/${integerId(taskId, "task_id")}/context`);
  }

  async claimPublicPoolTask(taskId) {
    const id = integerId(taskId, "task_id");
    const context = await this.getPublicPoolTaskContext(id);
    if (isRecentPublicPoolReactivationTask(context?.task)) {
      throw new ArkApiError("该T1客户最近60天内存在订单，禁止加入再激活任务");
    }
    return this.request(`/api/sales-automation/agent/public-pool/tasks/${id}/claim`, {
      method: "POST",
      body: { agent_id: this.#agentId },
    });
  }

  heartbeatPublicPoolTask(taskId, leaseToken) {
    return this.#publicPoolLeaseRequest(taskId, "heartbeat", leaseToken);
  }

  submitPublicPoolIndustryGate(taskId, leaseToken, gate) {
    return this.request(`/api/sales-automation/agent/public-pool/tasks/${integerId(taskId, "task_id")}/industry-gate`, {
      method: "POST",
      body: { ...gate, agent_id: this.#agentId, lease_token: leaseToken },
    });
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
