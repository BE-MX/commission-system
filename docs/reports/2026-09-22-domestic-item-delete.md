# 内贸订单编辑：删除产品明细

## 问题与修复

订单管理的「编辑订单 → 产品明细」只有编辑按钮，前端 API 模块也没有接入已存在的 `DELETE /api/domestic/items/{item_id}`。本次补齐删除入口，复用现有后端事务、创建人校验、报工/跳过历史保护及余额结算，不修改后端业务逻辑或数据库结构。

- 每条明细提供「删除明细」，要求 `domestic:write`；确认框明确删除立即生效，已提交业务单提示按实际差额退回客户余额。
- 确认和请求期间锁定相关操作，取消不发送删除请求；失败保留明细，错误使用现有 API 拦截器展示。
- 成功后移除该行、通知父列表更新并重新获取详情；后续刷新失败不重新显示已删除行，也不覆盖尚未保存的表头输入。
- 仅创建人可删，订单至少保留一条；已发货、已终止、待审核、已驳回禁止删除。报工和跳过历史由服务端最终校验，撤销后的历史记录同样阻止删除。

## 验证

- `node --test frontend/tests/domesticItemDelete.test.mjs frontend/tests/domesticOrderEditing.test.mjs`：21 项通过。新增组件测试先在原版本复现入口缺失，再验证修复。
- 后端隔离内存 SQLite：`python -m pytest tests/test_domestic_item_delete.py tests/test_domestic_review_flow.py -q --tb=short`：24 项通过。覆盖持久化、总额/件数、草稿不退款、已扣款退款、防重复退款、创建人、最后一行、冻结状态、有效及已撤销报工/跳过历史。
- `npm run build`：通过，保留现有大包及混合导入警告。
- Chrome 真实 Vue/Element Plus 组件，使用隔离 API 响应：桌面及 390px 删除/取消、最后一行禁用、表头未保存内容保留、重开后的明细、弹窗宽度均通过，无页面 JS 错误。此项不是生产环境验收，也不是浏览器直连后端端到端测试。
- 独立代理只读审查通过，未发现阻断缺陷。
- `git diff --check`、`check_conventions.check('HEAD')` 增量规则通过。完整 `python scripts/check_conventions.py` 被 9 项既有 UI 行数基线过期阻断，未调整基线。
- 扩展运行既有 optimizations/reporting/review_flow 三组得到 29 passed / 69 failed。代表失败在建单夹具中把当前正式单当作待审核单，或对非待审核单再次审核，在到达删除断言前失败；本次没有修改这些测试及后端业务代码。为避免依赖过期建单夹具，新增测试直接建立合法持久订单，验证真实删除 service。
- `python scripts/git_sweep.py --no-fetch` 已执行，仅本地远端快照；未清理其他任务。

## 交付状态与证据

开发分支 `codex/domestic-item-delete`，工作目录 `D:/MyProgram/commission-system-codex-domestic-item-delete`。用户已授权合并 main 并推送 origin/main，本轮不部署、不操作生产数据。浏览器检查脚本与截图保留到主目录 `tmp/domestic-item-delete/`，隔离页面归档为该目录的 `frontend-fixture.html`，均为忽略的本地验证材料。
