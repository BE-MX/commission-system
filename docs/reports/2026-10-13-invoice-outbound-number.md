# 翟 #261022 发票改号未同步发货单

## 实际读取证据

2026-10-13，只读查询共享数据库，并使用现存 token 执行小满 GET；未刷新 token、未发送业务 POST、未修改线上数据。

| 对象 | 读取结果 |
| --- | --- |
| 方舟发票 | ID 1053，当前号 `翟 #261022`，stock，synced；更新时间 11:25:23 |
| 原订单 | 小满 order_id `105851416713325`；实时 name 为 `翟 #261022`，update_time 11:25:21 |
| 原出库单 | outbound_invoice_id `105851418127778`；实时 serial_id 为 `Ginny-KC-1001`，status=1，update_time 09:41:49 |
| 镜像 | record ID 93344，与实时旧号一致；不是只因展示缓存未刷新 |
| 创建日志 | 1494，09:40:38，create 成功，请求 name 为 `Ginny-KC-1001` |
| 修改日志 | 1518，11:25:23，update 成功，请求 name 为 `翟 #261022` |
| 关联同步 | 该发票没有 InvoiceLinkedSync 记录 |

## 原因与修复范围

原逻辑只从最新关联同步记录的 before/after 判断改号。普通保存再同步没有此记录，即使原订单成功更新，后续出库同步也不传目标 serial_id。

本地修复从同订单成功 create/update 的请求与响应确认历史编号；最新成功推单名必须对应当前发票，旧出库号必须精确匹配历史名。沿用唯一关联、待出库、重号检查及原单更新/回读协议；自定义号、不完整证据、已出库或多单不扩大自动改号范围。

另增加目标发票号和实时出库旧号检查，防止扫描后仓库自定义改号被覆盖。原提交结果不确定时仍核对已发送的原任务，不重发。

修复位于 `codex/invoice-outbound-number`，尚未合并、推送或部署。线上原发货单尚未改号；生产发布与该单实际修改需要对应授权。

## 验证

- `pytest tests/test_outbound_invoice_sync.py tests/test_invoice_linked_sync.py -q`：143 passed，45 条既有 jose 弃用警告；隔离 SQLite 和模拟小满。
- `pytest --confcutdir=tests/portal_mysql tests/portal_mysql/test_mysql_outbound_execution.py -k ordinary_rename -q`，显式指定自有本地 MySQL 程序与全新工作区：3 passed。真实 MySQL 与当前员工授权执行器，供应商 HTTP/镜像边界模拟；覆盖普通改号成功、仓库扫描后改号拒绝、预览前发票再次改号拒绝。
- 独立审查发现扫描后覆盖仓库自定义号竞态，已修复并复审通过；额外隔离核对确认改号结果不确定后回读成功，POST 仍仅 1 次。
- `git diff --check` 通过；`check_conventions.py --strict` 被已有 17 项发票 UI 债务阻断，脚本增量代码规则 `check('HEAD')` 为 0 项，未弱化门禁。
- `git_sweep.py --no-fetch` 已执行；仅本地远端快照。既有迁移编号 186 分支冲突仍保留，本次没有迁移、未处理其他代理分支。

## 后续发布

两项修复已获合并推送部署授权并发布到办公室和北京，实际版本 f5269d9d；本报告前文为当时诊断/本地修复阶段。此次未执行历史单业务恢复或改号，见[发布回执](2026-10-13-invoice-sync-production-release.md)。
