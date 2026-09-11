# 方舟客户邮件触达闭环：开发邮件自动发送功能设计规划

设计日期：2026-09-11。上游方案：会话附件《方舟客户经营：个性化开发信与自动定时发送开发计划》（2026-09-09，基线 `b0d58ea6`）。本次设计基于 `main`（`915837f6`）的只读代码核查，未修改业务代码。

本文把上游方案的工作包 A–F 落成可执行的工程设计：数据模型、API、状态机、模块划分、关键流程、分阶段任务拆解与验收。上游方案中的业务边界（人工审批、单发一次、停发条件、待拍板事项）不在本文重复论证，直接作为设计约束执行。

## 一、设计目标与约束

**目标：** 业务员在方舟内完成"选客户 → 生成有证据的多语言草稿 → 逐封审批 → 定时自动发送 → 结果回流客户时间线"的闭环；发送只发生一次或保守待核对，AI 全程无审批权和发信凭据。

**硬约束（来自上游方案与代码核查）：**

- 方舟数据库是唯一可发送任务源；不维护原型 JSON 队列与主站两套待发状态。
- 排程算法只有一份实现：`services/openclaw-sales-agent/src/outreach-schedule.mjs`（纯函数库，依赖 luxon + date-holidays + Node ICU 周末数据），禁止 Python 重写。
- 审批绑定"具体发件人 + 精确收件人 + 内容版本 + 排程政策"的哈希；批准后任何关键变化使审批失效。
- 到点发送前必须在服务端完成临发复查（上游方案 §D 指出的缺口：原型 `dispatchDue` 只校验本地哈希/时间/状态，调用 send 前不拉取 Ark 最新状态——已核实属实，`src/outreach-queue.mjs:281-383` 无任何 Ark 依赖）。
- 业务时间列存无时区北京时间（`app/core/time.py` 约定）；跨机器租约与对 Node 的协议交换用 UTC/带偏移 ISO 格式。
- 发送通道为 Agent Mail 官方 CLI（`agently-cli message +send ... --confirmed`），固定版本做契约测试；不逆向网页接口。

## 二、总体架构

```text
┌─────────────────────────── 方舟主站（FastAPI，唯一业务状态源）──────────────────────────┐
│ 前端审核工作台 ──► /api/mail-outreach/*（人类 JWT + 动作权限 + 客户 ACL）              │
│                        │                                                             │
│   backend/app/mail_outreach/ 域                                                      │
│     context_service ── 触达安全快照（扩展 outreach_service 缺失字段）                 │
│     eligibility_service ── 服务端统一触达资格                                        │
│     generation_service ── 调 app.ai.service（preset=mail_outreach_generate）         │
│     approval_service ── 审批 + 哈希锁定 + 失效                                       │
│     job_service ── 唯一待发队列、租约/fencing、撤销                                  │
│     precheck_service ── 临发复查（worker send-authorize 时执行）                     │
│     event_service ── 收件分类、去重、抑制、回流 CustomerEvent/Action                 │
│     schedule_client ── 调 Node 排程侧车（preview）                                   │
│                        │                                                             │
│   APScheduler 仅作"到期扫描唤醒器"，不是队列（schedulers/registry.py 模式）           │
└───────────────────────────────▲───────────────────────────┬──────────────────────────┘
          worker 受限接口        │                           │ 排程 preview（内网 HTTP+令牌）
┌───────────────────────────────┴───────────────────────────▼──────────────────────────┐
│ Node 邮件工作进程（services/openclaw-sales-agent 扩展，Node ≥24.15 独立运行时）        │
│   outreach-worker.mjs    轮询/认领 → send-authorize → 临发复查 → CLI 发送 → 回写     │
│   mail-schedule sidecar  复用 outreach-schedule.mjs 的 HTTP 薄封装（preview/健康）    │
│   mail-ingest.mjs        agently-cli message +watch → 去重 → ingest-event           │
│   dispatch 适配层         在 scripts/outreach-dispatch.mjs 基础上加固（见 §7.5）      │
└───────────────────────────────────────────┬──────────────────────────────────────────┘
                                            │ 官方 CLI（OAuth 由人完成，受控账号保管）
                                            ▼
                                      Agent Mail 通道
```

**关键决策：**

| 决策 | 结论 | 理由 |
|---|---|---|
| 排程算法复用方式 | Node 侧车 HTTP 服务，主站 `schedule_client` 调用；worker 内部直接 import 同一模块 | `outreach-schedule.mjs` 是无副作用纯库（确认：无 argv/env/文件 I/O，`now` 可注入，返回纯 JSON）；周末数据来自 V8 ICU `Intl.Locale.getWeekInfo()`，Python 移植必漂移 |
| 备选降级 | 侧车不可达时 preview 返回"排程服务不可用"；审批可走 admin 手动指定时间（`schedule_source=manual_override`），发送前 worker 仍按政策重算校验 | P1 早期侧车未部署时不阻塞审批流建设 |
| 队列归属 | 全部在方舟 DB；APScheduler 只定时触发扫描器 | 上游方案 §D 明确；现有 registry.py 有 28 个任务先例 |
| 审批模式 | 组合 `AgentArtifact` 的 accept/reject 交互 + `CustomerChangeProposal` 的 action_hash 防篡改 | "审批时内容 = 发送时内容"必须哈希锁定 |
| Worker 与 Ark 通信 | 单向：worker → 主站受限接口；主站不反向调 worker 执行发送 | worker 部署节点可能在内网/办公网，主站不假设可达 |
| 发送身份 | `mailbox_binding.worker_identity ↔ CLI workspace ↔ 发件地址` 固定映射，每次运行用 `agently-cli +me` 核对 | 原型发件身份靠 CLI OAuth 状态隐式决定，不可接受 |

## 三、数据模型设计

新建 7 张表，迁移 `backend/alembic/versions/144_mail_outreach_core.py`（当前 head 为 `143_whatsapp_reply_inquiries`；建迁移前仍须按 AGENTS.md 查所有分支最新编号）。约定：表前缀 `ark_mail_`；`created_at/updated_at` 一律 `default=beijing_now, onupdate=beijing_now`；业务时间列存北京 naive；租约/协议列存 UTC；downgrade 直接 `raise RuntimeError`（143 号迁移确立的业务表约定）。**不复制客户/联系人/抑制表**，只存引用与必要快照。

### 3.1 `ark_mail_mailbox_bindings`（发件邮箱绑定）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | |
| provider | VARCHAR(32) | 首版固定 `agent_mail` |
| sender_email | VARCHAR(255) | 发件地址；与 provider 联合唯一 |
| display_name | VARCHAR(128) | 发件人展示名 |
| owner_user_id | BIGINT FK→ark_users | 邮箱业务归属人 |
| worker_identity | VARCHAR(64) | 允许操作该邮箱的 worker 身份标识 |
| cli_workspace | VARCHAR(64) | 对应 `AGENTLY_WORKSPACE`，如 `ark-sales` |
| auth_status | VARCHAR(32) | `active / expired / unbound / unknown`（由 worker 心跳+`+me` 核对更新） |
| daily_quota | INT | 默认 50，上线时以腾讯页面为准 |
| quota_timezone | VARCHAR(64) | 配额重置时区，PoC 确认前默认 `Asia/Shanghai` |
| pause_reason | VARCHAR(255) NULL | 非空即暂停该邮箱一切发送 |
| secret_ref | VARCHAR(255) | **只存密钥引用**（受控保管位置标识），不存 OAuth token 本体 |
| status | VARCHAR(16) | `active / disabled` |

### 3.2 `ark_mail_outreach_messages` + `ark_mail_outreach_revisions`（草稿与不可变版本）

message（聚合根）：`id`、`customer_id`、`contact_id`、`contact_point_id`、`relationship_goal`（`first_intro / follow_up / reactivation`）、`status`（`draft / approved / rejected / cancelled / completed`）、`current_revision_id`、`created_by`、`created_at/updated_at`。索引：`(customer_id)`、`(contact_point_id, status)`。

revision（不可变，追加式）：`id`、`message_id`、`revision_no`（单调递增）、`subject`、`body_text`（首版纯文本）、`language_tag`（BCP 47）、`language_source`（`recipient / company / country`）、`language_basis`（TEXT，依据说明）、`meaning_summary_zh`（中文释义）、`angle`、`cta`、`claims_json`（数组，每项 `{claim, fact_id?, fact_fingerprint?, knowledge_version_id?, allowed_wording}`）、`risk_flags_json`、`evidence_snapshot_json`（生成时可见事实 ID/指纹/画像版本快照）、`recipient_timezone`、`location_evidence`、`schedule_policy_json`（office_start、顺延上限、过期政策）、`preset_name`、`preset_prompt_revision`、`content_sha256`（对规范化后的 subject+body+language+claims 计算）、`created_by`（人类或生成服务标识）、`created_at`。

### 3.3 `ark_mail_outreach_approvals`（审批）

`id`、`message_id`、`revision_id`、`approver_user_id`（必须人类，见 §8）、`decision`（`approved / rejected / revoked`）、`reason`、`mailbox_binding_id`、`to_contact_point_id`、`to_email_snapshot`（仅快照，发送时仍校验指向同一 contact point）、`approval_sha256`（对 `{content_sha256, mailbox_binding_id, to_contact_point_id, to_email_snapshot, language_tag, schedule_policy_json, scheduled_at_utc}` 规范化 JSON 的 SHA-256）、`scheduled_at_utc`、`scheduled_at_local`、`scheduled_at_beijing`、`reschedule_policy_json`（允许顺延窗口/次数）、`expires_at`（审批有效期）、`decided_at`、`revoked_at`、`revoke_reason`。唯一约束：同一 revision 至多一条 `decision=approved` 且未撤销的记录（部分唯一索引或事务内校验）。

### 3.4 `ark_mail_outreach_send_jobs`（唯一待发队列）

`id`、`idempotency_key`（CHAR(64) UNIQUE，由 message+revision 派生）、`approval_id`（UNIQUE——同一批准只生成一个 job）、`message_id`、`revision_id`、`mailbox_binding_id`、`to_contact_point_id`、`to_email_snapshot`、`status`（见 §4）、`due_at`（北京 naive，业务展示与扫描）、`due_at_utc`（协议用）、`lease_owner`（worker identity，NULL 可认领）、`lease_until_utc`、`fencing_token`（INT，每次认领 +1）、`send_started_at_utc` NULL（非空即已开始外部调用，撤销只能标"太晚"）、`reschedule_count`、`last_precheck_json`、`blocked_reason`、`created_at/updated_at`。

### 3.5 `ark_mail_outreach_send_attempts`（发送留痕，追加-only）

`id`、`job_id`、`fencing_token`（发起时的 fencing，防旧 worker 上报）、`precheck_result_json`、`provider_message_id` NULL、`provider_response_redacted`（脱敏 JSON）、`outcome`（`accepted / failed_safe / unknown`）、`error_kind`、`started_at_utc`、`finished_at_utc`。**无 update 接口，只 INSERT。**

### 3.6 `ark_mail_events` + `ark_mail_event_checkpoints`（收件事件与同步检查点）

events：`id`、`mailbox_binding_id`、`provider_message_id`、`rfc_message_id`、`in_reply_to`、`references_header`、`from_address`、`to_address`、`subject`、`received_at_utc`、`classification`（`human_reply / auto_reply / bounce / opt_out / other / uncertain`）、`classification_confidence`、`matched_job_id` NULL、`matched_customer_id` NULL、`match_basis`（`thread_header / sender_subject_candidate / manual / none`）、`processed_status`（`pending / processed / ignored / needs_human`）、`payload_redacted`、`created_at`。唯一约束 `(mailbox_binding_id, provider_message_id)` 防重复处理。

checkpoints：`mailbox_binding_id` PK、`last_seen_provider_message_id`、`last_polled_at_utc`、`watch_health`（`ok / stale / down`）。补采方式待 P0 PoC 确认，不假设有游标。

### 3.7 幂等与业务去重分层

1. 生成请求幂等：`POST /drafts` 带 `request_key`（前端按 QualificationPanel 的 `createSearchJobIdempotencyKey` 模式，表单变动即重新生成）。
2. 批准 → job：`approval_id` 唯一。
3. job → 发送尝试：`scheduled → claimed → sending` 原子状态转换 + fencing 递增，只有一次成功。
4. 收件人冷却：审批前与临发时各查一次——同一 `contact_point_id` 在冷却期（默认 14 天，进 `schedule_policy` 可配）内已存在 `provider_accepted/sending` job 则拒绝；两个不同 job 也不得重复骚扰同一客户。
5. 邮箱规范化：复用既有 contact point 规范化逻辑，**不去除 `+tag` 或点号**。

## 四、状态机

### 4.1 草稿/审批

`draft → approved`（人类审批通过，同事务创建 job）/ `draft → rejected`；`approved → cancelled`（撤销，job 未进 sending 才生效）；任何关键字段变化 → 产生新 revision，旧审批自动 `superseded`（在 approvals 上记 `revoked` + reason=`revision_superseded`）。

### 4.2 发送 job 主状态

```text
scheduled ──认领──► claimed ──授权+开始──► sending ──通道接受──► provider_accepted
   ▲                  │                       │
   │                  ├─租约过期─► scheduled  ├─明确未开始─► failed_safe（可人工重回 scheduled）
   │                  │                       ├─结果未知─► ambiguous（只准对账/人工，不自动重发）
   │                  │                       └─预检失败─► blocked / needs_review
   └──── 政策内顺延（reschedule_count 未超上限）
cancelled：终态，任何阶段可进入；send_started_at 非空时仅标注"撤销太晚"
```

收件/退信/退订是 `mail_events` 后续事件，**不用单一 `sent` 覆盖业务生命周期**；`provider_accepted` 对业务员展示为"通道已接受"，永不展示"已送达"。

### 4.3 事件分类流转

`pending → processed`（自动分类高置信度）/ `needs_human`（低置信度、候选关联、疑似退订）→ 人工确认后 `processed`；退订/硬退信确认后触发抑制写入与未开始任务取消。

## 五、API 设计

注册方式：`backend/app/mail_outreach/router.py` 定义无 prefix `router`，在 `app/routers.py` 尾部按现有模式 `include_router(..., prefix="/api/mail-outreach")`；每个端点 `Depends(require_permission(...))`。权限码 `mail_outreach:read / write / admin` 加入 `app/auth/service.py` 的 `seed_role_permissions` 列表（启动 upsert，不靠迁移）。

### 5.1 业务员/管理员接口（人类 JWT）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/context/{customer_id}` | read | 触达安全快照（§7.1），含资格结论与缺项清单 |
| POST | `/drafts` | write | 按 customer+contact+contact_point 生成草稿；body 带 `request_key` 幂等；只落草稿不外发 |
| GET | `/drafts` / `/drafts/{id}` | read | 列表（按客户/状态筛选）与详情（含当前 revision、证据账本、中文释义） |
| POST | `/drafts/{id}/revisions` | write | 编辑或请求重新生成 → 新 revision；使旧审批失效 |
| POST | `/drafts/{id}/schedule-preview` | write | 调排程侧车算候选时间，返回 `{scheduled_at_local, scheduled_at_beijing, scheduled_at_utc, timezone, skipped_reasons[]}`；**不入队** |
| POST | `/drafts/{id}/approve` | write + 人类校验 | body：`{revision_id, mailbox_binding_id, expected_content_sha256, schedule_policy, reason}`；服务端重算哈希、条件更新防并发、**同事务创建 job** |
| POST | `/drafts/{id}/reject` | write | 必填理由 |
| POST | `/drafts/{id}/revoke` | write | 撤销已批准任务 |
| GET | `/jobs` | read | 队列看板：状态/邮箱/到期时间筛选，分页 |
| POST | `/jobs/{id}/cancel` | write | 原子撤销；已开始发送返回"撤销太晚"标注结果 |
| GET | `/mailboxes` | read | 邮箱绑定列表（**永不返回凭据**，只返回 auth_status/配额用量） |
| POST/PUT | `/mailboxes` 等管理操作 | admin | 绑定/暂停/恢复/配额调整 |
| GET | `/events` | read | 收件事件列表（按客户/邮箱/分类），受客户 ACL 与数据分级过滤 |
| POST | `/events/{id}/classify` | write | 人工确认分类/关联（needs_human 处理入口） |

响应统一 `app.core.response.ok / page_result`；列表请求前端带 `showLoading: false`。

### 5.2 Worker 受限接口（`/api/mail-outreach/worker/*`）

单独子路由，**只接受 worker 专用凭证**（复用 `app.mcp.auth.resolve_token` 机制，新增权限 `mail_outreach:worker`，seed 进权限表；该 token 无任何人类路由权限，人类 JWT 也不放行这些端点——双向隔离）。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/worker/jobs/claim` | `{worker_identity, mailbox_binding_id?, limit}`；原子认领到期 job：条件更新 `status scheduled→claimed`、`lease_owner`、`lease_until_utc`、`fencing_token+1`；返回 job+payload |
| POST | `/worker/jobs/{id}/heartbeat` | 续租（携带当前 fencing，旧 fencing 拒绝） |
| POST | `/worker/jobs/{id}/send-authorize` | **临发复查核心**：携带 fencing + 本地 payload 哈希；服务端执行 §7.4 全部复查；通过则原子转换 `claimed→sending`、记 `send_started_at_utc`、返回一次性授权（绑定 job+fencing+哈希）；不通过转 `blocked/needs_review` 并返回原因 |
| POST | `/worker/jobs/{id}/report-result` | 上报 `{outcome, provider_message_id?, response_redacted, error_kind?}`；校验 fencing 与 sending 状态；写 attempt、流转 job 状态 |
| POST | `/worker/events/ingest` | 批量上报收件事件（NDJSON 逐项），服务端按 `(mailbox, provider_message_id)` 去重入库 |
| POST | `/worker/heartbeat` | worker/邮箱健康上报：更新 `auth_status`、`watch_health`、配额用量 |
| GET | `/worker/config` | 下发该 worker 的邮箱绑定、配额、总停发开关状态 |

**总停发开关**：`settings` 增加 `MAIL_OUTREACH_SEND_ENABLED`（默认 false）；`send-authorize` 与 claim 首先检查，关闭时一律拒绝。优先级高于一切队列任务。

## 六、后端模块划分

```text
backend/app/mail_outreach/
├── models.py              # §3 全部实体
├── schemas.py             # Pydantic 入出参
├── router.py              # 人类接口
├── worker_router.py       # worker 受限接口
├── context_service.py     # 触达安全快照
├── eligibility_service.py # 统一触达资格策略
├── generation_service.py  # AI 生成 + 结构校验（不调模型客户端，走 app.ai.service.chat）
├── approval_service.py    # 审批/哈希/并发/失效/撤销
├── job_service.py         # 队列、认领、租约、取消
├── precheck_service.py    # 临发复查（send-authorize 实现）
├── event_service.py       # 事件分类、去重、抑制、回流
├── schedule_client.py     # 排程侧车 HTTP 客户端（httpx，短超时，失败可降级）
└── policies.py            # 冷却期、顺延上限、配额默认值等集中常量
```

**触达安全快照（context_service）**——在 `app/customer/outreach_service.py:20` 的能力上补齐（该服务入参是已鉴权 `CustomerAccess`，鉴权模式直接沿用）：客户/联系人两级 `default_language/timezone/country_code`、联系人 `display_name/canonical_name/job_title/buying_role`（模型字段齐全，现服务没查）、事实正文（`CustomerFact` 内容，经 `access.allowed_classifications()` 过滤后投影，不把整份背调塞给生成）、画像版本 `current_profile_version_id`、获准引用的公司知识版本列表。缺时区、语言冲突、多语国家无依据、事实过期、邮箱 `unknown/risky` → 返回结构化缺项清单，`eligible=false`，前端展示具体原因。

**触达资格（eligibility_service）**——双跑抑制检查：客户级 `is_development_denied(db, cid, "channel", "email")`（`sales_automation/public_pool_service.py:119`）+ 点级 SuppressionRegistry 查询（`outreach_service.py:50-56` 模式），比对一律用 `beijing_now()` 对 `effective_at`。叠加：归属/ACL（`require_customer_access`）、`verification_status=valid`、`contactability_status=allowed`、合法触达依据记录、冷却期、最近回复检查。

**生成（generation_service）**——`chat(db, preset_name="mail_outreach_generate", ...)`（`app/ai/call_service.py:66` 签名）；preset 由 `bootstrap/seed_ai.py` 的 `auto_init_ai_presets` 幂等创建，提示词内容以 `.agents/skills/ark-email-outreach/SKILL.md` 为唯一方法源（证据账本三列、目标语言直接写作、中文释义、事实/商业承诺硬门禁），另加单元测试断言 preset 提示词与 SKILL.md 的关键门禁语句同时存在，防两套提示词漂移。输出 JSON schema：`{subject, body_text, language, meaning_summary, angle, cta, claims[], risk_flags[]}`，服务端校验：结构完整、每条 claim 的 fact_id/指纹在快照内、无未填占位符、无未批准报价/交期/库存/认证承诺（关键词+正则初筛，风险项进 `risk_flags` 供人工）、收件人与请求一致。字符脚本检测复用原型 `validateBodyScript` 思路在 Python 侧做等价初筛（仅拦明显错误，不宣称能区分同字母语言）。

**审批（approval_service）**——approve 事务内：锁 message 行 → 校验 revision 归属与 `expected_content_sha256` → 资格复查 → 计算 `approval_sha256` → 插入 approval（并发重复批准走唯一约束/条件更新，重复点击返回已有结果不新增 job）→ 同事务创建 job（`idempotency_key` 唯一兜底）。人类校验：参照 `governance_policy_service.py:69` `_require_human`，actor 必须是活跃 ArkUser；agent token 走不到此路由（worker/mcp 凭证体系分离）。

**事件回流（event_service）**——写客户时间线走 `fact_service.append_customer_event`（`event_fingerprint` 幂等）；新增事件类型（`outreach.email_accepted / email_failed / email_reply_received / email_opted_out` 等）须注册进 `EVENT_REGISTRY`（`fact_service.py:134-305`）并 bump registry 版本，注意现有 `message.received/sent` 的 source "email" 白名单与 `human_actor_required` 约束——定时任务无人类 actor，新注册项不要带 human 标志。跟进待办走 `workflow_service.create_action`（`action_fingerprint` 幂等，owner 必须在客户归属范围内）。退订/硬退信 → 写 `CustomerSuppressionRegistry`（HMAC 存储，复用现有写入路径）+ 取消该 contact point 全部未开始 job + 生成业务员待办。

**到期扫描（APScheduler）**——按 `schedulers/registry.py` 三步注册 `JOB_MAIL_OUTREACH_SCAN`（interval 60s，`max_instances=1, coalesce=True`）：只做"把到期的 scheduled job 标记为可认领/记录 missed 窗口"，**不在 Web 进程内发信**；受 `SCHEDULER_ENABLED` 与 `MAIL_OUTREACH_SEND_ENABLED` 双重开关。

## 七、Node 侧设计（services/openclaw-sales-agent 扩展）

不新建仓库目录：排程、CLI 适配、测试全在此包内，新增三个入口，esbuild 按 `build-email-tools.mjs:14-31` 模式打单文件。**运行时要求 Node ≥24.15.0（本机 v22.23.2 不满足），为邮件服务配独立 Node 运行时，不动全机环境。**

### 7.1 排程侧车 `mail-schedule-service.mjs`

薄 HTTP 封装（Node 原生 http，无新依赖）：`POST /schedule/preview` 入参 `{country, state?, timezone, language, languageSource, languageBasis, officeStart?, now?}` → 直接调 `validateLocale` + `nextEligibleSend` 返回其结果加 `skipped_reasons`；`GET /health`。监听地址与共享令牌走环境变量，仅内网/回环。与 worker 同机同进程组部署；worker 内部 import 同一 `outreach-schedule.mjs`，预览与实际计算永远是同一份代码。

### 7.2 发送 worker `outreach-worker.mjs`

主循环（间隔可配，默认 60s）：

1. `GET /worker/config`：总开关关闭或邮箱 pause → 空转。
2. `POST /worker/jobs/claim`：认领到期 job（单实例部署 + 服务端 fencing，天然单执行器；仍按多实例安全设计）。
3. **发件身份核对**：`agently-cli +me`（带对应 `AGENTLY_WORKSPACE`）返回地址必须等于 job 的 `mailbox_binding.sender_email`，不符 → 上报 failed_safe + 告警，绝不"碰巧用默认账号发"。
4. `POST /worker/jobs/{id}/send-authorize`：拿一次性发送授权；服务端临发复查（下节）。被拒 → 按返回原因结束（job 已转 blocked/needs_review）。
5. 调发送适配层 → `report-result`。任何进程中断场景：重启后扫描到 `sending` 且无回写的 job → 对该 job 调对账接口查 attempt，无 provider 凭据 → 保持 `ambiguous` 等人工，**绝不自动重发**。

### 7.3 临发复查（precheck_service，服务端，send-authorize 时执行）

按顺序全量复查，任一不过即拒并落 `last_precheck_json`：

- 总开关、邮箱绑定 active 且未 pause、`auth_status=active`；
- approval 存在、未撤销、未过期、`approval_sha256` 与 worker 携带的本地哈希一致；
- job fencing/lease 有效、状态为 claimed、未到 `expires_at`；
- 客户归属/资格仍有效（`require_customer_access` 逻辑以"发送代表人"视角复核）、`record_status=active`；
- 双跑抑制检查 + 退订事件表无新记录；`verification_status=valid` 且 `verified_at` 在有效期政策内；`contactability_status=allowed`；
- 画像/证据未变：`evidence_snapshot_json` 中 fact 指纹与画像版本与当前一致，不一致 → `needs_review`；
- 冷却期与频控；`mail_events` 中该联系人最近无人工回复（有 → `needs_review`，避免对已回复客户发预设信）；
- 该邮箱当日配额（本地保守计数 + attempt 表实际计数取保守者）；
- 时间政策：当前时刻仍在批准窗口或允许顺延范围内；超出且政策未授权 → `needs_review`（重新审核），政策内顺延 → 重算 due_at 并记录，**approval 载荷不变**（原型 `dispatchDue` 改时间重算哈希的做法废弃：批准载荷不可变，调度决策另存）。

### 7.4 发送适配层加固（对 `scripts/outreach-dispatch.mjs` 的问题清单逐项处理）

| 现状问题 | 加固设计 |
|---|---|
| `spawnSync` 退出码 0 即 ok，`message_id` 可空（:39-47） | 解析 stdout JSON 契约：必须含业务成功标志且拿到 `data.message_id` 才记 `provider_accepted`；格式不符/为空 → `unknown` 转对账。CLI 版本锁定，契约测试钉住响应格式 |
| 正文走 `--body` 命令行参数（:21） | 改为临时文件（0600、用完即删）或 stdin 传入（以 PoC 验证的 CLI 能力为准）；解决 Windows 中文/引号/换行/命令长度问题；进程参数不含正文，降低日志泄露面 |
| 超时/信号杀死语义 | 超时或信号中断且无法排除已发送 → `outcome=unknown`；只有 ENOENT/EACCES 类"明确未开始"才是 `failed_safe`（沿用 :33-37 判定） |
| 重试 | 仅 `failed_safe` 且临发复查仍通过时允许有界重试（次数进 policy）；`unknown` 只人工对账 |
| 账号失效/连续异常 | 连续 N 次 unknown/失败 → 自动 pause 邮箱 + 钉钉告警（复用 registry 的失败告警链路），人工恢复 |

### 7.5 收件 worker `mail-ingest.mjs`

常驻进程跑 `agently-cli message +watch`（NDJSON 流）：逐行解析 → `POST /worker/events/ingest` 批量上报；本地记最近成功上报的 `provider_message_id` 到本地状态文件（断线重连后补采窗口内邮件，补采能力以 P0 PoC 为准）；进程级看门狗：watch 静默超阈值 → 重启 CLI 并上报 `watch_health=stale`。CLI 断网/休眠/解绑/登录失效由 §7.2 心跳与邮箱 `auth_status` 反映到主站看板。

### 7.6 测试复用与新增

直接复用 `test/outreach-schedule.test.mjs`（11 例：09:05、假日跳过+DST、沙特/TH/TR/NG 周末、ja-JP 别名、多语国家拒绝等）与 `test/outreach-queue.test.mjs` 的规则用例（token 一次性、篡改检测、ambiguous 不重试、emailStatus≠valid 拒绝、非拉丁脚本检测）。**注意：本次只读未执行，不能直接宣称通过；Node ≥24.15 就绪后先跑 `npm test` 作为基线。** 新增：worker 主循环对 mock 主站的 claim/authorize/report 契约测试、dispatch 适配层对 mock CLI 的解析测试（含空 message_id、非零退出、超时）、`+watch` NDJSON 解析与去重测试。

## 八、前端设计

技术栈 Vue 3 + Element Plus，无 TS、无 i18n（全中文硬编码）。三处改动：

1. **客户详情抽屉新增"邮件触达"Tab**：`frontend/src/views/customer_hub/CustomerDetailDrawer.vue` 的 el-tabs 中按"待办"Tab 同模式加 lazy tab-pane（`v-any-permission="['mail_outreach:read','mail_outreach:write','mail_outreach:admin']"`）。内容：该客户草稿/任务列表 + "新建开发信"入口（选联系人/邮箱 → 拉触达上下文 → 资格缺项可视 → 触发生成）。
2. **审核抽屉**（照抄 `QualificationPanel.vue` 交互范式）：`el-drawer` 内分区展示——收件人/邮箱验证状态/发件账号；语言+依据、国家/IANA 时区、客户当地时间与北京时间并排；主题、完整正文、中文释义；证据账本表（每条 claim 的来源与允许措辞）；风险标记、退订说明、重复联系提醒。操作：`保存草稿 / 重新生成 / 请求补充背调 / 批准并排程 / 拒绝 / 撤销`，approve 提交带 `request_key` + `expected_content_sha256`，提交中禁关抽屉。按钮 `v-permission` 控写。
3. **队列工作台独立页**：`config/navigation.js` 的 `customerOperations` 分组加一条 entry（order 约 50，路由自动生成，不改 `router/index.js`）；列表基座复用 `useOperationsList`/`useListPage`，状态筛选 + `el-tag` 状态列 + 操作列撤销/查看；运行状态区展示邮箱 auth_status、配额用量、watch 健康、总开关状态；`ambiguous/needs_human` 红色置顶。轮询复用 `createSearchJobPollingController` 模式。

API 层：`clients.js` 加 `mailOutreachClient = createApiClient({ baseURL: '/api/mail-outreach' })`，新建 `api/mailOutreach.js`（Contract 模式，列表请求 `showLoading: false`）。时间展示：北京时间走 `utils/datetime.js`；**客户当地时间为空白点**，在 `datetime.js` 新增 `formatInTimeZone(date, timeZone)`（`Intl.DateTimeFormat`，时区名由后端返回，前端不维护国家→时区映射）。正文编辑纯文本 `el-input type="textarea"`，预览只读；不引入富文本。

## 九、安全与凭据

- OAuth 授权由人完成，token 存受控服务账号侧（worker 节点 0600 文件/系统密钥库），`mailbox_binding.secret_ref` 只存引用；凭据不进代码、日志、前端响应、提示词、CLI 参数。
- 三类身份隔离：人类 JWT（审批）、worker token（`mail_outreach:worker`，仅 worker 接口）、生成 AI（无任何 token，由服务端代调）。审批端点服务端 `_require_human` 式硬校验。
- 提示注入防护：客户记录/背调内容作为数据传入并在系统提示中显式标记不可信；收件内容分类前的文本同样按不可信处理，不据此执行任何指令。
- 退订公开接口（P3）：安全随机/签名令牌，不泄露邮箱或客户 ID，幂等、反滥用、防链接预抓取误操作（GET 只展示确认页，POST 才生效）。
- 前端接口不返回凭据与原始收件正文（受数据分级 + 客户 ACL 过滤）。

## 十、配置与部署

- 主站 settings 新增：`MAIL_OUTREACH_SEND_ENABLED=false`、`MAIL_OUTREACH_SCHEDULE_SERVICE_URL`、`MAIL_OUTREACH_SCHEDULE_TOKEN`、`MAIL_OUTREACH_WORKER_TOKEN`（worker 凭证）、冷却期/配额默认值进 policies 可配置。
- 权限 seeds：`mail_outreach:read/write/admin/worker` 入 `seed_role_permissions`。
- Preset seed：`mail_outreach_generate` 入 `auto_init_ai_presets`。
- 迁移：`144_mail_outreach_core.py`（7 表 + 索引 + 唯一约束）；执行前先 `git log --all --oneline -- backend/alembic/versions/` 核对所有分支编号；只用已确认隔离的开发库，不动共享生产库。
- Worker 节点：独立 Node ≥24.15 运行时；Windows 用任务计划/NSSM 常驻 + 日志轮转 + 心跳；常驻服务器方案在 P0 立项拍板（办公电脑休眠不作为调度节点）。`AGENTLY_WORKSPACE ↔ worker_identity ↔ sender_email` 对照表入部署文档。

## 十一、分阶段开发计划

交付门槛制，非日历承诺。任务颗粒度已拆到可认领级别；P 表示上游方案阶段，保持对应。

### P0：通道与环境验证（无业务代码，出结论）

1. 已确认隔离的开发库到位并可跑迁移回滚演练。
2. 固定版本 `agently-cli` + 自有测试邮箱 PoC：`+me`、发送返回 JSON 契约（成功标志/message_id 位置）、超时行为、`message +watch` NDJSON 字段与断线补采能力、配额扣减/重置口径、服务侧退订页行为。产出：`services/openclaw-sales-agent/test/` 下的契约测试与《通道契约记录》。
3. Node ≥24.15 独立运行时安装验证 + `npm test` 基线跑通。
4. 腾讯条款确认（公司平台开发信用途/标识/自动化许可）——**P3 真实发送的硬准入**。
5. 常驻节点方案拍板。

### P1：方舟内草稿与审核（外发总开关保持关闭）

| # | 任务 | 产出 |
|---|---|---|
| 1.1 | 迁移 144：7 表 + 约束 | alembic 升级/（拒绝）降级演练通过 |
| 1.2 | context_service + eligibility_service + `GET /context/{customer_id}` | 缺项清单单测（缺时区/语言冲突/邮箱 unknown/被抑制均 eligible=false） |
| 1.3 | preset seed + generation_service + `POST /drafts`、`/revisions` | claim 证据校验、占位符/承诺初筛、版本不可变单测 |
| 1.4 | approval_service + approve/reject/revoke + job 同事务创建 | 并发双批准只一 job、哈希失配拒绝、agent token 无法审批的测试 |
| 1.5 | 排程侧车 + schedule_client + `schedule-preview` | 预览返回当地/北京/UTC 三时间；侧车不可达降级路径 |
| 1.6 | 前端：详情抽屉 Tab + 审核抽屉 + drafts API 模块 | 业务员完成"选客户→草稿→证据核对→批准"全流程，job 落库但永不外发 |

门槛：1.1–1.6 全绿；审核界面 §八.2 的信息项逐项可展示。

### P2：受控定时发送（只发测试收件人名单）

| # | 任务 | 产出 |
|---|---|---|
| 2.1 | job_service 认领/租约/fencing + worker claim/heartbeat 接口 | 双 worker 并发认领只一人成功的集成测试 |
| 2.2 | precheck_service + send-authorize | §7.3 全项测试：退订/归属变更/证据变化/解绑/超窗各阻断用例 |
| 2.3 | dispatch 适配层加固 + worker 主循环 + report-result | mock CLI 下 accepted/failed_safe/unknown 三路径；进程崩溃恢复不重复发 |
| 2.4 | 配额计数 + 暂停/恢复 + 总开关 | 临近上限顺延、开关关闭全链路空转测试 |
| 2.5 | 到期扫描 APScheduler 注册 + 机器休眠恢复策略 | 休眠恢复不集中补发过时邮件的仿真测试 |
| 2.6 | Windows 部署：任务计划/NSSM + 日志轮转 + 心跳 + `+me` 身份核对 | 部署手册 + 重启演练记录 |
| 2.7 | 队列工作台页面 | 测试名单内端到端：批准→到点→accepted→时间线可见 |

门槛：重启、并发认领、CLI 超时、撤销竞争、跨时区（至少覆盖 DST 国家与周五六周末国家）全部在测试名单内通过。

### P3：回流与真实客户试点（依赖 P0 条款结论）

1. mail-ingest worker + 事件分类/去重/候选关联 + needs_human 人工台。
2. 退订/硬退信 → 抑制注册表 + 取消未开始任务 + 业务员待办；退订公开页（签名令牌）。
3. `EVENT_REGISTRY` 新增 outreach 事件类型（bump 版本）+ `create_action` 跟进待办。
4. 运行看板完善（审核量/通道接受/失败/未知/回复/退订）+ 异常操作手册。
5. 试点名单与触达依据补录（邮箱 `valid/allowed` 缺口先补）；业务负责人确认发送身份后开真实发送。

### P4：试点后迭代（按证据决定）

语言/切入点评估、按响应优化发送时间、跟进建议、多账号受控推广。不以"能发出"替代业务有效。

## 十二、测试与发布纪律

- 后端 pytest 只连隔离库；前端执行现有 build/check；收工跑 `python scripts/git_sweep.py --no-fetch`；不自动提交/推送/部署。
- 端到端必测清单直接采用上游方案 §九（证据完整生成、无资格不排程、模型无法自批、批准失效、并发/崩溃不重复发、临发阻断、假日/DST/顺延、CLI 超时转 ambiguous、休眠恢复、事件去重与正确归类、凭据零泄露、退订阻断），逐条对应到 P1–P3 的测试用例，验收时逐条打勾。
- 发布顺序：`dry_run`（总开关关）→ 测试收件人名单 → 明确业务授权后逐步开放；停发条件触发即关总开关，人工查清再恢复。

## 十三、风险与开放问题

1. **腾讯条款与通道契约**（P0 出结论，最大外部依赖）：条款不适用则只替换发送适配层，其余设计不受影响。
2. **配额/退订/补采语义**未 PoC 前，相关字段（quota_timezone、checkpoints、退订同步）按"可配置、可人工兜底"设计，不承诺自动化。
3. **多实例安全**：首版 worker 单实例部署即可，但租约/fencing 按多实例正确性设计，避免横向扩展时重做。
4. **画像证据漂移**：`evidence_snapshot_json` 与当前画像不一致一律 `needs_review` 而非自动放行，试点期可能偏保守，按数据调阈值。
5. 待拍板事项维持上游方案 §十的 6 项，P0 评审时逐项落定。
