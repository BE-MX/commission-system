# WhatsApp 话术检索 P0 优化（2026-09-11）

对应优化方案 `docs/2026-09-11-whatsapp-reply-optimization.md` 的 P0 部分，分支 `kimi/whatsapp-reply-p0`。不改变"后端只生成不发送"、不落聊天正文、证据 hash 绑定与生成后复查等既有安全边界。

## 改动内容

1. **中文查询词修复（P0-1）**：`knowledge/reply_sources.py` 新增 `extract_query_terms`——ASCII 词保持原有 `{2,80}` 与英文停用词语义，CJK 连续段改为 2-gram 切分（单字丢弃）。修复中文整句被当成一个不可命中的长词的问题；`focus_query` 同步受益。`_score` 内 title/text/alias 的 casefold 上提，适配查询词上限放大后的打分开销。
2. **查询词截断策略（P0-3）**：`reply_service.py` 查询词上限 120→300；保留顺序从"尾部截断"改为：配置别名命中优先，其后按消息新近度保留（最新优先，最旧先淘汰）。
3. **LLM 查询改写（P0-2）**：新模块 `whatsapp_translation/reply_rewrite.py`。词法检索只命中必需约束、没有任何答案性段落时，用独立预设 `WHATSAPP_REPLY_QUERY_REWRITE_PRESET`（默认 `whatsapp_reply_query_rewrite`）对最近客户消息（≤2000 字符）做一次轻量改写，输出 ≤16 个检索词组并入评分后重检。改写结果只用于检索打分，不进生成 prompt、不触客。预设未配置/未启用/调用失败/输出非法均静默回退纯词法检索；按客户消息哈希进程内缓存 10 分钟。bootstrap 会准备**关闭**的独立预设（max_tokens=400），需管理员核验后手动启用。
4. **绑定失效可观测（P0-4）**：文档可取到但修订/章节/长度/hash 不匹配时，`resolve_binding` 记录 warning 日志（document_id、section_index、原因，不含内容）；`retrieve_reply_sources` 新增可选 `audit` 出参，回复响应追加 risk flag `knowledge_binding_stale`；`scripts/validate_whatsapp_reply_profile.py` 的 invalid 条目带失效原因。ACL 排除与到期下线不记 stale（属预期行为）。未新增 HTTP 端点：保存链路提示由现有校验脚本与运行时日志/risk flag 覆盖，避免产生无前端消费的 API 表面。
5. **catalog 触发词配置化（P0-5）**：`WHATSAPP_REPLY_CATALOG_RULES`（JSON list，默认空=沿用原 weft/genius 行为），规则形如 `{"trigger": "<regex>", "terms": [...]}`，首个命中规则生效，顺序即优先级。配置非法（坏正则、超限）时报 `reply_configuration_invalid` 并计入配置签名，与 source profile 的 fail-closed 口径一致。

## 顺带修复

- `test_whatsapp_translation_api.py` 的路面白名单补上既有的 `POST /reply-memory`（main 上既有失败，非本次引入）。

## 配置项

| 变量 | 默认 | 说明 |
|---|---|---|
| `WHATSAPP_REPLY_QUERY_REWRITE_PRESET` | `whatsapp_reply_query_rewrite` | 改写预设名；预设不存在或未启用时改写自动关闭 |
| `WHATSAPP_REPLY_CATALOG_RULES` | `[]`（用内置 weft/genius 规则） | 配置后整体替换内置规则 |

## 验证

- 合成数据测试：`test_whatsapp_reply_sources.py`（bigram 切分、中文整句命中、stale audit+日志）、`test_whatsapp_reply_catalog.py`（自定义规则触发/替换默认/非法配置 503）、`test_whatsapp_reply_service.py`（中文端到端命中、300 上限新近度优先、改写恢复漏召/成功时不触发/失败回退、stale risk flag）、`test_whatsapp_reply_state.py`（seed 两个关闭预设）。
- 隔离 SQLite：reply 相关 14 个文件 148 通过、1 跳过；`knowledge` 与 `whatsapp_translation` 范围 158 通过（含路面白名单修复）。
- 未调用真实模型，未使用真实客户或知识数据；改写预设上线前需管理员核验并在实机验收召回提升。
