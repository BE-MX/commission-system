# 2026-11-02 最新 main 全局托管部署

已部署版本：`d4a6d3ffa6a6b28740cd8775a5d2cf4ca678a1a7`。发布 ID：`a1f0c51de2684d16a94be2c387fd77a3`。范围：`office-and-cloud`，用户明确授权拉取最新 Git 并全局部署。

## 结果

- 办公室与北京后端 HEAD 均为固定候选；`publish-current.status=succeeded`，`schema-writers.status=completed`，受管发布目标 `deferred=[]`。
- 主站两入口、PM、客户素材、客户门户五个 HTTPS 入口均为 200；26 项必需发布后检查全部通过。
- 数据库由 `214_sales_return_ledger` 沿 227–246 单链迁移到 `246_domestic_followup`。44 张新增表齐全；1494 张既有发票全部为 legacy，authority 无缺失或路线不一致；`legacy_only` 保持，未激活本地交易路线，没有本地历史回款。
- 出库轮询器版本及摘要核验通过，恢复原 active/enabled 调度；邮件 Worker 保留原 inactive/disabled 状态。其他写入实例按原基线恢复。
- 主目录原有 107 个改动文件在写入本报告/交接记录前均 SHA256 一致，暂存区为空；handoff 原文完整备份并保留。

## 执行与证据

办公室连接最初不可用，通过 UU 远程重试原有办公室会话恢复既有 2223 转发；未修改映射配置或 SSH 信任规则。两端 fetch 后固定 origin/main 为候选 SHA，办公室从原 `f79af949` 快进发布。

使用受管源码 `D:/commission-system/.deploy_state/sources/<SHA>/deploy/deploy.bat --live-root D:/commission-system --revision <SHA> --no-pull`，先 `--prepare-only` 成功再激活。准备 565.05 秒，激活 258.28 秒；未手工执行迁移、stamp、downgrade 或独立服务重启。

迁移独立静态审查及生产只读预检确认新表无重名、FK 主键类型匹配、旧回款唯一约束存在且外键另有独立索引、无本地历史回款。部署相关 Python 回归 43 项、Node 本地路线隔离回归 3 项通过。主站及门户构建成功；大文件体积和可选 matplotlib 缺失提示非阻断，色卡版本核验后跳过导入。

本机证据：`.deploy_state/full-main-release-20261102-d4a6d3ff/`，包括 preflight、schema-preflight、migration-risk-audit、prepare/activate-readback、postcheck、readback、final-receipt 和 local-preservation。完整准备与激活日志保留于办公室同名目录。

## 范围边界

这是项目登记的全局托管发布。`pm.leshine.cloud` 尚未配置 DNS/TLS，hair/video 权威源码在仓库外，独立 Agent/MCP/同步服务与终端安装不冒充本次已升级；未知探针状态另列在 postcheck。静态和候选历史清理按既有策略延后为独立维护任务。本次完成技术部署与只读验证，不等同于登录态业务验收。发布记录留在本地，未追加 Git 提交或向 origin 推送。
