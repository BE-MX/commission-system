# 2026-10-14 远端最新 main 完整生产发布

## 来源与范围

用户授权完整生产部署，并明确后续默认：部署前拉取远端最新 main，执行全局受管发布，不只发布当前对话差异。工作站与办公室均重新 fetch origin，确认候选为 `4b811874126c9437cb5892844d4cac280784c9ce`，随后全流程固定该版本。候选包含现网 `a7d39aaa` 全部历史，累计 58 个文件差异，无迁移文件变化。

办公室 SSH 最初不可用；用户恢复转发后 `office-prod` 已重新核验为 LYS-ACCIOWORK、安装目录 `D:/commission-system`，原应用版本 a7d39aaa、两个 NSSM 服务运行、发布日志 succeeded、迁移日志 completed、无发布锁。没有用仅云端发布替代完整范围。

## 执行与当前状态

从受管候选调用统一 `deploy/deploy.bat --live-root D:/commission-system --revision <完整 SHA> --no-pull`；准备阶段另加 `--prepare-only`，退出码 0。正式操作由本轮持久任务执行，发布身份 `a582deb58a3a47269e04c56d19ffab26`。

准备与正式部署均已返回 exit_code=0。应用、路由、五个静态目标及附属服务切换已完成，publish-current/success 均为本轮版本，deferred=[]。静态资源保留 status=succeeded，office、leshine.work、leshine.cloud 全部完成；收尾后再次验证两主域健康与六项公网制品 SHA-256 全部通过。完整发布已完成。

## 已验证结果

- 办公室及北京实际 HEAD 均为 4b811874。北京 8 个关键源文件与该提交逐字规范化匹配，覆盖内贸默认价、发票响应绑定/恢复、出库库存与角标查询。
- 办公室回环、leshine.work、leshine.cloud 的 /health 均 200、database=connected。真实身份只读接口中 navigation-preferences、WhatsApp accounts、待审核数量均 200；助手 options 缺参数正确返回 422。新库存详情路由已出现在运行中 OpenAPI。
- 两地主站制品均为 `67086895f643c709c6b0a93f0a6abe9f82f22812ef21da7de5c212ea4fdbc82f`，各处理 215 个变化文件。两站实际 HTTPS 的 index、MainLayout 与 domestic 脚本共 6 项 SHA-256 与本轮构建一致，包含 60 秒静默角标轮询代码。
- PM、素材及客户门户制品未变，已按完整清单核验。客户门户和其他经营开关保持原状态；本轮不代表新的经营验收。
- 共享数据库实际 `195_main_portal_merge`，无新增迁移；已有八张相关业务表仍存在。没有 stamp/downgrade，也未执行真实订单/审批/回款操作。
- Connector 受保护健康接口 200，provider=baileys。历史账号仍为旧 provider/pending，正文数量为 0；没有代替持有人绑定账号或外发消息。
- 北京 ark-backend、ark-colorwork、出库 timer、研究 Agent 均 active；出库 timer 仍 enabled，邮件 Worker 仍 inactive/disabled。独立服务和终端安装没有盲目升级至未指定的新版本。

## 独立服务覆盖说明

统一入口未把独立服务冒报为新版本发布。只读核验北京 deputy-relay、dingtalk-monitor、social-customer-mcp、wlai-tunnel、ark-sales-agent、色块备份 timer 和 root OpenClaw gateway 均 active；PM2 的 okki-index、leshine-customer-mcp、shipment-tracking-mcp 均 online。Agent 同步 cron 文件存在，此项不代表逐条任务执行成功。新加坡 frps active，旧 okki-sync 仍 masked；办公室 n8n 管理器仍未确认。hair/video 权威源码、未开通的 pm.leshine.cloud 及终端安装保持部署清单的既有边界。

## 验证边界与证据

部署测试 817 passed、18 skipped、1 个既有 storage-routing mock StopIteration 失败；该专项源码与已部署 a7d39aaa 相同，历史发布记录也已登记，并非本轮应用切换失败。角标实现此前 34 项相关 Node 回归及 8 场景受控浏览器验证通过；办公室本轮完整生产构建通过。

本地与办公室证据目录均为 `.deploy_state/full-main-release-20261014/`，包括候选计划、持久任务启动脚本、准备/正式日志、任务退出回执、独立 readback、北京源码摘要及最终状态。原 SSH 阻塞预检保留为历史证据，不冒充本轮最终结果。

主目录已有未提交工作保留；本报告与交接追加不自动提交或推送。生产受管候选/cache/回滚材料由部署入口维护。
