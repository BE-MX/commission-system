# WhatsApp 话术 P1：auto 记忆只读接入与语言修正（2026-09-11）

对应优化方案 `docs/2026-09-11-whatsapp-reply-optimization.md` 的第 2 期 P1 项，分支 `kimi/whatsapp-reply-p1`（基于 `kimi/whatsapp-reply-p0`）。P1-1b（auto 自动写记忆）按方案要求留待单独评审，本期不做。

## P1-1a auto 模式记忆只读接入

- **绑定持久化**：扩展新增 chat→inquiry 映射，键为加盐哈希后的聊天标题（复用 `chatKey` 范式，不落明文），存 chrome storage 的 `chatInquiries`，上限 200 条 FIFO 淘汰；读写走 background 新消息 `reply/memory-binding/get|set`，inquiryId 校验 UUID 格式。
- **面板维护绑定**：`generate()` 自动创建、`newInquiry()`、`usePreview()` 成功后写绑定；`deleteMemory()` 后清除。`generate()` 在记忆开启且无当前记录时**先读绑定恢复**，不再每次刷新都新建孤儿 inquiry；绑定失效（not_found）清除后走原创建路径，瞬时错误保留绑定并跳过创建。
- **auto 只读接入**：开启接管时异步初始化（读绑定→`read` 拿最新 revision，`memoryReady` 门挡住首轮 suggest），之后每轮请求带 `memory_conversation_id`/`memory_revision`，后端 `saved_observations` 注入即可消除"反复追问"。响应 `memory_error=reply_memory_conflict` 时后台重读刷新 revision（下轮生效，本轮草稿照发）；`not_found`/`disabled` 丢弃本地绑定并清存储。auto 全程**只 read，不 create、不 commit**，写路径维持人工采纳不变。
- **提示**：接管开启且无绑定时，经既有状态通道提示"未绑定询盘记忆…在话术面板生成一次即可建立"，不阻断接管。

## P1-2 glossary 语言选择修正

- 后端 `ReplyRequest` 新增可选 `detected_language`（"" 为未知，限已支持语言码）。glossary 选词表顺序改为：`detected_language` > 非 auto 的 `target_language` > `fallback_language`，修复 `target_language=auto` 时错用词表的问题。
- 扩展侧复用入站翻译的检测回调（`incomingTranslator` → `onDetectedLanguage`），按聊天会话跟踪最近检测语言，手动与 auto 请求均携带；切聊天重置；与用户手选的回复语言完全分离，未知则不传。

## P4-3 死 schema 处理

- 删除 planner 时代的 `ReplyPlan`/`ReviewEvidence`（生成链路从未使用，仅测试夹具引用，测试改为逐字段校验的 `SimpleNamespace`）。
- `claims`/`status` 保留：二者在线上契约内（扩展校验 `claims`、评测断言 status 枚举），删除会破坏线契约。
- `handoff.next_step`/`action.focus` 接入真实数据：auto 转人工时用真实复核原因（如"模型分段格式不完整…"），草稿模式用首条 `missing_information`，替换原固定套话"核对并使用建议回复"。

## 验证

- 后端 pytest：reply 相关套件 102 通过 1 跳过（含新增：detected_language 驱动 glossary 三档优先级、非法码 422、handoff next_step 两种模式、ReplyPlan 移除后的 memory 回归）。
- 扩展 vitest：299/299 通过（新增 16 例：绑定读写/淘汰、auto 绑定携带与冲突自愈、面板恢复不重建、detected_language 上报）；`tsc --noEmit` 通过。
- 未做实机 WhatsApp 联调；绑定按标题哈希，同名不同联系人会共享绑定（既有 identity 机制的已知限制）。

## 留待后续

- P1-1b（auto 自动 commit 记忆）需产品评审后单独排期。
- 手动面板收到 conflict 只提示不自动重读（保持人工确认语义）。
- `setMemoryEnabled(false)` 不清除已存绑定（auto 仍会读）；如需要可在后续补"按聊天停用记忆"开关。
