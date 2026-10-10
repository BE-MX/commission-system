# 订单编辑页已生成回款的备注入口补漏

用户截图位于新版订单编辑页「本次回款 / 原回款已生成」区域。之前的 `f3b1a685` 增加了订单与回款详情页的独立备注接口和入口，遗漏了这里：`ReceiptFields` 的 `readonly` 将金额、日期与备注一起冻结。

## 生产只读核验

2026-10-10 通过办公室 SSH `office-prod` 与北京 `ubuntu@154.8.205.162` 检查应用源码和运行中 OpenAPI：两端源码 checkout HEAD 均为 `60e408d4e1538a4e2613cb85bad685e76f80584b`，没有 `backend/app/receipt/remark_service.py`，运行中 OpenAPI 均没有订单或回款的独立 remark 路由。源码 HEAD 仅说明 checkout，不替代运行中路由核验。未写生产业务数据、未发布或重启服务。

## 修复行为

- 新版库存单、预售单以及旧版库存单的已生成有效回款区域，使用现有 `DocumentRemarkEditor` 独立编辑、保存或清空备注，复用 `PATCH /api/receipts/{id}/remark`。金额和日期仍只读，既有 `receipt:write` 权限控制入口。
- 保存返回完整回款记录并更新冻结的 `receipt_draft`，包括 remark 与 version；不覆盖未保存的订单 header/items。旧版本资金汇总响应不能回退已保存的备注。
- 备注编辑或保存期间阻止截图编辑、资金操作和订单保存；订单保存、同步或关联任务读取期间反向锁住该入口。重挂载和卸载解除编辑标记。
- 备注接口沿用已同步记录只保存在方舟、不自动重推小满的行为，无表结构改动。

## 验证

- Node 回归：`node --experimental-vm-modules --test tests/documentRemark.test.mjs tests/invoiceReceiptCorrection.test.mjs tests/invoiceReceiptPayment.test.mjs tests/invoiceCustomerRemark.test.mjs`，37 passed，覆盖双向互斥、迟到版本、权限变化与未保存订单备注保留。
- Chrome + 实际 Vue 组件（业务 API 全拦截）：`convertedReceiptRemark.browser.py` 对现代和 legacy 各验证编辑、清空、409 保留输入、取消、权限撤销、反向订单锁、表单版本更新及 390px 备注区域；各 3 次 mock PATCH，pageerror 为 0。这些证据不等同生产真实保存验收。截图上传区域窄屏溢出是既有问题，本次未改上传组件。
- `npm run build` 成功，3491 modules；现有 auth 静态/动态混合导入与大 chunk 提示保留。
- `python scripts/check_conventions.py` 与 `git diff --check` 成功。
- 独立 agent 审查并修复旧汇总响应回退、在途订单保存反向锁后复核通过。

生产需要发布包含前次接口与本次入口的前后端。合并推送授权已存在；生产发布授权尚未取得，待用户明确授权后走 `deploy/deploy.bat`，发布完成需检查两端 OpenAPI 与真实静态版本，用户再正常保存该业务备注。
