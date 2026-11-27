# AI 接入管理重设计：设计文档

> 版本：v0.3 · 2026-11-27 · 状态：**需求已确认，待排期实施**（v0.3 吸收代码库全链路深查评估与 Q1–Q6 拍板结论，见 §10）
> 需求：[requirements.md](requirements.md) · 原型：[prototype/index.html](prototype/index.html)
> 现有代码：`backend/app/ai/`（models / provider_service / preset_service / call_service / stream_service / image_service / agent_service / log_service / router）、`backend/app/ai_chat/`、`backend/app/bootstrap/seed_ai.py`、`frontend/src/views/system/AIManager.vue`、`frontend/src/views/system/composables/useAiManager.js`

---

## 1. 设计结论（先看这里）

1. **“订阅源”不新建主实体，复用 `ark_ai_providers`**。订阅与展示元数据拆到 1:1 新表 `ark_ai_provider_billings`（复数表名，含 `service_kind` 区分直连/中转站，不改 `provider_type` 枚举）；余额登记与充值记录落独立流水表 `ark_ai_balance_checkpoints`（保留历史与漂移快照）。
2. **“订阅管理”取代“提供商管理”Tab，并取代原页面顶部旧 4 张统计卡**。卡片为默认视图，保留表格视图切换及原提供商全部技术能力。
3. **统一价格源，收编既有定价**：`ark_ai_model_prices` 作为全平台唯一主单价表（`DECIMAL(14,6)`，支持 `token / per_call / image_rate_card`），收编现有 `parameters.chat.pricing` 并兼容生图 `rate_card`，避免同一页面多套账本打架。
4. **费用在调用结束时计算并固化，覆盖全部 5 条主调用链 + 3 条兜底链**：`call_service`（`chat` / `delegate`）、`stream_service`、`image_service`（`generate_image` / `edit_image`）、`agent_service`（排除保守预扣 `reservation`）以及外部 pending 清理。计费代码抽入独立 `billing_service.py`，永远不改变业务调用结果。
5. **续费/周期与余额正交可选（不互斥）**：填了续费/到期日即展示周期段（以“周期已过进度”呈现），登记过余额即展示余额段（以上次登记基准为 100% 分母），由 `is_balance_deducted_by_usage` 控制是否按调用扣减；余额截点精确到秒（默认 `beijing_now()`），杜绝当天重复扣减。
6. **状态在后端计算、告警按维度独立统计**：主状态用于卡片主徽章，次要告警用副标签展示；顶部汇总“续费提醒”和“余额预警”各自按维度独立计数，互不遮蔽；全平台消费汇总包含已停用及已软删提供商的历史日志（总账守恒），并与“在用固定订阅月折算”并列展示、不混算。
7. **预设归属用字段 `feature_key`**，来源为 `backend/app/ai/feature_catalog.py`（导航分组 + 内置非导航类），迁移写死回填快照，且启动种子 `seed_ai.py` / `seed_fx_settlement.py` / `seed_whatsapp_reply.py` 同步写入。

---

## 2. 信息架构

```
AI 接入管理（整页 ai:admin；移除原 Tabs 上方旧 4 卡，各 Tab 内自有汇总）
├─ 订阅管理（新，默认）   OverviewMetricCard 汇总条 · 多维筛选排序 · 卡片/表格切换 · 录入与单价抽屉
├─ 预设管理（改造）       功能面包屑 × 提供商 × 模型 三层标签筛选 · 分组列表 · 详情抽屉（保留测试/复制）
├─ 调用日志（小改）       新增按提供商/费用状态筛选 · 列表显示费用状态 · 模块筛选改读 feature_catalog · SQL 聚合
├─ 聊天运行               一期末不变；二期切读统一单价表与日志费用快照
└─ 站点应用               不变
```

**为什么合并“提供商管理”并移除顶部旧 4 卡**：
- 提供商与订阅源是同一批实体，分开会在两处改同一家配置；抽屉内分「连接配置」「订阅与周期」「余额与流水」「模型单价」四段管理。
- 原 `AIManager.vue` 顶部 4 张统计卡与新订阅汇总条存在视觉叠罗汉，且原“今日调用 / 本月累计 Token”实为未过滤日期的全表统计；移除后在 Tab 标签附带数量角标，调用明细汇总归调用日志 Tab。

---

## 3. 数据模型（严格遵循 `docs/database.md` 命名宪法）

所有新表均使用复数表名、表级 `comment`、全列中文 `comment=`、北京时间 `DATETIME` 及审计操作人列（`INT UNSIGNED`，匹配 `ark_users.id`）。

### 3.1 新增表 `ark_ai_provider_billings`（订阅与账务元数据，1:1 提供商）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | `INT PK AUTO_INCREMENT` | 主键 |
| `provider_id` | `INT UNIQUE NOT NULL FK → ark_ai_providers.id` | 1:1 关联提供商（与主表 `id` 同为有符号 INT） |
| `service_kind` | `ENUM('official','relay') NOT NULL DEFAULT 'official'` | 接入渠道分类：直连官方 / 第三方中转站（ACCIO WORK 不强依赖此列；**不修改 `ark_ai_providers.provider_type`**） |
| `plan_name` | `VARCHAR(64) NULL` | 套餐名 |
| `billing_mode` | `ENUM('monthly','quarterly','yearly','pay_as_you_go') NOT NULL DEFAULT 'pay_as_you_go'` | 主计费方式 |
| `is_balance_deducted_by_usage` | `BOOLEAN NOT NULL DEFAULT TRUE` | 是否按调用估算扣减余额（按量默认 `TRUE`，纯固定包月默认 `FALSE`，混合包月可开） |
| `price_amount` | `DECIMAL(12,2) NULL` | 周期订阅金额（包月/包季/包年时填） |
| `price_currency` | `CHAR(3) NULL` | 订阅金额币种：`CNY` / `USD`，默认 `CNY` |
| `subscribed_at` | `DATE NULL` | 订阅日期（或本周期起始参考日） |
| `renew_at` | `DATE NULL` | 下次续费日 / 充值包到期日（正交可选，按量包若带有效期也可填） |
| `renew_confirmed_at` | `DATETIME NULL` | 最近一次人工确认续费的北京时间 |
| `console_url` | `VARCHAR(512) NULL` | 控制台地址，仅 `https://` |
| `docs_url` | `VARCHAR(512) NULL` | API 文档地址，仅 `https://` |
| `logo_storage_key` | `VARCHAR(255) NULL` | 对象存储键（走 `app/core/storage/`，空则展示首字字标） |
| `latest_checkpoint_id` | `BIGINT NULL FK → ark_ai_balance_checkpoints.id` | 指向最近一次余额核对/充值流水（无外键循环问题：先插流水再更新指针） |
| `low_balance_threshold` | `DECIMAL(14,4) NULL` | 余额预警线（按最新流水同币种比较） |
| `created_at / updated_at` | `DATETIME NOT NULL` | 创建/更新时间（`beijing_now`） |
| `created_by / updated_by` | `INT UNSIGNED NULL` | 创建/更新人 ID（`ark_users.id`） |

> 不存 API Key；Key 仍在 `ark_ai_providers.api_key`（加密）。

### 3.2 新增表 `ark_ai_balance_checkpoints`（余额核对与充值流水）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | `BIGINT PK AUTO_INCREMENT` | 主键 |
| `provider_id` | `INT NOT NULL FK → ark_ai_providers.id` | 关联提供商 |
| `checkpoint_kind` | `ENUM('reconcile','topup') NOT NULL DEFAULT 'reconcile'` | 类型：余额核对 / 充值入账 |
| `balance_amount` | `DECIMAL(14,4) NOT NULL` | 本次登记的账户余额（作为此后估算与进度条的 100% 基准） |
| `balance_currency` | `CHAR(3) NOT NULL` | 币种：`CNY` / `USD` |
| `recorded_at` | `DATETIME NOT NULL` | 余额生效截点（北京时间，**精确到秒，默认提交时刻 `beijing_now()`**；避免日期截断导致当日重复扣减） |
| `estimated_before_amount` | `DECIMAL(14,4) NULL` | 登记瞬间系统按上一条流水估算出的余额快照（用于核对漂移误差，首次登记为 NULL） |
| `remark` | `VARCHAR(256) NULL` | 备注（如充值单号、对账说明） |
| `created_at` | `DATETIME NOT NULL` | 创建时间（`beijing_now`） |
| `created_by` | `INT UNSIGNED NULL` | 登记人 ID（`ark_users.id`） |

索引：`idx_ai_bal_cp_provider_recorded (provider_id, recorded_at DESC, id DESC)`。

### 3.3 新增表 `ark_ai_model_prices`（全平台统一模型单价表）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | `INT PK AUTO_INCREMENT` | 主键 |
| `provider_id` | `INT NOT NULL FK → ark_ai_providers.id` | 关联提供商 |
| `model` | `VARCHAR(128) NOT NULL` | 模型名，与预设 `model` 一致 |
| `pricing_mode` | `ENUM('token','per_call','image_rate_card') NOT NULL DEFAULT 'token'` | 计价方式：按百万 token / 按次固定 / 复用预设生图 `rate_card` |
| `input_per_million` | `DECIMAL(14,6) NULL` | 每百万输入 token 单价（`token` 模式必填，6 位小数对齐 `ai_chat/billing.py`） |
| `output_per_million` | `DECIMAL(14,6) NULL` | 每百万输出 token 单价（`token` 模式必填） |
| `per_call_amount` | `DECIMAL(14,6) NULL` | 单次调用固定费用（`per_call` 模式必填，适用于按张计费生图等） |
| `currency` | `CHAR(3) NOT NULL DEFAULT 'CNY'` | 币种：`CNY` / `USD`（`image_rate_card` 固定 `USD`） |
| `created_at / updated_at` | `DATETIME NOT NULL` | 创建/更新时间（`beijing_now`） |
| `created_by / updated_by` | `INT UNSIGNED NULL` | 创建/更新人 ID（`ark_users.id`） |

唯一键：`uq_ai_model_prices_provider_model (provider_id, model)`。单价调整只影响之后的调用，历史费用由日志快照固化。

### 3.4 改造既有表

**`ark_ai_presets`**：新增 `feature_key VARCHAR(64) NULL comment='所属功能标识'`，建索引 `idx_ai_presets_feature_key`。新建预设 API 层校验必填且属于功能目录；存量允许 NULL，页面标为“未归属”。

**`ark_ai_call_logs`**：新增

| 列 | 类型 | 说明 |
|---|---|---|
| `provider_id` | `INT NULL` | 调用时提供商 ID 快照；预设改绑提供商后历史仍归原提供商 |
| `finished_at` | `DATETIME NULL` | 调用结束时间（北京时间；成功、失败、超时、兜底清理都写）。余额扣减与月度统计以它为界 |
| `cost_status` | `ENUM('priced','unpriced','no_usage','failed','not_billed','legacy','test') NULL` | 费用状态，见下表（存量迁移回填为 `legacy`，新写入均显式赋值） |
| `cost_amount` | `DECIMAL(14,6) NULL` | 仅 `priced` 时有值，币种见 `cost_currency` |
| `cost_currency` | `CHAR(3) NULL` | 费用币种：`CNY` / `USD` |
| `price_snapshot` | `JSON NULL` | 计费时的单价来源、模式、单价及 token/次数明细，供审计 |

| `cost_status` | 含义 | 是否计入金额 | 是否计入“未定价” |
|---|---|---|---|
| `priced` | 已按单价计费 | 是 | 否 |
| `unpriced` | 调用成功且有有效用量，但无匹配单价（或计费自身异常兜底） | 否 | 是 |
| `no_usage` | 调用成功，但供应商未返回可用 token 用量（且非 `per_call`） | 否 | 是（明细单列“无用量”） |
| `failed` | 调用失败、超时、断流、或 Agent 仅剩保守预扣 `reservation` | 否 | 否 |
| `not_billed` | ACCIO WORK 等内部不计费通道 | 否 | 否 |
| `legacy` | 上线前存量日志，不回填金额 | 否 | 否（单列“上线前”） |
| `test` | 测试调用（`caller_module = 'ai_preset_test'` 或测试预设白名单） | 否 | 否（单列测试次数） |

**索引**：
- `idx_ai_call_logs_provider_finished (provider_id, finished_at)`：按提供商汇总与余额扣减；
- `idx_ai_call_logs_cost_status_finished (cost_status, finished_at)`：全平台月度/累计汇总；
- `idx_ai_call_logs_status_provider (status, provider_id)`：快速统计在途 `pending` 调用数。

### 3.5 迁移策略

- 一个 Alembic 迁移（revision ID `NNN_ai_subscription_billing` ≤ 32 字符；建迁移前执行 `git log --all --oneline -- backend/alembic/versions/` 核对全分支最新编号）。
- **功能归属回填写死在迁移内**：迁移文件内置一份静态 `PRESET_FEATURE_SNAPSHOT` 字典回填 `ark_ai_presets.feature_key`，不 import 运行时代码；未命中的保持 `NULL`。
- **存量日志处理**：所有已存在日志一次性更新 `cost_status = 'legacy'`（不猜 `provider_id` 与历史费用）；**同步迁入现有 `parameters.chat.pricing`**：迁移可选择不改 `parameters`，而是在首次启动或管理页提供一键导入，或由后端在回退读取时自动识别，避免破坏性改写 JSON。
- **MySQL 幂等与安全**：只新增表与可空列，不删列不改既有枚举；迁移只随部署入口执行，开发机只在隔离库验证升/降级。

---

## 4. 后端设计

### 4.1 功能目录与启动种子对齐

- **`backend/app/ai/feature_catalog.py`** 作为 `feature_key` 的唯一后端定义源，每项包含：`key`、`label`、`nav_group`（对应 `navigation.js` 分组标题或“平台内置”）、`route_path`（可选，有则前端可跳转）、`caller_modules`（映射到该功能的历史 `caller_module` 列表，用于统一替换 `useAiManager.js` 中过时的 `MODULE_LABELS`）。
- 分类除覆盖 `navigation.js` 业务模块外，显式包含内置非导航类：`ai_gateway`（外部站点网关）、`agent_runtime`（Agent 引擎）、`system_test`（系统与内部测试）。
- **同步改造自动种子**：更新 `backend/app/bootstrap/seed_ai.py`（`_auto_create_preset`）、`seed_fx_settlement.py`、`seed_whatsapp_reply.py`，所有自动初始化预设均显式传入 `feature_key`，消除新环境不断产出“未归属”预设的根源。
- `scripts/check_conventions.py` 增补静态提示：目录与 `navigation.js` 标题脱节或代码出现未登记 `preset_name` 时报黄警告（不阻断）。

### 4.2 全链路费用结算（`billing_service.py`）

新增 `backend/app/ai/billing_service.py`，集中负责价格解析、费用计算与日志收尾，提供两个核心函数：

1. `settle_call_log_cost(db, log_id, *, provider_id, provider_type, model, preset_name, caller_module, status, tokens_prompt, tokens_completion, usage_detail, preset_parameters=None, accounting_source=None)`
   - **独立事务/异常隔离**：必须在调用状态已 `commit` 之后单独调用，内部自带 `try/except`，失败只 `db.rollback()` + `logger.warning` + `print(flush=True)`，再尝试把 `cost_status` 降级记为 `unpriced`（`price_snapshot = {"error": ...}`），**绝不向上抛异常、绝不改变业务调用的成功返回**。
   - **结算规则顺序**：
     1. `caller_module == "ai_preset_test"` 或 `preset_name in TEST_PRESET_WHITELIST`（如 `mail_outreach_internal_test`）→ `cost_status = 'test'`。
     2. `provider_type == "accio_work"` → `cost_status = 'not_billed'`。
     3. `status != "success"` → `cost_status = 'failed'`。
     4. `accounting_source == "reservation"`（Agent Runtime 未拿到真实 usage 时的保守预扣）→ `cost_status = 'failed'`（或若 `status == 'success'` 则 `no_usage`），**严禁把预扣字节数当真实 token 算钱**。
     5. 查找有效定价（按优先级，确保 SSOT 并兼容过渡期）：
        - **优先级 1**：查 `ark_ai_model_prices`（`(provider_id, model)`，走索引直查或 ≤ 30s 短 TTL 缓存，确保多进程/独立生图 worker 不脏读）：
          - `pricing_mode == 'per_call'`：直接取 `per_call_amount`，无需 token；
          - `pricing_mode == 'image_rate_card'`：读取 `preset_parameters.get("rate_card")` 调用 `image_job_runtime.estimated_cost_microusd()` 并换算为 `USD`（`/ 1_000_000`）；
          - `pricing_mode == 'token'`：要求 `tokens_prompt is not None` 且 `tokens_completion is not None`（否则 `no_usage`），计算 `(input_per_million * tokens_prompt + output_per_million * tokens_completion) / 1_000_000`，保留 6 位小数。
        - **优先级 2（兼容过渡期）**：若单价表未配置，回退检查 `preset_parameters.get("rate_card")`（复用生图费率卡）或 `preset_parameters.get("chat", {}).get("pricing")`（复用 `ai_chat/billing.py`），并将 `"source": "fallback_rate_card" / "fallback_chat_pricing"` 记入 `price_snapshot`。
        - 均无匹配 → `cost_status = 'unpriced'`。
2. `mark_log_terminal_failed(db, log_id_or_query, *, finished_at=None)`：供外部兜底清理统一补写 `finished_at = beijing_now()` 与 `cost_status = 'failed'`。

**全链路覆盖清单（共 5 条主链 + 3 条兜底链，缺一不可）**：

| # | 位置 | 插入 pending 时补写 | 终态收尾接入 | 特殊约束 |
|---|---|---|---|---|
| 1 | `call_service.py` (`chat`) | `provider_id=provider.id` | 成功 commit 后调用 `settle_call_log_cost`；错误/异常分支写 `finished_at` + `cost_status='failed'` | 同时将原始 `usage` 落入 `log.usage_detail`；计费必须在业务 `try` 之外 |
| 2 | `call_service.py` (`delegate`) | `provider_id=provider.id`, `cost_status='not_billed'` | 任务终态写 `finished_at` | 不计费 |
| 3 | `stream_service.py` (`chat_stream` / `_finalize_log`) | `provider_id=provider.id` | `_finalize_log` 写 `finished_at`，commit 后调 `settle_call_log_cost` | `GeneratorExit` / `stream_incomplete` 等错误路径一律 `failed` |
| 4 | `image_service.py` (`generate_image` / `edit_image`) | `provider_id=provider.id` | 成功 commit 后**在业务 try 之外**调用 `settle_call_log_cost`（传 `preset.parameters` 供 `rate_card`）；失败分支写 `finished_at` + `cost_status='failed'` | 严禁计费异常触发外层 `except` 把成功生图改标 `error` |
| 5 | `agent_service.py` (`prepare_agent_chat`) | `provider_id=provider.id` | `finally` 写 `finished_at`，commit 后调用 `settle_call_log_cost(..., accounting_source=accounting_source)`；`_reserve_budget` 清理超时 stale 时写 `finished_at` + `cost_status='failed'` | 仅 `accounting_source == 'provider_usage'` 且 `status == 'success'` 才可 `priced`，保留原预算预扣语义不变 |
| 6 | `ai_chat/generation_service.py:41` | — | 租约过期清理 pending 时同步写 `finished_at=now` + `cost_status='failed'` | 避免残留无 `finished_at` 的异常行 |
| 7 | `customer_image/worker.py:311` | — | 兜底失败时同步写 `finished_at=beijing_now()` + `cost_status='failed'` | 同上 |
| 8 | `design_image/worker.py:468` | — | 兜底失败时同步写 `finished_at=beijing_now()` + `cost_status='failed'` | 同上 |

**关于 `chat.pricing` 的收编**：
- 一期在「预设编辑 → AI 工作台」里保留已有 `chat.pricing` 展示并加提示“建议统一在「订阅管理 → 模型单价」维护；当单价表已配置时以单价表为准”。
- 二期将「聊天运行」Tab 的 `management_service.usage_report` 改读 `ark_ai_call_logs.cost_amount/cost_currency`，彻底消除双口径。

### 4.3 多维度状态计算（`subscription_service.py`）

输入：今天（`beijing_today()`）、provider、billing、最新 checkpoint、估算余额、在途数。

先**独立判定两个告警维度**（不互相遮蔽）：
- **续费维度 `renew_flag`**（只要 `is_enabled=True` 且 `renew_at` 非空即参与）：
  - `renew_at < today` 且 `renew_confirmed_at` 未覆盖该周期 → `renew_pending`（待确认续费，warning）
  - `0 ≤ (renew_at − today).days ≤ 7` → `renew_soon`（即将到期，warning）
  - 其他 → `null`
- **余额维度 `balance_flag`**（只要 `is_enabled=True` 且 `latest_checkpoint` 非空且估算余额可用）：
  - `balance_now ≤ 0` → `balance_empty`（余额不足，danger）
  - `low_balance_threshold is not None and balance_now < low_balance_threshold` → `balance_low`（余额偏低，warning）
  - 其他 → `null`

再合成展示字段：
- **卡片主状态 `status`**（单值，按优先级取最紧急的一个）：
  `disabled` (`!is_enabled`) > `renew_pending` > `balance_empty` > `balance_low` > `renew_soon` > `healthy`。
- **次要副标签 `secondary_flags[]`**：未选为主状态但非空的其他维度告警（如主状态 `renew_pending`，副标签 `['balance_empty']`），卡片上同时渲染，不丢失双重告警。
- **周期进度计算**（统一为“本周期已过进度”，消除 0%→100% 跳变）：
  - 周期总天数 `cycle_days`：优先取 `(renew_at - cycle_start).days`（若 `subscribed_at` 存在则按周期推算本期起点），兜底按 `billing_mode` 取 30 / 90 / 365。
  - 剩余天数 `days_left = (renew_at - today).days`。
  - `elapsed_pct`：`days_left < 0` 时为 `100`；否则 `clamp(round((cycle_days - days_left) / cycle_days * 100), 0, 100)`。
- **确认续费动作**：管理员点「已续费」调用 `POST /providers/{id}/renew-confirm`，按 `billing_mode`（月/季/年，月末日期安全对齐）顺延 `renew_at` 一期并写 `renew_confirmed_at = beijing_now()`。

### 4.4 余额估算与漂移对账

只要提供商存在最新余额流水 `cp`（`ark_ai_balance_checkpoints`）即展示余额段：

- 若 `is_balance_deducted_by_usage = False`（纯固定包月不按调用扣减）：
  - `balance_now = cp.balance_amount`，`balance_pct = 100`，标注“不随调用自动扣减”。
- 若 `is_balance_deducted_by_usage = True`（默认按量或混合额度池）：
  ```sql
  SELECT cost_currency, COALESCE(SUM(cost_amount), 0)
  FROM ark_ai_call_logs
  WHERE provider_id = :p
    AND cost_status = 'priced'
    AND finished_at > :cp_recorded_at
  GROUP BY cost_currency
  ```
  - **异币种不静默丢弃**：若结果中存在 `cost_currency != cp.balance_currency` 且金额 > 0，余额状态标为 `currency_mismatch`，界面提示“存在其他币种消费，余额估算不可用”，不输出失真数字。
  - 否则 `balance_now = cp.balance_amount - same_currency_spent`。
  - **进度条分母**：以 `cp.balance_amount` 为 100% 基准：`remaining_pct = clamp(round(balance_now / cp.balance_amount * 100), 0, 100)`（`cp.balance_amount <= 0` 时为 `0`），同时返回 `threshold_pct` 供前端在轨道上标注预警线位置。
- **截点精确到秒**：`POST /balance-checkpoints` 默认 `recorded_at = beijing_now()`；若人工补登过去时间，前端时间选择器精确到分（后端补 `:00`）。
- **漂移快照**：写入新流水前，先算此刻系统原估算值存入 `estimated_before_amount`，前端流水记录中可直观看到每次核对的估算偏差（`balance_amount - estimated_before_amount`）。
- **在途调用**：`WHERE provider_id = :p AND status = 'pending'` 单独计数返回 `inflight_count`，卡片标注“含 N 次在途调用未计入”。
- **核对提醒**：`(beijing_today() - cp.recorded_at.date()).days > 14` 时显示“登记已超 N 天，建议核对”，不改主状态色。

### 4.5 全平台汇总口径（全走 SQL 聚合，保证总账守恒）

- **本月调用消费 `month_spend[]`**：对整张 `ark_ai_call_logs` 执行 SQL `GROUP BY cost_currency`，条件 `cost_status = 'priced' AND finished_at >= 本月 1 日 00:00（北京）`。**不过滤 `ark_ai_providers.is_enabled` 或 `deleted_at`**，保证停用或删除提供商后全平台月账不凭空缩水。
- **上线后累计消费 `total_spend[]`**：同样不按提供商软删过滤，条件 `cost_status = 'priced'`（天然排除 `legacy / test / failed / not_billed`）。
- **未定价与测试计数**：SQL `GROUP BY cost_status` 统计 `unpriced`、`no_usage`（合计为未定价提示）及 `test`（单列，不入消费）。
- **在用固定周期订阅合计 `fixed_subscriptions_monthly[]`**：对所有 `is_enabled = True AND deleted_at IS NULL` 且 `billing_mode IN ('monthly','quarterly','yearly')` 且 `price_amount IS NOT NULL` 的提供商，按 `price_currency` 分组汇总**折合月费**（月付 `/1`、季付 `/3`、年付 `/12`）与**在用固定套餐数**，与调用消费并列展示、**绝不相加混算**。
- **顶部计数（独立维度，不遮蔽）**：
  - `active_count`：`is_enabled = True AND renew_flag != 'renew_pending'`；
  - `renew_alert_count`：`is_enabled = True AND renew_flag IN ('renew_pending', 'renew_soon')`；
  - `balance_alert_count`：`is_enabled = True AND balance_flag IN ('balance_empty', 'balance_low')`。
- **顺带优化 `log_service.py`**：将现有 `log_service.py:56-76` 的 `.all()` 内存求和重构为 SQL `SUM / COUNT / AVG`，避免日志增长后拖慢管理页。

### 4.6 LOGO 存储与安全

- `PUT /api/ai/providers/{id}/logo`：
  1. 校验文件大小 ≤ 512KB；
  2. 读取首部字节按 **magic bytes** 校验真实 MIME（仅允许 `image/png`、`image/jpeg`、`image/webp`，**明确拒绝 `image/svg+xml` 与其他一切类型**，防 Stored XSS）；
  3. 走平台统一存储层 `backend/app/core/storage/` 落盘并登记跨节点同步，将 `storage_key` 存入 `ark_ai_provider_billings.logo_storage_key`；
  4. 提供 `GET /api/ai/providers/{id}/logo`（沿用路由层 `ai:admin` 鉴权，设 `Content-Disposition: inline` + `X-Content-Type-Options: nosniff` + 私有缓存头），前端通过带鉴权 blob URL 或同类既有图片端点读取，避免未鉴权公开暴露且多节点不裂图。

### 4.7 接口清单（全部沿用 `router.py:21` 的 `require_permission("ai:admin")`）

费用、余额与流水字段只存在于这些 `ai:admin` 管理接口中，绝不进入业务模块 `chat()` 返回值。

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/ai/subscriptions` | 卡片/表格列表 + 顶部汇总。参数：`status_filter`（`all/renew_alert/balance_alert/disabled`）、`service_kind`、`api_type`、`hide_disabled`、`q`、`sort`。返回 `summary` 与 `items[]`（含 `status`、`secondary_flags`、`renew`、`balance`、`spend`、`models`） |
| `PUT` | `/api/ai/providers/{id}/billing` | 新增/更新订阅与费用元数据（upsert）。校验 `https://`、金额非负、日期合法、`service_kind` |
| `POST` | `/api/ai/providers/{id}/renew-confirm` | 人工确认续费，顺延 `renew_at` 一期并写 `renew_confirmed_at` |
| `GET` | `/api/ai/providers/{id}/balance-checkpoints` | 查询余额核对与充值历史流水（含原估算值与漂移差额） |
| `POST` | `/api/ai/providers/{id}/balance-checkpoints` | 新增一条余额核对/充值流水（默认 `recorded_at = beijing_now()`），同步更新 `latest_checkpoint_id` |
| `PUT / GET` | `/api/ai/providers/{id}/logo` | 上传/读取提供商 LOGO（magic bytes 校验、禁 SVG、走 `core/storage`） |
| `GET / PUT` | `/api/ai/providers/{id}/model-prices` | 查询与批量保存该提供商下的模型单价（含 `pricing_mode`） |
| `GET` | `/api/ai/feature-catalog` | 返回后端 `feature_catalog.py` 功能目录（驱动预设筛选、新建下拉、日志模块筛选） |
| `GET` | `/api/ai/presets` | 增加 `feature_key`（多选）、`provider_id`（多选）、`model`（多选）筛选；返回交集计数与 `unassigned_count` |
| `POST / PUT` | `/api/ai/presets` · `/api/ai/presets/{id}` | 新建必须带合法 `feature_key`；编辑允许调整 `feature_key` |
| `GET` | `/api/ai/logs` | 增加 `provider_id`、`cost_status` 筛选；返回 `provider_id`、`finished_at`、`cost_status`、`cost_amount`、`cost_currency`；汇总改 SQL 聚合 |

接口变化同步更新 `docs/api-reference.md`。

---

## 5. 前端设计（对齐 `DESIGN.md` 与 Liquid Glass 体系）

### 5.1 组件拆分与复用

`AIManager.vue` 已有 546 行，重设计将移除顶部旧 4 卡并把新逻辑拆入 `views/system/ai/`：

```
views/system/
├─ AIManager.vue                  Tab 壳层（沿用 .lg-aurora 极光背景与 .ai-tabs 玻璃壳；Tab 标签带数量角标）
├─ ai/
│  ├─ SubscriptionBoard.vue       OverviewMetricCard 汇总条 + 筛选排序栏 + 卡片/表格切换
│  ├─ SubscriptionCard.vue        单订阅卡片（.lg-card 玻璃质感 + 顶部状态边线 + 正交周期/余额段 + 快捷与更多操作）
│  ├─ SubscriptionDrawer.vue      基于 DetailDrawer：连接配置 / 订阅与周期 / 余额与核对流水 / 模型单价表
│  ├─ BalanceCheckpointModal.vue  快捷登记余额弹层（默认此刻、可选核对/充值、实时预览估算差额）
│  ├─ PresetBoard.vue             三层面包屑筛选 + 分组列表（窄屏自适应 2 行卡式布局，不隐藏模型）
│  ├─ PresetFeatureTrail.vue      “功能 › 预设”面包屑单元（有路由时可跳转）
│  └─ PresetDrawer.vue            基于 DetailDrawer：预设详情、用量（二期）、测试/编辑/复制/启停/删除
└─ composables/
   ├─ useAiManager.js             保留：提供商测试/编辑/删除、预设测试/复制、日志状态（日志模块名改读 feature-catalog）
   ├─ useSubscriptions.js         订阅汇总、筛选、排序、卡片/表格视图切换、续费确认、余额流水
   └─ usePresetFilters.js         三层标签选中态与 URL query 同步
```

- **强制组件与规范复用**：
  - 顶部汇总卡复用 `frontend/src/components/OverviewMetricCard.vue`（需为该组件增补 `danger` tone，成对引用 `--tag-danger-text` 与 `--tag-danger-bg`）；可点击筛选卡使用原生 `<button aria-pressed>`，保持静态不上浮。
  - 抽屉统一使用 `frontend/src/components/DetailDrawer.vue`（已内置 `append-to-body` 避免被 `.lg-aurora` 层叠上下文吞掉）。
  - 网络请求统一从 `api/clients.js` 取 `aiClient`；按钮权限用 `v-permission="'ai:admin'"`；颜色只用 `tokens.css` 变量；动效只用 `--motion-*` / `--ease-*` tokens，不写 `transition: all` 和 `ease-in`。

### 5.2 卡片结构（正交可选段）

```
┌──────────────────────────────────────────────┐  ← 3px 顶部状态边线
│ [LOGO] TeamRouter          [正常] [次要副标]  │
│        中转站 · OpenAI 协议 · 订阅于 2026.11   │
│ 模型  [gpt-image-2] [claude-sonnet] [+1]     │
│ ──────────────────────────────────────────── │  ← 仅填了 renew_at 时显示
│ 下次续费 12-15           剩 18 天（已过 40%） │
│ ▓▓▓▓▓▓░░░░░░░░░  Pro 包月 · ¥299.00 / 月     │
│ ──────────────────────────────────────────── │  ← 仅登记过余额时显示
│ 余额（估算）                        ¥ 318.20 │
│ ▓▓▓▓▓▓▓▓▓│░░░░  较上次登记剩 64% · 预警 ¥50  │  ← 竖线标记预警线位置
│ 11-20 核对（基准 ¥500.00）· 含 1 次在途       │
│ ──────────────────────────────────────────── │
│ 本月调用 ¥86.40         上线后累计 ¥1,204.10 │
│ 含 3 次未定价调用（未计入）                   │
│ [控制台↗] [文档↗]  [登记余额] [编辑] [更多▾] │
└──────────────────────────────────────────────┘
```

- **不适用段直接不渲染**：纯按量无到期日不画续费占位行；纯固定包月未登记余额不画余额占位行；ACCIO WORK 内部通道渲染紧凑的「绑定预设数 + 近 30 天调用量」摘要块，避免卡片半空。
- **操作入口完整**：待确认续费时底部显露品牌金主按钮「已续费」；「更多 ▾」内收起「连通性测试」「查看调用日志」「停用 / 启用」「删除」，保持卡片整洁同时旧能力零回归。
- **响应式**：1280px 下 3 列网格（`minmax(310px, 1fr)`）；390px 下 Tab 栏与顶部汇总条支持横向平滑滚动不折行，卡片单列不溢出。

### 5.3 预设面包屑筛选与窄屏适配

```
功能   [物流跟踪 12] [展会营销 9] [内贸订单 7] [外部站点网关 3] [未归属 2 !]
提供商 [DeepSeek 6] [TeamRouter 4] [ELBNT 3]
模型   [deepseek-chat 4] [gpt-image-2 2] ...
```

- 三层标签均可多选，模型随功能/提供商交集联动并自动剔除失效选中。
- 选中状态写入 URL query（`?tab=presets&feature=logistics&provider=3`），刷新与分享保持。
- **窄屏（≤ 900px）严禁隐藏模型列**：预设行在窄屏下自动转为双行紧凑卡式布局（首行：`功能 › 预设名` + 状态徽章；次行：提供商标签 + 等宽模型徽章 + 近 30 天调用次数），保证手机和平板上也能一眼看清绑定关系。

---

## 6. 视觉、状态色与动效约束

| 状态 | 卡片顶部边线 | 标签样式 | 进度条色 |
|---|---|---|---|
| `healthy` 正常 | `--tag-success-solid` | `--tag-success-bg/text` | `--tag-success-solid` |
| `renew_pending` 待确认续费 / `renew_soon` 即将到期 / `balance_low` 余额偏低 | `--tag-warning-solid` | `--tag-warning-bg/text` | `--tag-warning-solid` |
| `balance_empty` 余额不足 | `--tag-danger-solid` | `--tag-danger-bg/text` | `--tag-danger-solid` |
| `disabled` 已停用 | `--tag-neutral-solid` | `--tag-neutral-bg/text` | 无 |

- 金额使用 DM Sans / Outfit + `tabular-nums`，统一千分位与两位小数格式。
- 品牌金（`--button-primary`）仅用于主操作（新增订阅源、已续费、保存）与选中态强调，不用于状态语义。
- 动效规范：按钮按压 `scale(0.97)`（`--motion-press` 120ms `--ease-out-strong`）；hover 反馈仅在 `@media (hover: hover) and (pointer: fine)` 生效；高频筛选卡和 chip 保持静态；弹层与抽屉遵循 `--motion-base` / `--motion-sheet` 与 `prefers-reduced-motion: reduce`。

---

## 7. 分期与验证计划

### 第一期

- 迁移：新增 `ark_ai_provider_billings`、`ark_ai_balance_checkpoints`、`ark_ai_model_prices`；改造 `ark_ai_presets` 与 `ark_ai_call_logs`；存量预设按快照回填；存量日志标为 `legacy`；同步改造 3 处启动种子文件。
- 后端：全链路 5+3 写入/兜底接入 `billing_service.py`；`subscription_service.py`；`feature_catalog.py`；LOGO 存储接入 `core/storage`；`log_service.py` 切 SQL 聚合；全部新增路由。
- 前端：移除顶部旧 4 卡；落地 `SubscriptionBoard/Card/Drawer`、`BalanceCheckpointModal`、`PresetBoard/FeatureTrail/Drawer`；补齐 `OverviewMetricCard` 的 `danger` tone；同步日志筛选与 `api/ai.js`。

**验证**：
- 后端 `pytest`（隔离库）：
  1. 计费抛错时，同步 `chat`、流式 `chat_stream`、生图 `generate_image/edit_image` 均保持 `success` 且正常返回结果（回归测试）。
  2. 全 5 条写入链（含生图 `rate_card` 与 `per_call`、Agent Runtime `provider_usage` vs `reservation`）与 3 条外部 pending 兜底链均正确写 `provider_id / finished_at / cost_status`。
  3. 7 种 `cost_status` 分类正确；`legacy / test / failed / not_billed` 不进金额统计。
  4. 多维度告警叠加（`renew_pending + balance_empty`）：主副标签正确，顶部“续费提醒”和“余额预警”独立计数不遮蔽。
  5. 余额：默认 `beijing_now()` 截点不重复扣减当日更早调用；异币种显示不可用；在途调用不计入；登记流水保留 `estimated_before_amount` 漂移值；纯包月关闭自动扣减时不扣余额。
  6. 续费：`renew_pending` 人工确认顺延一期（含月末日期如 1/31 → 2/28）；7 天边界与当天到期。
  7. 总账守恒：停用或软删提供商后，全平台本月与上线后累计总消费不变；固定订阅月折算单独返回不混算。
  8. 权限 403、https 校验、LOGO magic bytes 校验与拒绝 SVG。
  9. 北京时间测试：覆盖服务器非东八区 + 北京 00:00 跨日/跨月边界。
- 前端：`npm run build`；现有 `aiManagerResources` / `aiAdminSettings` 单测更新与回归；390px 与 1280px 视觉与交互验收。
- 迁移：隔离库从当前全分支最新 head 执行 `upgrade` + `downgrade` + 再次 `upgrade` 验证。
- 约定检查：`python scripts/check_conventions.py`。

### 第二期

- 预设详情抽屉近 30 天用量与消费统计、从预设跳转业务功能页、从卡片深链跳转日志页；「聊天运行」Tab 统一改读日志费用快照，下线预设表单里的重复 `chat.pricing` 录入。

### 第三期

- 支持余额查询接口的提供商按适配器自动同步余额；按月导出费用 CSV。

---

## 8. 风险与取舍

| 风险 | 影响 | 处理 |
|---|---|---|
| 中转站不提供余额接口 | 余额靠手工登记可能随时间漂移 | 用 `ark_ai_balance_checkpoints` 记录每次核对漂移值；超 14 天提示核对；三期按适配器接入 |
| 单价填错或供应商含缓存/推理折价 | 估算与账单存在偏差 | 明确“估算，以账单为准”；`call_service` 同步留存 `usage_detail` 供后续细化；价格快照固化可审计 |
| 流式中途断开供应商是否已计费未知 | 本地按 `failed` 记可能略低估 | 一期保守记 `failed`，在账单对账时以余额核对流水校准 |
| 多 worker 并发改单价 | 永久内存缓存会脏读 | 取消永久内存缓存，用带唯一索引的 DB 查询或 ≤30s 短 TTL 缓存 |
| 历史 `chat.pricing` 过渡期并存 | 管理员困惑在哪填价 | 明确 `ark_ai_model_prices` 优先，过渡期兼容回退并在旧表单放跳转提示，二期彻底收口 |
| 合并 Tab 与移除顶部旧 4 卡 | 老用户习惯变化 | 首次进入显示一行可关闭提示；Tab 标签带数量角标；表格视图保留原全部列 |

---

## 9. 对抗性审查与方案评估记录

- **v0.1 → v0.2**：独立上下文对抗性审查，修正了计费异常污染成功调用、流式漏覆盖、`cost_status` 拆分、存量 `legacy` 口径、异币种静默丢失、到期永久变红、迁移快照解耦、`ai:admin` 路由权限与测试调用单列（共 8 项）。
- **v0.2 → v0.3**：结合全仓库代码与原型渲染实测深度评估，并依据亮哥对 Q1–Q6 的拍板结论完成以下修订（见 §10）。

---

## 10. 审查与评估修订记录（v0.2 → v0.3）

| # | 发现与决策来源 | 核实依据 | v0.3 处理 |
|---|---|---|---|
| 1 | 漏掉生图、Agent Runtime 及 3 处外部 pending 兜底写入链 | `image_service.py:759,880`、`agent_service.py:325,448`、`ai_chat/generation_service.py:41`、`customer_image/worker.py:311`、`design_image/worker.py:468` | §4.2 补齐全部 5+3 链路清单；生图独立 try 隔离计费；Agent 严禁对 `reservation` 预扣算钱；`call_service` 同步写 `usage_detail` |
| 2 | 平台已有 `chat.pricing` 与生图 `rate_card` 两套定价 | `ai_chat/billing.py`、`AiPresetChatFields.vue:19`、`image_job_runtime.py:171` | §3.3 & §4.2 将 `ark_ai_model_prices` 升级为全平台单一价格源（`DECIMAL(14,6)`，支持 `token / per_call / image_rate_card`），收编 `chat.pricing` 并兼容 `rate_card` |
| 3 | 缺“直连/中转站”存储字段；表名违宪；缺余额流水与时间戳截断重复扣减 | `models.py:21`、`docs/database.md:305-313` | 表名改为复数 `ark_ai_provider_billings` 补审计列与 `service_kind`；新增 `ark_ai_balance_checkpoints` 流水表记录漂移快照，默认截点 `beijing_now()` 精确到秒 |
| 4 | 主状态优先级遮蔽顶部汇总告警计数 | 原型 `Anthropic 官方` 过期+零余额未计入“余额预警” | §4.3 & §4.5 改为续费与余额两维度独立判定计数，卡片展示主标签+副标签 |
| 5 | 包月与余额互斥过死；固定订阅支出未体现 | Q5 拍板 | §3.1 & §4.5 续费/到期与余额改为正交可选（`is_balance_deducted_by_usage` 控制扣减）；顶部汇总并列展示「调用估算消费」与「在用固定订阅月折算」 |
| 6 | 软删提供商导致总消费丢失 | Q6 拍板 | §4.5 明确全平台月度/累计消费按日志表聚合，不因提供商停用/软删而扣除 |
| 7 | `seed_ai.py` 等启动种子与非导航预设未覆盖 | `seed_ai.py:221`、`seed_fx_settlement.py`、`seed_whatsapp_reply.py` | §4.1 同步改造 3 处种子写入 `feature_key`；目录补齐外部站点网关/Agent/系统测试分类，并统一日志模块筛选 |
| 8 | 顶部旧 4 卡冲突、LOGO 跨节点与 XSS 风险、多 worker 缓存脏读、`log_service` 内存聚合 | `AIManager.vue:10`、`core/storage/`、`log_service.py:56` | §2 移除旧 4 卡并对齐 Liquid Glass / `OverviewMetricCard` / `DetailDrawer`；§4.6 LOGO 走 `core/storage` + magic bytes 禁 SVG；§4.2 取消永久内存缓存；§4.5 `log_service` 切 SQL 聚合 |
| 9 | 原型进度条语义反转、窄屏排版错位、交互未闭环 | 1280px / 390px 渲染实测 | 续费条统一为“周期已过进度”；余额条分母改为上次登记基准值并标预警线；同步升级 `prototype/index.html` 至 v0.3 |
