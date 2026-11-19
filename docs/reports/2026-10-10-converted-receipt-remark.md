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

## 授权生产发布与后检

用户随后明确要求「根据git最新的代码进行生产环境的部署更新」。获取 `origin/main` 后固定完整候选 `e26d5c2398fa22a4c069ebb5a9d4b3e7028e5639`，从办公室受管候选的 `deploy/deploy.bat --live-root D:/commission-system --revision <SHA> --no-pull` 执行准备与正式发布。两个进程 exit 0，最终 `publish-current.json` 为 `succeeded`、范围 `office-and-cloud`、deferred 为空。

- 办公室与北京源码 HEAD 均为候选 SHA；运行中 OpenAPI 均包含 `PATCH /api/receipts/{identity}/remark` 与 `PATCH /api/invoice/invoices/{invoice_id}/remark`。部署后 41 项只读检查的所有必需项通过，后端、共享数据库、隧道及两主域鉴权可达；6 项非必需结果记录为原停用状态或未纳管探针，未将其计作全部运行。
- 两主域的前端制品均为 `445546e20b6e0a84690754843a7675fe822fe892c713cbad03f99650e7a453e3`；公网 index、InvoiceManage-BECaCqJB.js、共享 ReceiptPurposeCorrection-HNQdBXAJ.js 的 SHA256 与发布清单一致。实际公网 JS 包含「编辑备注」「保存备注」和订单页备注互斥字段。
- `pm.leshine.work` 与 `media.leshine.cloud` 制品无需变更，激活及公网 index 摘要核验通过。办公室静态站、北京色块服务与已登记出库制品也完成发布流程；出库调度恢复并核验原 active/enabled 状态。邮件 Worker 制品核验到本候选，保留原停用状态，未擅自启用发信。
- Schema 保持 `180_settlement_funding_amendment`，本次无 DDL。准备阶段两主域各传输 1,178,166 字节；正式阶段复用 staging，成功回执的 transfer_bytes 为 0。统一入口的 PM/Pantone 基础数据步骤均报告已有记录并跳过。
- 原有主目录未提交内容保留；发布回执、完整日志、OpenAPI 与公网摘要证据存放 `tmp/converted-receipt-remark-delivery/`，服务器保留原部署备份及恢复材料。本次只读后检未修改真实订单或回款，实际业务备注由用户正常编辑保存验收。

最新 Git 应用代码与备注入口已上线。小程序审核、平板 APK、尚未登记的站点与独立服务不在统一入口本次应用发布范围内。
