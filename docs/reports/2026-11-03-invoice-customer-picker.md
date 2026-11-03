# 发票客户选择分组与有效性核对

日期：2026-11-03。工作区：`D:/MyProgram/commission-system-codex-customer-picker`，分支：`codex/customer-picker`，基点：`a8707d8f`。用户已授权本批提交、合并 main 与推送 origin；不部署。最终交付引用以 Git 回读为准。

## 问题与结果

客户与联系人原先平铺为独立选项；两份同名客户各有一个联系人时显示4项，容易误认为4个客户。小满已不存在的客户仍可能保留在只读镜像中，选中后推单才失败。

新旧订单表单共用 `InvoiceCustomerPicker.vue`：

- 按公司ID分组，显示公司名称、国家、客户编号；组内提供客户选择入口及缩进的联系人入口，完整标签仍保留所属公司以供选中回显及键盘辨识。
- 不按同名或时间后缀合并/删除数据；同名不同编号保持独立，分页中的同一公司及重复选项按身份归组去重。底部显示当前已加载的独立客户、联系人数量。
- 只有用户选择时，才核对这一个小满客户。明确不存在时直接隐藏本次选择器会话中的整组客户及其联系人，底部仅统计可见项；重新搜索或分页返回同ID不会回流；网络/鉴权错误不标记删除，保留当前选择并支持重新选择重试。私海实时归属变化单独提示。搜索仍使用现有分页，不逐次按键远程核对所有候选。
- 正常选择联系人继续填入该联系人的姓名、电话、邮箱；核对通过时使用小满当前客户名称。编辑已存发票不自动改客户。关闭、重置、私海/业务员/订单上下文变化后，迟到结果失效。

新端点 `GET /api/invoice/customers/availability` 的权限、范围与响应见 `docs/api-reference.md`。不新增数据表，不修改业务客户、发票或镜像；端点仅允许按现有机制刷新小满鉴权缓存。

## 验证证据

- 前端：`node --experimental-vm-modules --test frontend/tests/invoiceCustomerSearch.test.mjs frontend/tests/invoiceCustomerSelection.test.mjs frontend/tests/invoiceCustomerPicker.test.mjs frontend/tests/invoiceCustomerRemark.test.mjs frontend/tests/invoiceLayout.test.mjs`，115项通过。包括真实组件挂载、失效组隐藏、原选择保留、失败重试、身份不匹配、切换/关闭后迟到响应等；编辑器原有联系人、价格、备注和保存行为回归通过。
- 后端：客户有效性、客户选择、客户过滤、手动同步4个文件，45项通过；2项既有建单用例单独排除，原因见下文。新增测试覆盖严格404形态、HTTP错误/鉴权/超时/身份不完整不误判删除、私海与权限、归属变化、单次token刷新上限和失败后镜像不变。使用内存SQLite，工作区不复制 `.env`，测试环境数据库指向 `127.0.0.1:9` 哨兵地址。
- `npm run build` 成功，139条导航；保留原有 auth 静态/动态导入及大包提示。严格增量约定检查与 `git diff --check` 通过，Git巡检仅本地引用快照。
- 构建和测试日志：工作区 `tmp/customer-picker/build.log`、`frontend-tests.log`、`backend-tests.log`。初始新增行为回归在实现前失败，完成后通过。
- 独立只读代码审查发现旧抽屉保持挂载时，关闭未取消核对；已通过 `active` 显式接线及同步取消修复，补挂载回归。复审通过，相关10项测试通过。
- 实际浏览器使用隔离夹具 `frontend/tests/invoiceCustomerPickerHarness.html`，axios adapter 拦截全部模拟读请求，不连接业务服务。已验2客户/2联系人分组、有效联系人选择、失效客户与联系人整组隐藏、可见数量更新、重新搜索不回流、原选择保留、网络失败后重试、键盘方向/Enter/Escape、慢查询后重置、375px窄屏无横向溢出。
- 截图目录：`C:/Users/windb/.codex/visualizations/2026/11/03/01a19f4b-d4f0-72d1-b45a-a5972d184015/customer-picker/`，包含 `groups.jpg`、`missing-hidden.jpg`、`network.jpg`、`narrow-375.jpg`（`missing.jpg`为此前禁用展示方案的历史截图）。

## 已知限制

- `test_invoice_customer_filters.py` 的 `test_create_endpoint_duplicate_returns_400`、`test_create_endpoint_race_integrity_returns_400` 预期建单201，实际422。用HEAD原版的 router、okki_client、customer_picker_service 再跑这两项，仍相同失败，确认并非本次变更；未修改或弱化其断言。本任务不扩展为修复旧建单测试。
- 浏览器长会话中曾两次显示通用核对失败；刷新后直接选择失效客户，以及重走“慢核对→重置→等待→选择失效客户”均正确，未稳定复现。原因未确定，不能据此声称无任何运行时风险；本轮没有生产端到端验收。
- 已知失效记录只在当前选择器会话隐藏，关闭重开会重新核对；没有删除镜像、自动合并客户、推送真实订单或更正 `Rina-KC-1103`。
- 收尾自动审批以 `blocked by policy` 拒绝了已核对归属的预览进程停止与构建目录删除操作，未绕过拦截：本次Vite预览 `127.0.0.1:3187`（核对时PID 58076）及工作区 `frontend/dist` 暂时保留；测试日志和截图继续保留。
