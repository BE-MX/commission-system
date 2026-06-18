# ACCIO WORK → 莱莎方舟 客户机会台 集成规范

> **版本**: v1.2  
> **最后更新**: 2026-06-16  
> **目标读者**: ACCIO WORK 开发团队  
> **本文档足以独立实施，无需阅读方舟源码**

---

## 1. 接口概览

| 项目 | 值 |
|------|-----|
| 端点 | `POST /api/insight/customer-opportunities/import/accio` |
| 协议 | HTTPS（生产）/ HTTP（本地开发） |
| 认证 | Header `X-Import-API-Key: <密钥>` |
| Content-Type | `application/json; charset=utf-8` |
| 请求体大小限制 | 建议单批 ≤50 条（无硬限制，但超 100 条响应时间明显增长） |
| 幂等性 | **是** — 相同 `source_key` 多次推送不会产生重复记录 |
| 超时建议 | 30 秒（含背调 HTML 大 payload 时） |

---

## 2. 认证

```
X-Import-API-Key: <与方舟管理员约定的密钥>
```

方舟侧通过环境变量 `INSIGHT_IMPORT_API_KEY` 配置。密钥不匹配返回 `HTTP 401`。

---

## 3. 请求 JSON Schema

```jsonc
{
  "schema_version": "1.2",           // 必填，固定 "1.2"
  "batch_id": "accio_20260616_0830", // 必填，全局唯一批次 ID（推荐格式：accio_{YYYYMMDD}_{HHmm}_{seq}）
  "generated_at": "2026-06-16 08:30:00",  // 本批次生成时间，格式 YYYY-MM-DD HH:MM:SS
  "time_range": {                    // 本次抓取的时间窗口（用于审计/追溯）
    "start": "2026-06-15 08:30:00",
    "end": "2026-06-16 08:30:00"
  },
  "filters": {                       // 可选，影响紧急度判定
    "overdue_minutes": null           // 若非空，所有本批条目 urgency 自动升为 "urgent"
  },
  "items": [                         // 机会条目数组，核心
    { /* 见下方 Item Schema */ }
  ]
}
```

### 3.1 Item Schema（每条机会）

```jsonc
{
  // ═══ 幂等键（最重要） ═══
  "source_key": "ali_inquiry_{self_ali_id}_{buyer_company_id}",
  // 全局唯一，相同 source_key 的后续推送会 UPDATE 而非 INSERT
  // 构造规则见第 4 节

  // ═══ 会话信息 ═══
  "conversation": {
    "self_ali_id": "cn1234567890",       // 必填，我方阿里国际站子账号 ID
    "subaccount_name": "leshine_alice",  // 我方子账号显示名
    "buyer_name": "John Smith",          // 买家名称
    "buyer_country": "US",               // 买家国家/地区（ISO 2 字母或中文均可）
    "buyer_level": "A2",                 // 阿里平台买家星级（原样传即可）
    "latest_content": "Hi, I need 500pcs of 18inch body wave...",  // 最新一条消息摘要（≤2000字符）
    "latest_send_time": "2026-06-16 07:45:00",  // 最新消息时间
    "chat_link": "https://message.alibaba.com/...",  // 阿里聊天链接（可为空）
    "conversation_id": "conv_abc123"     // 阿里会话唯一 ID（用于后续关联）
  },

  // ═══ 背调信息（可选） ═══
  "background_check": {
    "research_status": "completed",  // "completed" | "partial" | "missing"
    // "missing" 时方舟跳过背调写入（不覆盖已有背调）
    
    "lead_grade": "A",               // 背调评级 A/B/C/D，直接决定方舟优先级
    "confidence_score": 85,          // 置信度 0-100
    "next_action": "推荐发送样品方案报价",  // 建议下一步（展示给业务员）
    "key_evidence": [                // 关键证据（JSON array of strings）
      "该公司年营业额 $5M+",
      "LinkedIn 有明确假发采购需求",
      "近30天活跃询盘"
    ],
    "opening_message": "Hi John, thank you for your interest in our body wave products...",  // 开场话术（英文）
    "follow_up_message": "Just following up on my previous message...",  // 跟进话术（英文）
    "full_report_html": "<div class='report'>...</div>"  // 完整背调报告 HTML（可为空，最大 64KB）
  },

  // ═══ 机会种子（背调缺失时的兜底字段） ═══
  "opportunity_seed": {
    "title": "John Smith 值得跟进",      // 机会标题（背调有时由 AI 生成更好的标题）
    "priority_level": "C",               // 兜底优先级（仅在 background_check.lead_grade 为空时生效）
    "confidence_score": 50,              // 兜底置信度
    "recommended_strategy": "常规跟进",  // 兜底策略
    "key_signals": ["买家主动发起询盘"],  // 兜底信号
    "opening_message": "",               // 兜底话术
    "follow_up_message": ""              // 兜底话术
  }
}
```

---

## 4. source_key 构造规则（核心幂等逻辑）

```
source_key = "ali_inquiry_{self_ali_id}_{buyer_identifier}"
```

**要求**：
- `self_ali_id`：我方子账号 ID（与 `conversation.self_ali_id` 一致）
- `buyer_identifier`：买家唯一标识（推荐用阿里平台的 buyer company ID 或 member ID）
- 同一个买家跟同一个业务员的所有会话，归为**同一条机会**（同一个 source_key）
- 如果同一买家跟不同子账号沟通，产生不同的 source_key → 不同的机会卡

**幂等行为**：
| source_key 已存在？ | 方舟行为 |
|---|---|
| 不存在 | 新建机会卡（status=pending） |
| 已存在 | 更新字段（不覆盖 status/due_at 当 status≠pending） |

---

## 5. 抓取策略实现

### 5.1 增量模式（日常运行，每 24 小时）

**目标**：只推送过去 24 小时内有新消息的客户。

**ACCIO 侧实现要点**：

1. 维护一个本地游标 `last_scan_time`（上次成功推送的 `time_range.end`）
2. 每次运行时，从阿里国际站抓取 `last_message_time > last_scan_time` 的会话列表
3. 对每个命中会话，抓取最新一条消息内容作为 `latest_content`
4. 推送成功后（HTTP 200/207），更新 `last_scan_time = time_range.end`
5. 推送失败或超时时，**不更新游标**，下次会重推（方舟幂等，不会重复）

```python
# ACCIO 侧伪代码
last_scan_time = load_cursor()  # 从本地存储读
now = datetime.utcnow()

conversations = alibaba_api.list_conversations(
    since=last_scan_time,
    has_new_message=True
)

items = []
for conv in conversations:
    source_key = f"ali_inquiry_{conv.self_ali_id}_{conv.buyer_member_id}"
    item = build_item(conv, source_key)  # 见第 5.3 节
    items.append(item)

response = push_to_ark(items, time_range={"start": last_scan_time, "end": now})

if response.status_code == 200:
    save_cursor(now)
```

### 5.2 全量模式（首次运行 / 手动触发）

**目标**：抓取所有历史询盘，建立完整机会库。

**与增量模式的区别**：

| 维度 | 增量模式 | 全量模式 |
|------|---------|---------|
| 时间范围 | `last_scan_time → now` | 全量（或近 N 天） |
| 分批 | 通常 1 批够 | 按 50 条/批分页推送 |
| batch_id | `accio_{date}_{time}` | `accio_full_{date}_{seq}` |
| 背调 | 新客户做，已做过的跳过 | 同左 |
| 游标 | 推完更新 | 推完更新为最后一条的时间 |

**全量分批推送**：
```python
all_conversations = alibaba_api.list_all_conversations(days=90)  # 近 90 天

for batch_index, chunk in enumerate(chunked(all_conversations, 50)):
    batch_id = f"accio_full_20260616_{batch_index:03d}"
    items = [build_item(conv) for conv in chunk]
    push_to_ark(items, batch_id=batch_id)
    time.sleep(2)  # 避免方舟过载
```

### 5.3 背调去重策略

**核心规则**：ACCIO 侧决定是否做背调，方舟侧只消费结果。

```python
def should_run_background_check(conv, ark_existing_data=None):
    """
    ACCIO 侧判断是否需要执行背调
    """
    source_key = f"ali_inquiry_{conv.self_ali_id}_{conv.buyer_member_id}"
    
    # 方案 A（推荐）：ACCIO 自己维护已背调名单
    if source_key in local_checked_set:
        return False  # 已做过，不再重复
    
    # 方案 B：看本地缓存的上次推送响应
    # 如果上次推送时该 source_key 已有 background_check_json，跳过
    
    return True

def build_item(conv, source_key):
    item = {
        "source_key": source_key,
        "conversation": { ... },
        "opportunity_seed": { ... },  # 始终填写（兜底用）
    }
    
    if should_run_background_check(conv):
        bg_result = run_background_check(conv.buyer_name, conv.buyer_country)
        item["background_check"] = {
            "research_status": "completed",  # 或 "partial"
            "lead_grade": bg_result.grade,
            "confidence_score": bg_result.score,
            "next_action": bg_result.next_action,
            "key_evidence": bg_result.evidence,
            "opening_message": bg_result.opening_msg,
            "follow_up_message": bg_result.follow_up_msg,
            "full_report_html": bg_result.html_report,
        }
        # 记录到本地已背调名单
        local_checked_set.add(source_key)
    else:
        # 跳过背调 — 传 research_status="missing" 告知方舟不覆盖已有背调
        item["background_check"] = {"research_status": "missing"}
    
    return item
```

**方舟侧行为**：
- `research_status == "missing"` → 方舟不写入 `background_check_json`（保留原有背调数据）
- `research_status == "completed"/"partial"` → 覆盖写入

**什么时候需要重新背调**：
- 用户在方舟后台手动触发（未来功能，不影响当前接口）
- ACCIO 侧如果检测到买家信息发生重大变更（如公司名变更），可清除本地已背调标记，下次推送时重新做

### 5.4 已有客户的新增询盘记录匹配

当同一个 `source_key` 再次推送时：

1. `conversation.latest_content` 会被更新为最新消息 → 方舟覆盖 `summary` 字段
2. `conversation.latest_send_time` 被更新 → 方舟覆盖 `latest_message_at`
3. 如果状态仍为 `pending`，`due_at` 会按新优先级重新计算
4. 如果状态已变（业务员已处理），`due_at` 和 `status` 不被覆盖

**ACCIO 不需要传历史消息列表** — 只传最新一条消息的摘要即可。方舟的机会卡是"行动提示"而非"聊天记录存档"。

### 5.5 大内容处理（背调报告 HTML）

| 字段 | 建议大小 | 超限处理 |
|------|---------|---------|
| `latest_content` | ≤2000 字符 | 截断，尾部加 `...` |
| `full_report_html` | ≤64KB | 超限时压缩图片/移除内联样式 |
| `key_evidence` 数组 | ≤10 条，每条 ≤200 字符 | 截取最重要的 |
| `opening_message` | ≤2000 字符 | 正常英文话术不会超 |

**不需要存成 MD 文件** — 方舟数据库字段能容纳这些大小，直接 JSON 内联传输即可。

---

## 6. 归属解析机制

方舟通过 `conversation.self_ali_id` 自动匹配归属业务员：

```
conversation.self_ali_id  →  ark_user_external_bindings 表
  (provider="alibaba_icbu", external_account_id=self_ali_id)  →  ark_user_id  →  机会归属
```

**ACCIO 侧要做的**：确保 `self_ali_id` 准确反映实际接待该询盘的子账号 ID。

**如果归属匹配不上**（方舟侧未配置该子账号绑定）：
- 方舟会在响应中返回 `unassigned_external_accounts` 列表
- 机会卡 `owner_resolve_status = "unassigned"`
- 管理员在方舟后台手动绑定后，后续推送自动匹配

---

## 7. 优先级与 SLA 规则

方舟根据 `background_check.lead_grade` 决定优先级和截止时间：

| lead_grade | priority_level | due_at 计算 | 业务含义 |
|---|---|---|---|
| A | A | 当前时间 + 2 小时 | 高价值，必须立即响应 |
| B | B | 今天 18:00（如已过 18 点则明天 18:00） | 当天必须处理 |
| C | C | 明天 18:00 | 次日处理 |
| D | D | 无 due_at | 低优先级，自行安排 |
| 空 | 取 `opportunity_seed.priority_level`（默认 C） | 同上 | 未背调的兜底 |

**ACCIO 侧建议**：
- 背调完成时务必输出 `lead_grade`
- 如果背调引擎无法判断等级，传 `"C"` 作为安全默认值
- 不要传空的 `lead_grade` 除非确实没做背调

---

## 8. 响应格式

### 成功（HTTP 200）

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "batch_id": 42,
    "batch_source_id": "accio_20260616_0830",
    "item_count": 15,
    "created_count": 10,
    "updated_count": 4,
    "unassigned_count": 1,
    "failed_count": 0,
    "status": "success",
    "unassigned_external_accounts": [
      {
        "provider": "alibaba_icbu",
        "external_account_id": "cn9999999",
        "external_display_name": "new_account"
      }
    ]
  }
}
```

### 认证失败（HTTP 401）

```json
{"code": 401, "message": "Invalid API key", "data": null}
```

### 请求格式错误（HTTP 422）

```json
{"code": 422, "message": "Validation error: ...", "data": null}
```

---

## 9. 错误处理与重试

| 场景 | HTTP 状态 | ACCIO 应对 |
|------|-----------|-----------|
| 认证失败 | 401 | 检查 API Key 配置，不重试 |
| 格式错误 | 422 | 检查 JSON 结构，修复后重推 |
| 服务器错误 | 500 | 等 30s 后重试，最多 3 次 |
| 超时 | - | 等 60s 后重试，最多 2 次（方舟幂等，不怕重复） |
| 部分失败 | 200 + `status=partial_failed` | 记录 `failed_count`，下次增量推送会自动补（同 source_key 重推） |
| 全部失败 | 200 + `status=failed` | 检查 items 是否缺少 source_key |

**关键**：由于方舟端幂等（source_key 去重），重试是安全的。宁可多推一次，不要漏推。

---

## 10. ACCIO 侧状态管理清单

ACCIO 需要持久化以下状态（本地数据库或文件）：

| 状态项 | 用途 | 存储建议 |
|--------|------|---------|
| `last_scan_time` | 增量游标，决定下次扫描起点 | SQLite / JSON 文件 |
| `checked_source_keys` | 已做过背调的 source_key 集合 | SQLite 表 / Set 文件 |
| `batch_sequence` | 当日批次序号（保证 batch_id 唯一） | 内存计数器 + 日期前缀 |
| `push_failures` | 推送失败的 items（待重试） | 队列 / JSON 文件 |

---

## 11. 推送时序（推荐架构）

```
┌─────────────────────────────────────────────────────────────────┐
│  ACCIO WORK 定时任务（每 24h，建议 UTC 00:30 / 北京时间 08:30）  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
            ┌──────────────────▼─────────────────────┐
            │ 1. 读取 last_scan_time                  │
            │ 2. 调阿里 API: 获取有新消息的会话列表    │
            │ 3. 对每个会话:                           │
            │    a. 构造 source_key                    │
            │    b. 判断是否需要背调                    │
            │    c. 需要 → 执行背调 → 填充 bg 字段     │
            │    d. 不需要 → bg.research_status="missing" │
            │    e. 填充 conversation + seed 字段      │
            │ 4. 分批 (≤50条/批) 推送到方舟             │
            │ 5. 处理响应:                             │
            │    a. 记录 unassigned_accounts（通知管理员）│
            │    b. 更新 last_scan_time                 │
            └────────────────────────────────────────┘
```

---

## 12. 完整推送示例

```json
{
  "schema_version": "1.2",
  "batch_id": "accio_20260616_0830_001",
  "generated_at": "2026-06-16 08:30:00",
  "time_range": {
    "start": "2026-06-15 08:30:00",
    "end": "2026-06-16 08:30:00"
  },
  "filters": {},
  "items": [
    {
      "source_key": "ali_inquiry_cn1234567890_buyer_us_smith_trading",
      "conversation": {
        "self_ali_id": "cn1234567890",
        "subaccount_name": "leshine_alice",
        "buyer_name": "Smith Trading Co.",
        "buyer_country": "US",
        "buyer_level": "A3",
        "latest_content": "Hi, we are interested in 18inch body wave bundles, can you provide pricing for 500pcs?",
        "latest_send_time": "2026-06-16 07:45:00",
        "chat_link": "https://message.alibaba.com/message/default.htm?spm=a2700#/conversation/cn1234567890",
        "conversation_id": "conv_20260615_smith"
      },
      "background_check": {
        "research_status": "completed",
        "lead_grade": "A",
        "confidence_score": 88,
        "next_action": "高价值客户，建议24h内报价并附样品方案",
        "key_evidence": [
          "Smith Trading 年营收 $8M，主营美容分销",
          "LinkedIn 显示正在拓展假发品类",
          "30天内在平台活跃询盘4次",
          "美国市场，符合莱莎核心区域"
        ],
        "opening_message": "Hi there! Thank you for reaching out about our body wave bundles. We'd be happy to provide bulk pricing for 500pcs. Could you share your preferred hair grade and delivery timeline so I can put together the best offer for you?",
        "follow_up_message": "Hi again! Just following up on the body wave bundle inquiry. We have a special promotion running this month for orders over 300pcs. Would you like me to send over the details?",
        "full_report_html": "<div class='bg-report'><h2>Smith Trading Co. - 背景调查报告</h2><p>...</p></div>"
      },
      "opportunity_seed": {
        "title": "Smith Trading 大单询盘",
        "priority_level": "A",
        "confidence_score": 88,
        "recommended_strategy": "24h内报价",
        "key_signals": ["500pcs大单询盘", "美国分销商"],
        "opening_message": "",
        "follow_up_message": ""
      }
    },
    {
      "source_key": "ali_inquiry_cn1234567890_buyer_ng_hair_lagos",
      "conversation": {
        "self_ali_id": "cn1234567890",
        "subaccount_name": "leshine_alice",
        "buyer_name": "Lagos Hair Supply",
        "buyer_country": "NG",
        "buyer_level": "0",
        "latest_content": "hello, I want to buy hair",
        "latest_send_time": "2026-06-16 03:20:00",
        "chat_link": "",
        "conversation_id": "conv_20260616_lagos"
      },
      "background_check": {
        "research_status": "missing"
      },
      "opportunity_seed": {
        "title": "Lagos Hair Supply 值得跟进",
        "priority_level": "C",
        "confidence_score": 30,
        "recommended_strategy": "常规跟进，了解需求规格",
        "key_signals": ["买家主动发起"],
        "opening_message": "",
        "follow_up_message": ""
      }
    }
  ]
}
```

---

## 13. 校验清单（ACCIO 开发自测）

- [ ] `source_key` 非空且全局唯一（同买家+同子账号 = 同一个 key）
- [ ] `batch_id` 每次推送不重复
- [ ] `self_ali_id` 准确对应实际子账号
- [ ] 增量模式：只推 `latest_send_time > last_scan_time` 的条目
- [ ] 已背调客户：`background_check.research_status = "missing"`（不重做）
- [ ] 未背调新客户：做完背调后 `research_status = "completed"`
- [ ] `full_report_html` 不超 64KB
- [ ] 推送失败时不更新游标，下次自动补推
- [ ] 响应中 `unassigned_external_accounts` 非空时，通知管理员配置绑定
- [ ] 全量模式分批推送，每批 ≤50 条，批间间隔 ≥2 秒

---

## 14. 联调环境

| 环境 | 地址 | API Key |
|------|------|---------|
| 开发 | `http://192.168.x.x:8001/api/insight/customer-opportunities/import/accio` | 与后端开发约定 |
| 生产 | `https://leshine.work/api/insight/customer-opportunities/import/accio` | 与管理员约定 |

联调时可用小批量（1-3 条）推送验证，观察方舟后台"客户机会台"页面是否正确显示机会卡。
