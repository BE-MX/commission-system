# 状态标签竖排修复

亮哥反馈订单发票列表的“已同步”“取消处理中”被逐字排成竖列。本次在独立分支 `codex/status-badge-nowrap` 修复并验证；最初交付为本地修复，后续授权的合并与发布状态见文末。

## 原因与修改

| Before | After | Why |
| --- | --- | --- |
| 共享 StatusBadge 设置 `white-space: normal; overflow-wrap: anywhere` | 根标签使用 `inline-block; white-space: nowrap`，自有文字span省略，并为可关闭标签保留按钮空间 | 任意换行会把中文压成一字一行，并撑高整个表格行；单行超长值显示省略号，关闭按钮可点击 |
| 发票类型76px、状态/同步84px | 类型110px、状态160px、同步110px；状态与同步启用 overflow tooltip | 列宽包含单元格和标签内边距，最长已登记状态“同步结果待核对”完整显示，未知值可查看全文 |
| 设计文档未约束标签换行 | DESIGN.md 明确单行和列宽要求 | 避免后续通用响应式样式再次改变状态标签阅读方式 |

保留状态字典、语义颜色、事件、属性转发和业务数据。未覆盖 Element Plus 内部样式，也未提高 UI 债务基线。

## 实际验证

- `python tests/statusBadgeLayout.py`：在实际 Chrome、Element Plus、主站样式和真实 StatusBadge 下验证，桌面1280×720及390×844通过；无页面异常。
- 修复前84px窄列中，“已同步”标签高度60px，“取消处理中”96px；修复后均24px。“同步结果待核对”在160px状态列完整显示，未知长代码仍可通过 tooltip 查看全文。
- `node --test tests/sharedUi.test.mjs tests/invoiceLayout.test.mjs`：10/10通过，覆盖字典/未知值/close转发以及发票布局约束。
- 独立审查发现初版根标签overflow裁掉窄容器的关闭按钮，已改为仅截断自有文字span；浏览器新增70px窄可关闭标签的按钮几何和实际鼠标关闭断言，通过。
- 独立代理定向复核修复后的实际浏览器：1280px与390px分别重载、点击关闭、等待离场transition后原标签移除，均通过；关闭按钮始终位于70px标签内。
- `npm run build`：生产构建通过，113项导航；既有大chunk提示仍保留。
- `python scripts/check_conventions.py --strict`、`python scripts/audit_frontend_ui.py --baseline-ref HEAD`、`git diff --check`：通过。
- `python scripts/git_sweep.py --no-fetch`：已运行，本地快照，不代表已fetch最新远端。

浏览器回归入口：`frontend/tests/fixtures/status-badge/`。执行方式见该目录 README。
修复前后几何指标与桌面/窄屏截图保留在 `tmp/status-badge-before/`、`tmp/status-badge-after/`。

## 扩展修复：其他页面

按亮哥“其他页面也要修复”的补充要求，检查主站 `frontend/src` 所有 Vue 状态列，并调整70个页面/组件中的121个列宽。发票动态列的3个宽度由控制器单独调整，不计入上述静态列修改数。页面变更仅涉及列宽；共享组件修复单行、完整文字提示和关闭按钮，普通表格单元格允许多个标签在标签之间换行。没有修改业务状态、权限、接口或持久数据。

### 列宽与可读性

| 代表场景 | 最小列宽 | 文案依据 |
| --- | --- | --- |
| 售后审批 | 200px | 待主管确认取证豁免 |
| 工资期 | 140px | 考勤已同步、社保已导入 |
| 邮件任务 | 160px | 结果未知待核对 |
| 回款 | 160px | 远端删除已核实 |
| 物流 | 120px | 海关扣留 |
| 订单风险、情报可信度 | 120px | 周期异常、无法核实 |
| 产品色型（两列） | 190px | 巴拉雅奇 Balayage |

新增 `npm run audit:status-badges`：Vue AST检查185处含标签的列声明，排除1处展开控制列但继续检查内部子表，单独核对唯一发票动态模板。宽度规则包含单元格和标签边距，最低100px，并根据实际文案增加；同时检查固定宽度和最大/最小宽度矛盾。8处动态列约束从真实领域字典或页面内部显示映射读取，不执行业务setup。

独立审查发现静态模板中的函数调用无法直接推断文案，补齐物流、风险、可信度、两处色型共5个遗漏的列宽，并把这些真实字典/映射接入审计和浏览器回归。独立终审回放5个原窄宽全部被新约束拒绝，当前5列通过。其余动态文案仍需要结合来源定向检查，静态脚本不能证明所有服务端返回值均完整显示；超长未知值保持单行省略并保留全文提示。

### 共享组件边界

- 全文title来自实际渲染文字，保留数值0及调用方显式title（包括空值/null）。独立浏览器反例证明仅用组件onUpdated会漏掉ElTag内部插槽后代的更新；改为观察自有文字节点并在卸载时断开。复核6/6 Observer释放，离场DOM再变化没有回调。
- 仅文字span省略，70px可关闭标签仍能实际点击关闭；多个状态标签在标签之间换行。真实操作列仍保持flex换行。
- DESIGN.md、交接文档与回归fixture已同步；UI债务基线不增加。

### 最终验证与范围

- 实际Chrome桌面1280×720、窄屏390×844通过：72个标签，包含7类真实字典/映射的48个状态。单标签高22.5–24px，选取的登记状态无裁切，未知值全文tooltip、动态title、多标签、操作列及关闭按钮断言通过；页面异常0。
- 定向Node `sharedUi`、`invoiceLayout`、`statusBadgeColumns`：17/17通过，包含窄列反例、长状态、嵌套表、最大宽度、真实物流字典及安全读取页面显示映射。
- 全量Node快照1190项：1184通过、6失败。失败均为既有 `loginMapMotion` Canvas mock缺少 `ctx.save()`；上一轮隔离HEAD有相同6失败，本次源码和该测试未变。最终字典补漏与2项新增测试另由上述定向、浏览器和构建验证覆盖。
- 最终生产构建通过，113项导航；既有大chunk提示仍存在。严格约定、UI门禁、状态列审计、diff检查通过；Git巡检 `--no-fetch` 为本地快照。
- 新证据保留在 `tmp/status-badge-all-pages/`（截图/metrics）、`tmp/status-badge-audit/`（完整列账本/改动明细）、`tmp/status-badge-all-pages-*.log`。浏览器使用隔离数据，没有逐页登录生产业务验收或生产写入。

## 后续授权：合并推送部署

亮哥随后明确授权“合并推送部署”。应用提交 `326f7e0bf55dd6b7d1ee3a7675f55bea0d3c4a94` 已从任务分支在主worktree快进合入main并推送origin/main。合并后的生产构建通过（30.20s，113项导航），严格约定使用 `--base e5928845` 覆盖本次提交，diff检查通过。原有6项登录动画测试基线失败仍按上文说明。

主目录其他任务的15个文件SHA256未变；重叠的handoff先独立stash保存，合并后恢复，排除本次新增交接条目后与原文件完整内容一致。备份、恢复stash引用、合并验证及原浏览器证据已保存于主目录 `.deploy_state/status-badge-delivery/`。

**部署未完成，尚未触发生产发布。** 当前 `office-prod` 使用本机 `127.0.0.1:2223` 转发到办公室SSH；端口由GameViewer监听，但Windows OpenSSH与Git SSH均在banner交换阶段超时，未进入身份认证或远端部署入口。未重启GameViewer、修改隧道、绕过主机密钥校验或改用非项目发布入口。

最小解锁动作：恢复GameViewer的 `127.0.0.1:2223 → 办公室22` 转发。已保留固定候选的远端入口脚本；连接恢复后先执行同SHA `--prepare-only`，成功才正式发布并检查版本/服务/静态资源。任务工作树暂留，本记录不代表生产已更新。
