# 2026-10-23 最新 main 完整生产发布

已按用户“拉取最新的 git 代码进行部署”授权，fetch 后固定远端 main 为 `569b1fe5be4d1a89dd09973dce52025bbe42ade3`，从候选自身的 `deploy/deploy.bat --live-root D:/commission-system --revision <完整 SHA> --no-pull` 完成办公室与云端受管发布。

- 原生产版本：`73ed997b989c89c7212782f39832bc671dc1a092`，是固定候选祖先；没有强制重置或覆盖分叉。
- 发布 ID：`fdb972af6336420fb1da085334f01a2e`；范围 `office-and-cloud`，11 个受管目标完成、deferred 目标为空，入口退出 0、发布锁释放。
- 成功尝试执行时间：北京时间 19:35:55–19:44:08，约 492.9 秒；这是入口总耗时，不是停服时长。19:44:21 包装任务结束。
- 数据库仍为 `202_presale_order_revision`，本轮无 schema 变更或迁移。运行环境、业务存储与现有配置沿用受管流程。

## 已发布范围

办公室应用与静态制品、WhatsApp 连接器；北京后端；两地色块路由；新加坡主站与 PM 静态站；北京主站、客户素材、客户下单门户；受管出库工件及邮件 Worker 版本核验。

包括本次门户全页 UI/激活修复，以及最新 main 中已有的商品大图/定价读取优化、底部固定操作区、结算独立滚动、员工 PI 详情及模板导出、国内单件终止与 WhatsApp 稳定性更新。代码发布不替代真实账号的业务验收；本次未为验证创建客户、订单、回款或发送业务消息。

## 实际回读

- Office HEAD、office-success，北京 HEAD、backend-success 和本轮 publish-current/publish-success 均对应固定候选。办公室工作区干净；北京受管源码及 index 无 diff，现有未跟踪环境备份、虚拟环境和运行目录保留，未清理或冒称整棵工作区干净。
- 两地 HTTP/数据库健康正常；办公室 CommissionSystem、WhatsAppConnector、ArkOfficeHttps 均 Running。系统探针与服务事件原始记录已保留。
- 六入口独立回读：`lan.leshine.cloud`、`leshine.work`、`pm.leshine.work`、`leshine.cloud`、`media.leshine.cloud`、`shop.leshine.cloud` 的实际 HTML 与安装文件 SHA256 一致，已声明入口 JS 也一致。
- 客户站额外核对 `assets/index-DN358aJ0.css` 及入口 `assets/index-CzXP5rD7.js`；实际 HTTPS 字节与安装文件一致。
- 客户站 `/api/portal/v1/session` 未登录 401，`/api/users/me` 与 `/.env` 为 404；门户相关 API 在两地 OpenAPI 中存在。
- 北京门户保持 enabled/writes/invoice=true，notification/mail/outbound-worker=false；办公室门户全部关闭。办公室 Scheduler=true，北京 Scheduler=false，保留单活分工。
- 出库当前 mode=legacy，调度 active/enabled 均保持原 true 基线；邮件 Worker 当前不运行，保持原停用状态。

## 准备阶段问题与修复

首次尝试在服务切换前报 `No module named 'dotenv'`。只读回查证实旧生产版本、成功发布 ID 和两项服务均未变；系统 Python 3.14 缺模块，项目虚拟环境及在用服务环境均具备依赖。候选 deploy.bat 在自身无 .venv 时使用 PATH 中的 python，因此第二次仅按部署文档将安装目录 `backend/.venv/Scripts` 放到 PATH 前端，继续同一固定候选，没有安装全局包、修改候选代码、替换凭据或绕过门禁。首次失败日志、任务 XML 和结果单独保留。

两个一次性计划任务均在终态检查和导出 XML 后移除，未创建周期任务。发布后默认登记静态/候选保留维护为 deferred；没有额外执行磁盘清理。platforms.json 中未纳管的独立服务与 pending 站点不计为本次已更新范围。

## 证据与本地保护

成功记录：`.deploy_state/full-main-release-20261023-569b1fe5-retry/`，包括 office-evidence、beijing-evidence、static-verification、portal-readback、portal-boundaries、portal-styles、post-verification、task-cleanup 及 server 下日志/回执/探针。首次准备失败和本地基线：`.deploy_state/full-main-release-20261023-569b1fe5/`。

主目录原有 79 个改动/未跟踪路径在写本记录前均 SHA256 相同、status 原样、index 为空；本次仅新增此报告及在 docs/handoff.md 顶部加本轮记录，原文保留。未额外 commit 或 push 本地文档。
