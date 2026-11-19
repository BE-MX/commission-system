# 2026-11-04 main 7b1248d8 全局生产发布（中间阶段）

已通过办公室统一入口发布 `7b1248d8c00c38029540f68c5aa867e43bb6d705`，发布ID `1a5e2dd615e94e5a97dfa1964efcd02c`。prepare/activate均退出0，分别675.62/235.72秒（阶段耗时，不代表停服时长）。两地Git HEAD独立读回一致，26项必需后检通过，五站HTTPS200；当时schema保持249，Scheduler办公室单活、出库恢复，邮件及旧新加坡同步保持停用。

本阶段上线充值凭证粘贴与Kubai导航图标；固定候选60项前端回归、构建和严格检查通过。生产登录态浏览器验收因Computer Use Transport closed未进行。

发布期间远端又合入私海助理 `59f93e79`，按用户“最新代码全局部署”目标继续准备并发布。最终生产版本、schema与验收见[最终发布记录](2026-11-04-full-main-production-release-59f93e79.md)。本目录历史证据 `.deploy_state/full-main-release-20261104-7b1248d8/` 保留。
