# 客户邮件 MVP 合并与正式发布

2026-10-04，按用户“合并推送部署”授权，已将邮件 MVP 与最新 main 整合并发布。发送白名单保持仅 `86muliang@163.com`，本次没有新增外部发信。

## Git 与验证

- 应用提交：`acdec9d9067b91d8bb8ff4ab25daa94f61bd025e`，包含 main 的客户概览卡片更新及邮件完整链路。
- 在任务工作树合并最新 main 无冲突，再在主目录快进 main 并推送 origin；远端 SHA 已回读核验。
- 合并后 SQLite 隔离邮件后端 66 passed；前端邮件 10 passed；Node Worker 15 passed；增量严格约定与 diff 检查通过。仅有既有 python-jose UTC 弃用警告。
- 办公室候选主站构建成功（20.62 秒、113 个导航入口）；PM 制品未变化并复用。构建的大包提示不阻断发布。
- 主目录原有 23 个未提交/未跟踪文件均保留：21 个按原文件 SHA256核对，重叠的部署说明和交接文档按原始补丁 patch-id 核对。原始备份与 stash 保留。

## 正式发布结果

- 办公室 `D:/commission-system/deploy/deploy.bat` 固定应用 SHA，依次执行 `--no-pull --prepare-only` 和 `--no-pull`，均退出 0。
- release_id：`2cdfa6e9d3e542d68c94f8f965f34841`；scope=`office-and-cloud`；最终状态 `succeeded`，`deferred=[]`。
- 办公室 HEAD 为应用 SHA，健康 `ok/connected`。北京后端内容与 `1542e47e` 完全一致，部署器返回 unchanged 并复用旧 checkout，健康 `ok/connected`；不能把候选 SHA 当作北京实际 checkout SHA。
- 两地主站静态制品已更新；PM 和客户素材静态制品未变化并核验。邮件 Worker revision 为应用 SHA，running=true，systemd active。
- 共享数据库仍为 `173_task_center`，无 DDL；出库回执 verified，原调度 active/enabled=true 已恢复。
- 发布后从公网检查 `leshine.work` 和 `leshine.cloud` 的邮件页面入口、主 JS/CSS、邮件队列 JS/CSS，共 10 项 SHA256 与本次候选清单一致。
- 既有未纳管独立服务、未开通 DNS/TLS 的 PM 云域名及仓库外 hair/video 目标不在本次完成范围。

## 证据与边界

- 昨日真实收发、自动关联与人工分类证据见 [验收记录](2026-10-03-customer-mail-mvp-progress.md)。本次仅集成和发布，没有重复发送验收信。
- 本机证据：`.deploy_state/mail-mvp-main-integration/`，含原始文件指纹、重叠文件备份、构建清单、10 项公网核验、准备/发布日志与发布回执；`evidence/reply-acceptance.jpg` 为真实回信处理截图。
- 办公室日志：`.deploy_state/mail-worker-transfer/main-integration-prepare.log`、`main-integration-publish.log`。保留生产受管候选与配置备份用于恢复。
