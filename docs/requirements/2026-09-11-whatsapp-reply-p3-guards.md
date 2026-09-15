# WhatsApp 话术 P3：人性化延迟与安全边界（2026-09-11）

对应优化方案 `docs/2026-09-11-whatsapp-reply-optimization.md` 第 3 期（P2-1/P3-1/P3-2），并收尾第 1 期安排的 P4-1/P4-2/P4-4/P4-5。分支 `kimi/whatsapp-reply-p3`（基于 `kimi/whatsapp-reply-p1`）。

## P2-1 段间延迟拟人化（扩展）

- 首段前"阅读延迟"：1200ms + 客户最后一条消息长度 × 20ms/字符，封顶 4000ms。
- 后续每段前"打字延迟"：800ms + 段长 ×（40–80ms 随机系数）×（0.9–1.1 抖动），封顶 8000ms。
- 发送前重检、段间新客户消息丢弃剩余段等既有安全逻辑不变。

## P3-1 名单与时段限制（扩展）

- `LocalState` 新增 `autoReplyBlocklist`/`autoReplyAllowlist`（按聊天标题加盐哈希，各 500 条 FIFO）、`autoReplyAllowlistEnabled`、`autoReplySchedule`（本地时区 HH:MM 起止 + 周日到周六勾选，支持跨午夜）。默认全空 = 行为与现状一致。
- background 新增 `reply/auto-policy/get|set-chat|set-allowlist-enabled|set-schedule` 四个消息，非法输入回 `reply_invalid_request`。
- 执行：被禁聊天拒绝开启；白名单模式下非成员拒绝开启；接管进行中被拉黑立即停止；时段外不生成不发送、保持接管并提示。面板「询盘与接管」页新增「自动接管名单与时段」最小设置区。

## P3-2 金额代码级护栏（后端）

- `reply_direct.py`：auto 模式回复命中金额表达（货币符号/币种代码前后置/中文币种词）时，金额必须能在本次选中的绑定资料文本中找到同一数字（边界匹配、千分位归一）；找不到则强制 `handoff`，附 `price_unverified` + `auto_reply_review_required` 风险标，handoff 的下一步写明真实原因。聊天原文不算依据（客户报价与模型臆测无法区分），目录无价格数据不能作证。草稿模式不受影响（人工审阅环节仍在）。

## P4 收尾

- **P4-1 超时接线**：suggest 的 HTTP 超时改用当次 capability `timeout_seconds`（本地钳 ≤180s），回退 185s；修复 capability 下发不生效的 wiring 缺口。
- **P4-2 文档**：`REPLY-ASSISTANT.md` 按 1.6.5 全文重写（触发方式、历史档位、12 万字符上限、上滚加载、接管全行为、记忆绑定、名单/时段、金额护栏、capability 超时）。
- **P4-4 auto 独立开关**：`WHATSAPP_REPLY_AUTO_ENABLED`（默认 true）。关闭时 capability `auto_reply_enabled=false`，且 `mode=auto` 请求直接拒绝（`reply_auto_disabled` 403），手动话术不受影响；计入配置签名。
- **P4-5 记忆自清洁**：`build_update` 超 80 条上限时先回收 cancelled 条目，仍超限才报 `reply_memory_full`。
- 扩展侧补登记 `reply_auto_disabled` 错误码与 `price_unverified`/`knowledge_binding_stale` 风险标中文文案。

## 验证

- 后端 pytest：reply 相关套件 113 通过（新增：未核实金额转人工/有依据放行/草稿模式不受影响、auto 开关拒绝与 capability 反映、cancelled 回收后写入与仍满报错）。
- 扩展 vitest：313/313 通过（新增 14 例：延迟公式区间与封顶、名单/时段执行、policy 消息校验与淘汰、capability 超时接线）；`tsc --noEmit` 通过。
- 未做实机 WhatsApp 联调；名单/时段仅当前设备生效（未做服务端同步）。

## 方案外发现（留待后续）

- `reply/auto-policy/*` 与 `reply/memory-binding/*` 的 `chatTitle` 未校验类型（沿用现有惯例）。
- policyView 的本地提示文案未进 REPLY_COPY 错误码体系（与 memoryView 做法一致）。
- P1-1b（auto 自动写记忆）仍待评审；向量检索按方案继续不做。
