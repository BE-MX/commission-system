# 内贸订单按产品明细终止

开发分支为 `codex/domestic-item-termination`；本项交付涵盖代码合并与推送，不包含生产部署。

## 操作与结果

进入内贸订单详情，在目标产品操作区点击「终止明细」，填写原因后确认。只有订单创建人且有 `domestic:write` 权限可以操作。仅生产中或已完工订单的未发货整行可终止；部分发货也拒绝，继续保留原整单终止入口。

终止后只冻结该产品，保留明细数量、成交单价、报工/跳过历史与逐件身份；禁止继续报工、编辑、删除、配路线、跳过、撤销历史与发货。其他明细继续履约。取消行退出有效金额与进度计算，业务订单按原成交明细金额退回客户余额，并写差额账本；生产订单不发生资金变化。重复终止不重复退款。最后一项终止后整单终止；其余状态按有效明细回算。不能通过删除最后有效行绕过结算。

发货候选、未发货金额、订单列表进度排除终止行。订单详情标记原明细金额；单据 Excel 标明已终止，小计为零且出库栏禁止履约；模板明细导出显示明细已终止。

## 验证

- 后端：`python -m pytest tests/test_domestic_item_termination.py tests/test_domestic_item_delete.py tests/test_domestic_delivery.py tests/test_domestic_reporting.py tests/test_domestic_order_details_export.py tests/test_domestic_export.py tests/test_domestic_export_finance.py -q --disable-warnings --maxfail=2`，139 passed（隔离内存 SQLite）。
- 前端：`node --test tests/domesticItemTermination.test.mjs tests/domesticItemDelete.test.mjs tests/domesticOperationPermissions.test.mjs tests/domesticOrderEditing.test.mjs`，28 passed。
- `npm run build` 成功；保留现有打包体积和混合导入警告。
- `python scripts/check_conventions.py`：增量无违规。
- `python scripts/git_sweep.py --no-fetch` 已执行，仅为本地远端引用快照。
- 独立 agent 审查通过。修正了最后有效行删除漏退款、MySQL RR 快照下并发终止/删除导致回算过期的问题：金额、状态、有效行计数使用锁定 current read。

未进行浏览器人工路径验收或隔离 MySQL 并发实测；SQL 锁读契约测试与独立语义审查不能替代 MySQL 压测。没有连接生产库写入，没有 schema 迁移。

测试、构建、约定与巡检日志在集成时保留于主工作目录的 `tmp/domestic-item-termination-evidence/`。
