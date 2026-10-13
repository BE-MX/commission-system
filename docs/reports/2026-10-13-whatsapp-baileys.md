# WhatsApp Baileys 本地改造与验收

日期：2026-10-13。分支：`codex/whatsapp-baileys`。实现与本地验证完成；2026-10-13 用户已授权提交、合并和推送，未部署。集成回执见 docs/handoff.md。

## 范围与行为

依据用户提供的开发方案、二次评估和本轮明确授权，修改方舟 WhatsApp 连接与同步。评估文档的“只读”要求属于当时评估范围，本次实现不据此停在评估；生产发布和真实账号测试仍未执行。用户确认公司专用业务号允许全部会话，包含群聊。

- Connector 使用锁定的 `baileys@7.0.0-rc14`，移除 Chromium/whatsapp-web.js 运行依赖。公司业务号由持有人明确授权，保留账号 UID 重绑；二维码只在内存短期保留。
- 凭据和 Signal keys 使用外部密钥加密持久化，账号租约、递增 token、generation 和 consent_version 阻断旧进程及旧授权写入。采用单机 SQLite WAL，不支持共享网络盘或多主机并行运行同一账号。
- 先持久事件，再同事务更新当前消息和变更序号；方舟默认每 5 秒消费一批、上限 500 条。消息、来源映射、CRM 投影与 checkpoint 一起提交；毒性条目仅隔离元数据，数据库错误回滚整个批次。
- 实时、append、历史事件保留完整消息 key 与 PN/LID 别名，避免仅按时间戳漏掉迟到消息。编辑按 revision 更新，撤回清除当前正文与附件，旧事件不能复活消息。未知类型显示安全占位，媒体只同步元数据。
- 显示已获取的覆盖时间、历史状态和缺口，不声称手机全历史同步完成。历史 whatsapp-web.js 数据保留，只有可精确验证的直接聊天旧 ID 才接续，不猜配群聊和 LID。
- 聊天查看页上方为账号管理，下方全宽显示会话列表及消息正文；收到的消息靠左、发出的靠右。手机端上下排列并换行分页控件。后续以正文示例核验时发现原账号/聊天并排布局挤窄正文，已修正并重新构建和运行关键流程。
- 管理员默认只看连接元数据；正文读者、CRM 共享和 AI 外发分别授权。正文、CRM、缓存画像及 Agent 分析在读取或结果发布时重验当前账号、用户、授权和客户范围，撤权后不可从旧派生结果绕过。
- 解绑先提交本地停止授权，再请求 Connector 注销。超时只读回查，不能盲目重发；Baileys logout 完成不等于远端确认。页面明确显示远端未确认，持有人手机核对记录为 `owner_confirmed`，与协议确认区分。

应用没有发送消息、标记已读或修改聊天的 API。rc14 在 `markOnlineOnConnect:false` 下仍会发送协议要求的 offline presence 握手；这点已在实现说明中标注。

## 验证证据

所有测试使用隔离数据库、合成事件或被拦截的 API；未读取真实聊天，未生成真实扫码会话，未调用真实 AI 服务。

| 检查 | 实际结果 |
| --- | --- |
| 后端 18 个受影响测试模块 | 283 passed、1 skipped；1 项既有 Matplotlib 环境警告 |
| 最终保护状态只读回查改动后的受影响回归 | 33 passed |
| Connector Node 测试 | 41 passed，含真实多进程租约竞争、崩溃恢复、加密、原子 checkpoint、权限回调及 HTTP 契约 |
| Connector 语法与依赖审计 | 语法检查通过；`npm audit --omit=dev` 0 漏洞 |
| 前端状态测试 | 2 passed |
| 前端生产构建 | Vite 构建通过；保留既有 vendor chunk 大小提示 |
| 浏览器关键流程 | Edge + Playwright，1440px/390px，9 项流程，23 个合成请求，0 pageerror；手机授权弹窗实际截图已核对 |
| 迁移 | 隔离 SQLite 旧数据升级保留 ID/正文并清理旧二维码；MySQL 离线 DDL 验证 unsigned FK；没有执行生产 MySQL 迁移 |
| 增量代码约定 | 无违规；`git diff --check` 通过 |

后端完整日志：`backend/tmp/whatsapp-baileys/final-tests.log`。浏览器脚本：`frontend/tests/whatsappSync.browser.mjs`；截图在 `frontend/tmp/whatsapp-baileys/`。独立 Connector 与后端审查发现的问题均修复并补回归，最终均无剩余 P1/P2；后端最后一轮关闭审查另跑 4 项测试通过。

全仓 `check_conventions.py` 仍被发票页面既有 17 项 UI 债务阻断，同样结果已在原 main 复现。额外扩大检查发现 `test_customer_evidence_choices.py` 的 3 项既有失败，在原 main 上也复现为 3 failed / 3 passed，未纳入本次已通过的 18 模块范围，也未修改无关逻辑。

`python scripts/git_sweep.py --no-fetch` 已于收尾执行，exit 0，报告 `tmp/git-sweep.html`。这是本地远端引用快照；巡检指出其他分支的既有 186 撞号和其他 worktree 未提交工作，本任务未处理或清理它们。

## 部署前必要条件

运行要求与步骤见 [Connector README](../../services/whatsapp-connector/README.md) 和 [runbook](../runbook.md)。使用 Node >=22.13，配置独立的 32 字节 base64 加密主密钥、服务间 API key、方舟回调地址及可写本地 SQLite 路径；避免在日志中输出这些值。

迁移 `192_wa_sync_fencing` 基于本任务起点的 `186_domestic_delivery`。创建前已检查所有本地分支及工作目录，避开其他任务 187–191。集成最新 main 时仍须对账其他迁移，确保唯一 head，不可直接跳过并行 revision。迁移仅扩展字段和表并清理旧临时二维码，禁止降级删除业务数据。

仍待部署授权后的真实验收：专用公司号扫码、设备重启恢复、实际聊天/历史覆盖、真实手机解绑确认和目标 Node/MySQL 环境验证。此报告的通过结果不代表这些线上步骤已完成。旧会话不能原样导入 Baileys，启用后需要手机重新关联；已有方舟历史记录保留。

本次一个合成测试临时目录的递归清理被自动审批以删除限制拒绝，目录保留为验证材料；没有换工具绕过。
