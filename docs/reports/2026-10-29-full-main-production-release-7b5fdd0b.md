# 2026-10-29 最新 main 全量生产部署

已部署版本：`7b5fdd0bad0021a0655832585c5f2ab7edfc3a84`。发布 ID：`e514f54504d9474da03353e5d0f60d43`。入口：办公室 `D:/commission-system/deploy/deploy.bat`，固定 revision，范围 `office-and-cloud`。

## 交付与独立回读

- 发布前 fetch 最新远端 main 并固定候选；包含目标设置与绩效看板优化、验货单物流录入及薪资导出更新。办公室原版本为 `c66daee6`，工作区干净，无发布锁或未完成迁移记录。
- prepare 成功，耗时 506.61 秒；正式 activate 成功，耗时 230.67 秒。新加坡静态准备耗时较长，连接检查正常，原任务最终成功，没有重发发布。
- 办公室和北京后端实际 Git HEAD 独立读回均为本版本；publish-current=succeeded，受管发布目标 deferred=[]，schema-writers=completed。
- 办公室、北京后端、色块服务/路由及五个已登记静态站完成标准发布；未变化制品仍核验。26 项必需部署后检查全部通过。
- 共享数据库由标准入口统一执行 `212_portal_customer_settings → 213_salary_snap_export_cols`。独立 SELECT 返回唯一 revision=213；`ark_salary_record.snap_hire_date`、`snap_insurance_entity` 和 `ark_salary_period.export_seq` 的类型及可空性正确。迁移前冻结薪资明细和已确认薪资批次均为 0。没有 stamp、降级、复制数据库或生产业务测试写入。
- leshine.work、leshine.cloud、pm.leshine.work、media.leshine.cloud、shop.leshine.cloud 独立 HTTPS GET 均 200；两地主站首页 SHA256 同为 `2e8f135c496a47b2b4545d0fbf710cdaf52b8ec33c4b697653865ef83b9071cb`。这是静态和运行验收，未执行登录态业务操作。

## 基线与边界

- 北京出库 timer 恢复 active/enabled，shipment-tracking-mcp 的 PM2 进程在运行。邮件 Worker 保留 inactive/disabled，新加坡历史 okki-sync 保留 inactive/masked，未擅自启用停用服务。
- 独立服务、未开通站点和外部终端不计入本仓库发布成功范围；缺少探针的 okki-inventory、n8n、okki-shopify-cron、ark-okki-outbound-mirror 保留 unknown。
- 静态资源和候选清理按默认流程登记 deferred 维护任务；应用发布已成功，未额外执行维护删除。
- 本地原有 102 个待保留文件在部署后全部 SHA256 一致；随后仅新增本报告并在 handoff 顶部补入发布记录，保留原文。未额外提交或推送。

## 验证与证据

- 本轮隔离部署回归 103 passed；薪资导出与验货单物流关联回归 44 passed。候选主站、PM 和门户构建及受管依赖/迁移链预检成功。保留已有大分包与可选 Matplotlib 提示。
- 本地证据：`.deploy_state/full-main-release-20261029-7b5fdd0b/`，包括 candidate.json、preflight.json、prepare-readback.json、activate-readback.json、postcheck.json、readback.json、local-preservation.json、deploy-checks.log、business-regression.log、git-sweep.log。
- 完整执行日志保留在办公室同名目录的 prepare.log / activate.log。Git 巡检使用 --no-fetch，本地 main 与 origin/main 同步；未清理其他代理工作。
