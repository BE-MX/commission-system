# WhatsApp 回复助手优化方案（话术生成 + 自动接管）

日期：2026-09-11
范围：`backend/app/whatsapp_translation/`、`extensions/whatsapp-translation/`
前置：同日的机制复盘（知识库召回、auto 记忆、多段式人性化、安全边界）

## 复盘结论回顾

- 安全/隐私工程（hash 绑定、ACL 复查、证据校验、fail-closed 转人工）质量高，取向是"宁可不答不乱答"。
- 主要短板四处：
  1. **知识召回质量低**：纯词法打分；中文查询词因 `[\w-]{2,40}` 正则几乎失效；只保留最后 120 个查询词；hash 绑定随文档编辑静默失效且无监控；catalog 触发词硬编码三类产品。
  2. **auto 模式无记忆**：扩展自动接管不传 `memory_conversation_id`，多轮对话无跨轮事实积累，与 prompt "不反复追问" 指令矛盾。
  3. **拟人化较粗**：段间固定 1500/2500ms 延迟，与段长无关。
  4. **安全边界缺口**：无联系人白名单/排除列表、无时段限制、无客户端频次上限、金额护栏仅在 prompt 层。
- 另有工程债：`REPLY-ASSISTANT.md` 停留在 1.3.0 与 1.6.5 代码脱节；timeout capability 被钳制但未生效；`ReplyPlan/claims` 死 schema；`auto_reply_enabled` 硬编码 `True`。

技术前提（已核实）：后端无 jieba、无向量/embedding 基础设施，`requirements.txt` 有 numpy。语义检索需走轻量路线（LLM 查询改写），不建议本期引入向量库。

## 优先级总览

| 编号 | 事项 | 优先级 | 预计工作量 | 主要改动面 |
|---|---|---|---|---|
| P0-1 | 中文查询词分词修复 | P0 | 0.5d | `reply_service.py` |
| P0-2 | LLM 查询改写增强召回 | P0 | 1.5d | `reply_sources.py`、seed preset |
| P0-3 | 查询词截断策略优化 | P0 | 0.5d | `reply_service.py` |
| P0-4 | 知识绑定失效可观测 | P0 | 0.5d | `reply_sources.py`、knowledge 保存链路 |
| P0-5 | catalog 触发词配置化 | P0 | 0.5d | `reply_catalog.py`、配置文件 |
| P1-1 | auto 模式记忆接入（先读后写） | P1 | 2d | 扩展 autoReply/面板、`reply_service.py` |
| P1-2 | glossary 语言选择修正 | P1 | 0.5d | `reply_service.py` |
| P2-1 | 段间延迟拟人化 | P2 | 0.5d | 扩展 `autoReply.ts` |
| P3-1 | 白名单/排除列表 + 时段限制 | P2 | 1d | 扩展 storage/设置 UI |
| P3-2 | 金额代码级护栏 | P2 | 0.5d | `reply_direct.py` |
| P4-x | 工程债清理（文档/超时/死 schema/配置开关） | P1 | 1d | 多处小改 |

---

## P0：知识召回质量

### P0-1 中文查询词分词修复

- 现状：`reply_service.py:157` 用 `re.findall(r"[\w-]{2,40}")` 提取查询词，无空格中文被切成最长 40 字的整段连续串，在 `reply_sources.py:107-110` 的子串匹配里几乎不可能命中；中文召回实际全靠配置别名。
- 方案（零依赖，推荐）：非 ASCII 文本改取 **char bigram（2-gram）** 与 ASCII 词混合作为查询词集合；匹配侧非 ASCII 已是子串匹配，bigram 子串命中率可接受。同时把单字词（长度 < 2 的 CJK 片段）过滤。
- 备选：引入 jieba（纯 Python，依赖轻），分词质量更好但多一个依赖；先上 bigram，命中率不足再换。
- 验证：`backend/tests/` 新增用例——中文对话提到知识库条目的中文名/别名时能命中对应 section；回归现有词法打分测试。

### P0-2 LLM 查询改写增强召回

- 现状：无语义召回，客户换种说法（别名表未收录的同义词）即漏。
- 方案：检索前增加一次**轻量 LLM 改写调用**，复用现有 preset 体系（`app/ai/call_service.py`），新建 `whatsapp_reply_query_rewrite` preset（建议指向低成本模型）：
  - 输入：最近 N 条客户消息原文；
  - 输出：JSON `{"queries": ["..."], "synonyms": {"term": [...]}}`，中英双语查询词；
  - 结果并入词法打分的查询词集合，不改打分逻辑本身。
- 成本控制：**条件触发**——仅当词法命中段落数 < 2 时才发起改写调用；按消息内容哈希做进程内缓存（复用 `EphemeralReplyCache` 模式）。
- 风险：增加一次 LLM 调用的延迟与成本（条件触发可控）；改写结果需 JSON 解析容错（沿用 `reply_direct._object()` 的解析模式）。
- 验证：mock AI 调用的单测（参考现有 `test_whatsapp_reply_service.py` 写法）；构造同义词场景验证召回提升。

### P0-3 查询词截断策略优化

- 现状：`reply_service.py:158` 只保留最后 120 个查询词，长会话前文提到的产品词被挤出。
- 方案：上限 120 → 300；保留策略从"尾部截断"改为**优先级保留**——知识库 title/alias 直接命中的词 > 最近消息的词 > 高频词。
- 验证：长会话（>120 词）场景测试，确认前文产品词仍能命中。

### P0-4 知识绑定失效可观测

- 现状：`reply_sources.py:86-90` 段落 hash 与绑定不一致即静默返回 `None`，文档任何编辑都让对应段落悄悄消失，只有 mandatory 全失效才置 `knowledge_unavailable`。
- 方案：
  1. 绑定解析失败时记 warning 日志（含 document_id / section_index）；
  2. 响应 `risk_flags` 增加 `knowledge_binding_stale`（含失效段落数）；
  3. 知识库文档保存链路增加校验：保存后重算绑定配置中涉及该文档的段落 hash，失效段落数 > 0 时在管理界面/接口返回中提示（fail-closed 语义不变，只补可观测性）。
- 验证：编辑文档后断言 risk flag 与日志；文档保存接口的失效提示测试。

### P0-5 catalog 触发词配置化

- 现状：`reply_catalog.py:13-17` 硬编码 `weft/发帘/天才` 三类触发词，其他产品线无规格注入。
- 方案：触发词移入 `config/whatsapp-reply-phase12.json`（沿用现有配置文件 + 环境变量覆盖机制，`reply_profile.py:12-33`），按产品线配置 `trigger_terms`；配置签名/校验沿用现有机制。
- 验证：配置新增触发词后对应产品线消息能触发 catalog 注入；配置缺失时行为与现状一致。

## P1：记忆与语言

### P1-1 auto 模式记忆接入（先读后写，分两阶段）

- 现状：`autoReply.ts:49-53` 构造的请求不带 `memory_conversation_id`，后端 `load_for_generation` 直接返回空（`reply_memory.py:63-65`）。
- 阶段 1a（只读，本期做）：
  - 开启自动接管时，若当前聊天已绑定记忆会话则自动带上 `memory_conversation_id`；未绑定时在面板提示可一键创建绑定；
  - 生成侧不改，`saved_observations` 注入即可消除"反复追问"。
  - 写路径保持人工采纳不变——风险零增量。
- 阶段 1b（自动写，需单独评审后做）：auto 模式的 `memory_changes` 由扩展自动 commit。后端证据校验已保证客户端不可篡改（`reply_memory.py:219-235`），主要待决问题是产品语义（无人工采纳即落库是否可接受）与错误记忆的自清洁。
- 验证：扩展 vitest（auto 请求携带 memory id、绑定缺失时的 UI 提示）；后端生成链路注入观察条目的回归测试。

### P1-2 glossary 语言选择修正

- 现状：`target_language="auto"` 时用 `fallback_language` 选词表（`reply_service.py:166`），客户实际语言 ≠ fallback 时注错词表。
- 方案：优先使用扩展端已维护的会话语言偏好（`storage.ts` 的语言偏好 key，按聊天标题哈希存取），请求中显式传 `detected_language`；后端选词表顺序：`detected_language` > `target_language`（非 auto）> fallback。
- 验证：多语言会话场景选对词表的测试。

## P2：人性化与安全边界

### P2-1 段间延迟拟人化

- 现状：`autoReply.ts:76` 固定首段 1500ms、后续 2500ms，与段长无关。
- 方案：
  - 首段前加"阅读延迟"：base 1200ms + 客户最后一条消息长度 × 系数（如 20ms/字符，封顶 4000ms）；
  - 段间延迟模拟打字：base 800ms + 段长 × 40–80ms/字符随机系数（封顶 8000ms），加 ±20% 抖动；
  - 保留现有安全校验：每段发送前校验聊天尾部未变、段间新客户消息到达即丢弃剩余段。
- 验证：扩展 vitest 用 fake timers 断言延迟区间与丢弃逻辑不回归。

### P3-1 白名单/排除列表 + 时段限制

- 现状：任何 direct 聊天都能开自动接管，无时段/频次客户端限制。
- 方案：
  - `LocalState`（`storage.ts:3-12`）增加 `auto_reply_allowlist` / `auto_reply_blocklist`（按聊天标题哈希，与现有语言偏好同思路，不存明文联系人）与 `auto_reply_schedule`（本地时区的允许时段）；
  - 设置面板增加对应 UI；`tick` 前检查名单与时段，不满足则不开/即停；
  - 默认行为与现状一致（无名单=不限制），避免破坏现有用户习惯。
- 验证：扩展 vitest 覆盖名单命中/时段外不触发。

### P3-2 金额代码级护栏

- 现状：价格/付款约束仅在 prompt 层（`reply_direct.py:15,40`），无代码级检测。
- 方案：auto 模式后端对 `reply_text` 做轻量正则检测（货币符号 $/€/¥、数字+USD/RMB 等币种词）：
  - 命中且 `sources`/`product_catalog` 中存在对应价格依据 → 放行；
  - 命中但无依据 → `auto_action` 降为 `handoff` + risk flag `price_unverified`，与现有"歧义即转人工"路径复用（`reply_direct.py:117-127`）。
- 验证：含价格回复的 handoff 降级测试；有目录依据时正常放行测试。

## P4：工程债清理

1. **timeout wiring 修复**：`apiClient.ts:133` 写死 185s 改为使用 capability `timeout_seconds`（钳制逻辑已在 `replyValidation.ts:18`），文档注释同步。
2. **REPLY-ASSISTANT.md 重写**：对齐 1.6.5——185s 超时、滚动加载全量历史、120,000 字符上限、auto 接管完整行为与即停条件清单。
3. **死 schema 二选一**：`ReplyPlan/claims/needs_confirmation`（`reply_schemas.py:71-127`）要么接入生成链路（让 handoff_summary.next_step 用模型真实输出替换 `reply_memory.py:134` 的套话），要么删除，消除契约漂移。
4. **`auto_reply_enabled` 配置化**：`reply_service.py:68` 硬编码 `True` 改为读 `core/config.py` 开关，使后端可独立关闭 auto 而不影响手动话术。
5. **记忆满自清洁**：cancelled 条目不占 80 条名额（`reply_memory.py:24-25`），或提供单条删除；避免满后 `memory_error` 静默永久失效。

## 分期路线

- **第 1 期（约 2d）**：P0-1、P0-3、P0-4、P0-5 + P4-1/2/4——零新依赖、改动集中后端，直接提升召回与可观测性。
- **第 2 期（约 2d）**：P0-2、P1-1a、P1-2 + P4-3——召回语义增强与 auto 只读记忆。
- **第 3 期（约 1.5d）**：P2-1、P3-1、P3-2——人性化与边界补强；P1-1b 评审后排期。

## 明确不做（本期）

- 不引入向量数据库/embedding 基础设施（无现有依赖，词法 + LLM 改写未验证到瓶颈前不加重型方案）。
- 不改"后端只生成不发送"的架构与落库隐私边界。
- 不做逐字符打字模拟、已读回执操控等激进拟人手段。
- auto 模式不放开自动写记忆（P1-1b 单独评审）。

## 验证基线

- 后端：`backend/tests/test_whatsapp_reply_service.py` 等现有套件 + 上述新增用例，pytest 全绿。
- 扩展：`tests/autoReply.test.ts`、`autoSend.test.ts` 等 vitest 套件全绿；分段延迟改动用 fake timers 覆盖。
- 收工前按仓库约定跑 `python scripts/git_sweep.py --no-fetch` 巡检。
