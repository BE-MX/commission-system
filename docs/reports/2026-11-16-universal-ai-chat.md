# 通用 AI 工作台首版交付（2026-11-16）

## 结果与范围

在原 Vue/FastAPI AI 工作台升级，复用认证、权限、附件和供应商接入。分支 `codex/universal-ai-chat`，工作区 `D:/MyProgram/commission-system-codex-universal-ai-chat`，基点 `411a526c`。用户已授权本次提交、合并 main 并推送 origin；Git 结果以远端回读为准。未部署或写生产。

- 平台级 AI 工作台默认通用对话；设计组保留 AI 生图。原聊天 URL、权限和内置对话方式继续可用。
- AI 接入预设新增开放开关、显示名称、图片能力和可用角色。仅直连 OpenAI/Anthropic 文本协议模型进入目录；业务专用、生图及 agent 预设不能借此越权。
- 每轮选模型，回答保留模型标识，推理独立折叠；支持经清洗的 Markdown、回答/代码复制、重生成、停止、附件拖入与粘贴。纯文本模型拒绝图片历史，不静默丢失内容。
- 私人会话支持分页、重命名和软删除；删除后消息/附件入口均失效。保留历史与计数记录。
- 每用户默认每日 100 次受理生成，北京时间零点恢复；停止/失败仍计数，幂等重放不重复占用。用户行锁串行准入，同会话只允许一个生成。
- 管理元数据不透传供应商；预设发布不会破坏原有可信文本调用方。

配置步骤见 [需求契约](../requirements/2026-11-16-universal-ai-chat.md)，[API](../api-reference.md) 和 [数据库](../database.md) 已同步。

## 迁移与权限

`265_universal_ai_chat` 下接 `264_private_research_tools`，当前 Alembic 单 head。新增会话模型选择/软删除、消息模型摘要/推理正文；MySQL 正文扩为 MEDIUMTEXT。旧记录保留，新字段 NULL，不猜测补填历史模型。不自动 downgrade 丢弃聊天信息；生产迁移仍只走授权部署入口。

调用前对账号、角色及预设/供应商作锁定当前读，并冻结本轮配置，避免旧事务快照或管理员更新导致模型错用。客户端不能自填供应商地址、密钥或参数；软删除不能清除已用额度。

## 实际验证

所有写入仅限隔离 SQLite 或本次新建的本机 MySQL 8.4.13。供应商 HTTP 使用 MockTransport，没有真实模型调用。

| 检查 | 结果 |
| --- | --- |
| 首轮受影响后端（universal/service/router/stream/cleanup/owner/idempotency） | 106 passed；2 项原有草稿清理失败，见下文 |
| 最终模型、生命周期、协议及已有 client-desk 共享调用 | 80 passed；含 ASGI 2.3/2.4 的 6 个早期断开场景、终态保护、空答案上下文与冻结模型配置 |
| 补充模型与跨时区用例 | 20 passed；覆盖模拟 UTC-8、UTC、UTC+9 主机的北京时间零点额度重置和软删除时间 |
| 真 MySQL 自有进程 | 4 passed：265 保留旧记录并保存 10 万中文字符、并发仅一笔获准、旧 RR 快照下角色撤销和模型下架均被拦截 |
| 前端聊天状态 | 35 passed；含丢失 meta 后同键重试、旧刷新不能清除新请求键、草稿隔离、模型/图片/额度限制 |
| 导航与图标 | 11 passed；构建生成的导航契约已同步 |
| 前端构建 | `npm run build` 通过；保留项目已有大 chunk 提示 |
| 真实浏览器 | 桌面及 375×812，真实 Vue 组件配内存模拟接口；模型切换、流式停止、重生成、推理折叠、代码复制、会话改名/删除/隔离、无模型草稿输入及管理员角色配置通过 |
| 约定与 Git | 增量约定、diff 检查通过；`git_sweep.py --no-fetch` 已运行，只代表本地快照 |

表中回归批次存在重叠，不将它们相加为唯一测试数。日志/截图在 `tmp/universal-ai-chat/`，可重跑入口为：

```text
backend/tests/test_universal_ai_chat.py
backend/tests/test_universal_ai_chat_lifecycle.py
backend/tests/test_ai_chat_stream.py
backend/tests/portal_mysql/test_mysql_universal_ai_chat.py
frontend/tests/aiChatState.test.mjs
frontend/tests/fixtures/universal-ai-chat/
```

MySQL 测试使用项目自有进程防护，显式传入 `--portal-mysqld`、尚不存在的 `--portal-mysql-workspace` 和 `--confcutdir=tests/portal_mysql`；校验 datadir/port/UUID，拒绝共享连接。浏览器服务及临时 MySQL 已停止。临时 MySQL 数据目录清理被自动审批审查拒绝，仅返回 `blocked by policy`，因此保留数据目录及运行日志，未绕过。

独立风险审查已完成。断开清理、并发准入、旧事务授权、配置冻结、空答案上下文、图像预设误入和前端幂等键竞态均已处理；持久回归由主代理补入并执行。

## 已知边界

1. `test_ai_chat_idempotency_cleanup.py::test_file_delete_failure_keeps_draft_record` 和 `::test_db_delete_failure_can_be_retried_after_file_is_gone` 仍失败。独立审查将 HEAD 草稿清理函数原样载入后复现，函数 AST 与工作区一致；本轮未改该逻辑，不表述为全套通过。
2. 正常断开/停止已验证；进程强杀可能留下 `streaming` 状态，目前无自动租约恢复，可能阻止该会话继续或删除。恢复前需核实上游已结束，不能盲目重置。
3. 仍只发初始 heartbeat，长时间无输出受网关空闲超时影响。尚未做真实供应商联调，发布验收需核验具体模型流式、图片和超时参数。
4. 搜索、语音、业务工具、原生 Gemini/Responses 和完整消息分支不属于首版。

需要发布时先对齐最新 main 与迁移编号，再由项目部署入口应用 265，在 AI 接入开放模型和角色，执行授权的真实模型冒烟。本次已授权 Git 集成和推送，明确暂不部署。


## Git 集成复验

用户追加授权提交、合并 main 并推送，暂不部署。任务提交已整合最新本地 main `0b1b04bb`（含 Monid 参数修复）；合并候选的聊天、生命周期、共享文本调用及研究工具回归 106 passed，前端聊天/导航/图标 46 passed，覆盖本次提交的增量约定检查通过。此前构建对应的前端源码未变。

主目录 130 个既有未提交文件已逐字备份；三处重叠文件在整合前准备了保留双方内容的恢复稿，其他文件不作修改。备份位于主目录 `tmp/universal-ai-chat-main-integration/`；Git 交付以最终 origin/main 读回为准，不表示部署。
