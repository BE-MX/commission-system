# 2026-10-22 最新 main 全量生产发布

已按用户「拉取最新的git代码进行部署」授权，将拉取时最新 `origin/main` 固定为 `3cf507089a9f56294598f67a88000c493912e7b6`，通过该候选自身的 `deploy/deploy.bat` 完成办公室及云端全部 11 个受管目标。两地安装版本、发布回执与固定候选一致。

## 发布结果

- 原生产版本：`7b2e954029d4f541a2499754543baaf4f1504956`。
- 发布 ID：`0af2522c43a74871b709a0621fbea498`；范围 `office-and-cloud`，无 deferred 目标，入口退出 0，发布锁已释放。
- 正式入口北京时间 12:01:52 至 12:09:50，耗时约 7 分 59 秒；独立监测至 12:10:03 结束。此前办公室 SSH 暂时不可达，在用户要求继续后重新连接成功，核实干净工作区、服务和锁后仅发起一次正式发布。
- 使用固定候选 `deploy/deploy.bat --live-root D:/commission-system --revision 3cf507089a9f56294598f67a88000c493912e7b6 --no-pull`，后台一次性计划任务承载入口，避免查询连接断开中止部署。
- 数据库保持 `201_portal_access_requests`，无新增迁移；生产数据与持久存储沿用受管入口保护。
- 出库保持 `legacy`，timer 恢复原 active/enabled；邮件 Worker 保留 inactive。Scheduler 仍办公室单活。门户经营开关保持原状：北京总开关 true、办公室 false；两地下单写入、发票、通知、邮件及门户出库 Worker 均 false。
- `festival_event_monitor` 持久暂停策略仍为 1、更新时间仍为 10/21 17:10:36；最后记录执行仍是 10/21，未恢复大单/超级大单推送。

## 独立验证

- 两地 Git HEAD 均为固定候选；办公室工作区干净，NSSM 后端、WhatsApp Connector、办公室 HTTPS 服务均 Running；两地 API/数据库健康检查通过。
- 六个静态入口 index 与实际安装制品一致，已列出的入口 JS 摘要一致：办公室 LAN、leshine.work、pm.leshine.work、leshine.cloud、media.leshine.cloud、shop.leshine.cloud。
- 两地 `load_access_manifest()` 成功，导航源码与清单 source_sha256 一致，120 项常用导航策略可加载；门户 OpenAPI 注册、新表/列只读核验通过。
- 出库 poller、creator、mode、stock 四模块逐字节等于办公室固定候选，并与同提交 Git 内容的 Windows CRLF 检出结果一致。首次辅助校验直接比较 Git LF blob 而失败，独立确认四文件均仅为 CRLF 差异后，增加固定候选实际摘要比对，重新校验通过；未修改部署制品。
- 2 秒采样下，本机 API 首次失败至首次恢复约办公室 24.6 秒、北京 14.0 秒；公网分别约 26.5 秒和 16.0 秒。属于探测窗口，不能当作精确用户停机时长。
- 发布前后原有 68 个本地文件逐项 SHA256 一致；随后仅新增本报告及前置交接记录。本机 main 工作区已有资料未参与生产候选，未合并、提交或推送这些改动。

## 证据与边界

证据在 `.deploy_state/full-main-release-20261022-3cf50708/`，包括 `office-evidence.json`、`beijing-evidence.json`、`static-verification.json`、`navigation-verification.json`、`portal-readback.json`、`outbound-artifact-readback.json`、`scheduler-pause-readback.json`、`measurements.json`、本地文件摘要及 `server/` 下原发布日志和回执。

一次性任务 `ArkFullMain3cf5070820261022` 已核实退出 0、导出 XML 并移除；未清理现有生产数据、其他服务或他人工作区。静态和候选历史制品维护仍按部署器默认延后。

该结果证明受管技术发布和所列只读回读通过，不替代真实订单、库存占用或供应商写入业务验收。独立 Agent/MCP、hair/video、未开通 PM 云域名及终端安装不计为已升级；小程序源码随 Git 更新，微信上传审核发布仍需独立执行。
