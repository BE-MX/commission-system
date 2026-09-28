# Agent 服务统一部署到 leshine.cloud

用户于 2026-09-26 指定：OpenClaw 相关服务统一迁到北京 `ubuntu@154.8.205.162`，后续新增 Agent 服务也部署在该主机，以 `https://leshine.cloud` 为公网入口。新增服务必须登记 `platforms.json`，涉及 `commission_db` 写入时同时登记 DDL writer。

## 本次范围

| 服务 | 管理器与路径 | 新入口 |
|---|---|---|
| OpenClaw 2026.6.6 | root user-systemd `openclaw-gateway`；`/root/.openclaw` | 回环 18789，沿用飞书连接，不公开管理台 |
| 钉钉群监听 | systemd `dingtalk-monitor` | 出站 Stream 连接 |
| 客户/库存 MCP | root PM2 `leshine-customer-mcp` | `/inventory-mcp/sse`、`/inventory-mcp/messages` |
| 物流 MCP | root PM2 `shipment-tracking-mcp` | `/shipment-mcp/sse`、`/shipment-mcp/messages` |
| 社媒客户 MCP | systemd `social-customer-mcp` | `/mcp/social-customer/`，原 Bearer 鉴权 |
| Agent 中继 | systemd `deputy-relay` | `/relay/ws`、`/relay/health` |
| OKKI 同步 | root PM2 `okki-index` 与定时任务 | 保留原任务及游标 |
| OKKI 出库轮询 | `ark-okki-outbound-poller.timer` | 每分钟，保留单活与在途排空 |
| OKKI / Shopify 定时同步 | `/etc/cron.d/ark-agent-sync` | 从源 root crontab 精确抽取 10 项 |

办公室主应用、n8n、frp、北京主应用、共享数据库及文件存储不在这次搬迁范围。`okki-sync.service` 和 `okki-inventory` 没有活跃实例，不因迁移额外启动。运行版本保持原版本，不安装 latest。

## 操作入口与状态

候选代码位于本次独立 `codex/agent-cloud-migration` worktree。统一入口按阶段执行：

```powershell
deploy\deploy.bat --agent-cloud-migration prepare
deploy\deploy.bat --agent-cloud-migration validate-staged
deploy\deploy.bat --agent-cloud-migration freeze-source
deploy\deploy.bat --agent-cloud-migration copy-frozen-state
deploy\deploy.bat --agent-cloud-migration configure-target
deploy\deploy.bat --agent-cloud-migration activate-target
deploy\deploy.bat --agent-cloud-migration verify-target
deploy\deploy.bat --agent-cloud-migration retire-source
```

此为固定对象的一次迁移工具，不可用于任意服务器。`prepare` 前由操作员校验目标主机公钥和空目标目录，并临时配置源 IP 限定、到期时间限定、forced-command `rrsync -wo` 的传输 key；它只能写目标 `/var/lib/ark-agent-migration/payload`。完成后删除该授权和源端临时私钥。私钥、环境文件、PM2 环境与会话只在两台服务器的受限目录间经 SSH 传输，不作为代码制品，也不落开发机磁盘。

源备份在 `/var/lib/ark-agent-migration/source`，目标状态在 `/var/lib/ark-agent-migration`；本地只有非敏感回执 `.deploy_state/agent-cloud-migration/`。先准备全部运行依赖，冻结源调度并等待在途任务结束后，再同步最终状态。目标激活前必须有最终冻结回执；确认目标健康后，源服务 disable/mask，移除三个已迁移 PM2 注册并保存空清单，防止重启或旧发布器复活。源历史 `okki-sync.service` 同样 mask。

2026-09-26 迁移已完成，临时传输授权和私钥已删除。上述阶段不是可重复部署命令：不要重跑源快照、配置或复制阶段覆盖原始恢复证据及北京新状态。后续更新使用对应服务的正式发布入口。

Nginx 单独使用 `agent_cloud_nginx.py` 的 `prepare/activate/verify`：精确绑定北京 machine-id、站点和原摘要；候选 `nginx -t` 成功后才激活，失败恢复原配置。备份在 `/var/lib/ark-agent-migration/nginx/<plan_id>`。不复制新加坡 generic `/mcp/` 的办公室 `8002` 代理到北京。

## 验收与恢复

验收须同时有：源实例停用、目标服务及调度单活、OpenClaw RPC、钉钉/飞书连接、真实 HTTPS/TLS、MCP initialize/tools/list/只读查询、无效社媒 token 为 401、中继健康与 WebSocket 握手、两地主站 `/health` 正常。进程 active 或首页 200 不能代替业务协议验收。

回滚先停北京调度并排空写任务，再停止北京 Agent；保留并核对北京新增的游标、会话和中继 SQLite（包含 WAL）。不能直接恢复旧快照或在北京仍运行时启动新加坡。只在状态无分叉后，把必要状态回传原路径、恢复源受限目录中的 unit/cron/PM2 基线，最后恢复入口。Nginx 可独立按其保存的原摘要回退。

主应用后续发布必须使用包含这次 `platforms.json`、`schema_release.py`、`timer_writer.py`、`okki_outbound_release.py` 调整的发布器。它以 ubuntu SSH + sudo 操作 root 的 PM2 和出库 timer。旧源 unit 被 mask 后，旧部署器应失败，不允许绕过 mask。

实际执行结果记录在 `docs/handoff.md`，本文件只定义归属和操作约束。
