# 订单发票快递渠道与付款校验

日期：2026-11-04。分支 `codex/express-9610`，工作区 `D:/MyProgram/commission-system-codex-express-9610`，基点 `679d9888`。用户已授权本批提交、合并 main 与推送 origin；交付分支 `codex/express-9610-delivery` 从最新 origin/main 整合本次差异，保留本地 main 原有 19 个未推送提交与未提交内容。本批不部署。

## 行为

- 渠道选项：DHL普货、FEDEX普货、DHL9610、FEDEX9610、顺丰、其他快递。主编辑器与旧版抽屉共享选项；现有单选组支持自动换行。
- 业务保存必须满足：付款方式包含「便捷发货」当且仅当渠道包含 `9610`。前端给出具体修改提示，后端保存入口重复校验并返回 HTTP 400；不自动替用户更换付款方式或渠道。
- 覆盖新建、编辑、保存并同步、截图导入和关联业务保存；仅改明细分组的接口不改变上述业务字段。新旧路线均受保护。
- 存量 DHL/FEDEX 打开编辑回显为对应普货，保持初始表单干净，下次业务保存采用新值；不批量更新历史订单。旧单便捷发货与普货不匹配时须纠正后再保存。
- 整单 Excel 粘贴区分普货与 9610，支持联邦别名。本地订单补齐付款字段的命令传递、持久化和返回；历史空付款命令保持既有幂等摘要，非空付款参与幂等判定。
- 复用现有数据库字段，无表结构迁移，无生产库或外部系统写入。

## 验证

- `node --experimental-vm-modules --test tests/invoiceCustomerRemark.test.mjs tests/invoiceSettlement.test.mjs tests/invoiceWholeOrderPaste.test.mjs tests/invoiceZeroPrice.test.mjs`：137 项通过。执行真实编辑器 composable，覆盖双向错误的新建/编辑/保存并同步拦截、修改后成功提交、旧值回显及干净状态；选项与付款方式组合矩阵、粘贴识别、金额相关回归通过。
- 后端 `pytest tests/test_invoice_payment_channel.py tests/test_invoice_commerce.py tests/test_invoice_linked_sync.py tests/test_invoice_paste_import.py -q --tb=short`：112 项通过。使用内存 SQLite；运行时数据库地址设为 `127.0.0.1:1` 哨兵，未复制 `.env`。覆盖非法组合写入前拒绝、400 提示、合法组合持久化、失败保留原订单、本地转换及旧幂等回放。
- `npm run build`：通过。存在既有 bundle 体积及 auth 模块静态/动态导入提示；构建生成的无关导航目录差异已还原。
- `python scripts/check_conventions.py` 与 `git diff --check`：通过。现有大文件保持原职责，未引入无关拆分。
- 独立 agent 两轮审查发现并修复本地付款字段丢失及新增字段影响旧幂等摘要问题，最终复查无剩余必修问题。
- `python scripts/git_sweep.py --no-fetch`：完成，仅本地快照；其他任务的未提交、未推送内容保留。

## 扩展回归限制

另运行 `test_invoice_module.py`、`test_invoice_receipt_save_validation.py`、`test_invoice_linked_sync.py`、`test_invoice_paste_import.py` 共 91 项：86 项通过，5 项旧测试失败。失败均为旧夹具将 `InvoiceCreate` 默认 `inspection_requirement=None` 显式传给 `InvoiceUpdate`，被现有「请选择检验要求」校验拒绝，尚未进入本次修改的 service 保存逻辑；相关 schema 与旧夹具在本次未变更。具体为 `test_okki_flags_stored_and_null_recomputes_on_update`、`test_reducing_total_checks_existing_draft_even_when_omitted`（两个参数）、`test_edit_rejects_new_excess_amount_and_retains_original`、`test_existing_excess_draft_can_be_corrected_without_changing_order`。未借本任务修改无关检验要求行为或弱化测试。

未进行生产浏览器写单验收。关键保存路径通过真实 composable 与隔离 SQLite 验证。
