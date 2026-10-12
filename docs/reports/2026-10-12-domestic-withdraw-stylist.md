# 内贸审核撤回与发型师分析验收

2026-10-12，本地验收完成。分支 `codex/domestic-withdraw-stylist`，worktree `C:/Users/windb/.codex/worktrees/domestic-withdraw-stylist/commission-system`。亮哥已授权本次范围提交、合并main及推送origin/main；生产发布尚未授权，未执行生产迁移或写入验收数据。

## 完成行为

- 本人待审价格订单显示“撤回申请”，撤回退回草稿，可修改价格/明细再提交。已完成审批不能撤回。审核和撤回共用订单行锁，且绑定页面所见审核轮次；旧页面不能审核、驳回或撤回新一轮报价。
- 本人待审充值/余额与等级调整申请显示“撤回申请”，撤回不动余额、等级或账本。修改可沿用原凭证或替换文件，重新提交生成新申请并关联原撤回记录；原金额/说明/凭证保留。同一撤回申请只生成一个替代申请，重放不重复落账或通知。
- “发型师分析”按“做发型”有效报工的北京时间统计，含发型师排名、件数/明细/订单/次数/天数、对照件数、日/月趋势、型号与历史规格、属性分布、发型师×属性热力图、原始报工证据。分批/多人工作量分别归属实际报工人；明细跨人可能重叠。
- 沿用当前经营台客户权限与已应用条件，无客户生产单仍需两项全量权限及完整范围；不计撤销报工、非正数量、软删或无效订单。来源变化使原快照下钻返回409。修正行动面板的fragment显隐，其他标签页不会混入行动内容。

## 验证

- 后端受影响13套隔离SQLite回归：567 passed、1 skipped（原条件跳过，既有SQLAlchemy弃用警告）；新增旧提交幂等键/轮次回归及审核事件指纹后，决策与撤回相关4套68 passed。补齐普通充值权限重提调整的HTTP覆盖及上传前状态校验后，最终新增两套10 passed。以上集合重叠，不累加。
- 新测试：`backend/tests/test_domestic_withdraw.py`、`test_domestic_stylist_analysis.py`。覆盖本人权限、已审拒绝、资金与原申请不变、重放、新申请单次入账、客户归属改变、旧审核/撤回/提交请求、HTTP409、北京时间跨日、撤销、同明细多人去重、生产双权限、远程排序与来源变更。
- 迁移184：离线MySQL DDL编译、证据不删除及本分支唯一head测试通过。没有对共享生产库执行迁移；未完成真实隔离MySQL升级演练，该检查应在生产发布前完成。
- Node受影响4套25 passed，含发型师分组去重和证据、决策权限/查询门禁、订单编辑与审核角标。前端`npm run build`通过，保留现有混合导入与大chunk警告。
- 原Vue页面的Chrome真实浏览器隔离验收：1440px、390px；全部API截获，数据由后端内存SQLite事实生成。验证申请人按钮、撤回→弹窗修改650→重新提交、价格撤回携带版本→编辑草稿、分析总量5件/1明细/2次、两位发型师热力图独立列、选择单人2件、报工下钻与订单号排序。页面运行错误0，无未覆盖业务请求，页面无整体横向溢出；宽表在组件内滚动。采用非北京时间浏览器时区及减少动态偏好。
- `python scripts/check_conventions.py`和`git diff --check`通过。独立agent审查发现并修复旧轮次审批ABA、热力图横轴及排序白名单问题，复审无阻塞缺陷。`python scripts/git_sweep.py --no-fetch`完成，仅本地远端快照。

复跑浏览器（项目根目录）：

```powershell
python C:/Users/windb/.agents/skills/webapp-testing/scripts/with_server.py --server "npm --prefix frontend run dev -- --host 127.0.0.1 --port 3087 --strictPort" --port 3087 -- python frontend/tests/domesticWorkflows.browser.py
```

验收截图保存在本worktree的`tmp/domestic-workflows-browser/`：`stylist-1440.png`、`stylist-390.png`、`withdraw-edit-1440.png`、`withdraw-edit-390.png`。界面沿用DESIGN.md令牌、共享反馈、GlassButton和DetailDrawer；无新增装饰动效，图表沿用180ms并尊重减少动态偏好。

## 发布约束

迁移 `184_domestic_request_withdraw`新增撤回状态、撤回时间、新申请关联和订单审核轮次。本分支父revision为182；合并时重新核对已发布迁移图（所有分支已有183，故本次选择184），不可制造多head。发布须走统一入口，协调全部内贸审核后端写实例与主站前端切换；旧客户端缺轮次的审核请求会被新后端拒绝，须刷新后核对新报价。生产发布与共享库迁移需另有明确授权。
