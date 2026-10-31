# 核验目录与只读历史导入验证

本轮实现稳定目录来源映射与不可变历史证据归档，不把归档当成业务期初。分支codex/ark-local-commerce，基点d9266945，未提交或发布。

## 验证结果

- `backend/.venv/Scripts/python.exe -m pytest tests/test_commerce_migration.py -q --tb=short`：21 passed，3.82秒。包括只读预览、原子拒绝、同批/跨批重放、在线改名不覆盖、来源租户隔离、权限403、游标、原始JSON保留、北京时间零点边界及写入阶段二次核验。
- 隔离MySQL8.4.6完整真实Alembic链至188：13 passed，125.37秒。保留旧订单/行/售后/媒体/客户，并在真实外键结构完成原生资金、检验、出库和隔离退货。两个旧RR视图的并发导入返回相同ID；大小写不同的来源与租户分别保留；本地编码规格冲突和跨批来源产品拆分整批拒绝。
- 实际查询7个来源列均为utf8mb4_bin；导入前后StockLedger、FinanceEvent、InvoiceCommerceEvent数量完全不变。JSON回读完整保留空白区分字段名及值。
- 独立只读审查发现并关闭来源排序规则、外部产品跨批拆分和JSON字段名自动去空白三处问题；修复后无剩余阻塞。严格约定、diff检查通过，前端构建22.34秒/121导航通过（既有大chunk提示）。

本轮证据：`tmp/local-migration-chain/ark_chain_test_27f2ee198982493c/result.json`，nonce `synthetic-chain-535f70c18af74591bc61ecb309a12f8d`。schema/writer删除均实际读回true，日志`tmp/commerce-migration-chain-188.log`。迁移测试只连接127.0.0.1:33079，不连接生产或启动外发worker。

## 当前边界

archives只保留order/payment/outbound/inspection/production/material/commission核验快照；不会生成Invoice、Receipt、StockLedger或正提成。catalog复用本地产品/SKU，永久保存来源命名空间，禁止覆盖在线维护。核验说明是导入依据，不是模拟生产批准。

未结订单全合同、历史已发货应用、付款已用额度、已付提成负调整、生产/半成品责任以及库存/资金期初仍须专门承接和联测。R18及整个切换目标尚未完成；不以本报告宣称分支可上线。
