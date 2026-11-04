# 客户跟进总览、已提交编辑与潜在客户筛选

日期：2026-11-04。分支 `codex/followup-overview`，工作区 `D:/MyProgram/commission-system-codex-followup-overview`，基点 `679d9888`。本批已获提交、合并 main 和推送 origin 授权，进入 Git 交付；基于最新远端 main（含内贸参考图粘贴上传）整合本批差异，不推送本地 main 原有 21 个提交，未部署。新增迁移 `249_followup_revisions`，仅在本任务独立测试 MySQL 上执行；未修改生产库或业务数据。

## 最终行为

- 全部范围用户默认进入「管理总览」，普通业务员仍按原可见范围读取；可按录入人、客户/内容、日期筛选，并查看单条完整原文、截图及客户时间线。
- 业务员有 write 时只能修改本人已提交记录；super_admin 可修改全部。read_all、普通管理员或跟进配置权限不额外授予编辑他人记录权。编辑入口在「我的记录」、总览详情及客户时间线。
- 支持修改原文、日期、沟通方式、摘要、客户变化、要点/异常/意见、截图和下次计划；客户、原作者、原来源和确认时间保持不变。修改原因必填。
- 每次修改追加不可变历史：修改人、北京时间、版本、原因、记录及关联待办前后快照。移除的截图归档保留，可从修改历史鉴权预览。
- `version` 冲突返回 409；前端保留输入并要求重新载入。保存结果不确定时冻结输入，以同一个 request_id 和原 payload 重试；相同请求不会生成第二条修改历史。
- 新增「仅显示潜在客户」复选框（默认不勾选）。待办、异常意见、我的记录、总览、录入人候选、待办计数及草稿提示均按客户当前 `lifecycle_status=潜在` 过滤。原权限和其他条件继续生效。切换时清空旧范围、回第一页，旧请求不能带回非潜在数据。

## 待办与提醒

- 未完成计划原位更新，保持现负责人；未改变计划日期时保留手动顺延。清空下次日期取消待办。已结束任务不重开；明确新增/改变日期时另建新版计划。
- 条目 ID、转交后的负责人、已产生的处理结果保留。移除未处理条目标记 withdrawn 并取消未完成任务；处理中/已处理条目不能删除或切换仅记录，可以更正描述。「仅记录」重新启用只产生一张新的有效任务，旧取消记录保留。
- 原记录已关闭的回访、其他完成任务和处理事实不撤销，不重跑原确认流程。
- 草稿绑定与已提交编辑使用同一按精确主键排序的截图锁，锁后刷新并核验归属。真实 MySQL 测试发现原 OR 查询会产生二级索引 gap deadlock，已改成精确 PK 逐行锁并复验。
- 紧急提醒发送前重读并领取五分钟租约。编辑取消/更新未领取消息，发送时再次检查当前条目状态和内容；已发送或已领取的在途通知不能撤回。失败会释放租约，崩溃后的过期租约可重试；钉钉确认结果丢失仍存在既有的重复投递可能。

## 验证结果

- 内存 SQLite：全部 `tests/test_domestic_followup_*.py`，**189 passed**。覆盖权限、历史、重放、过期版本、计划与条目联动、转交/已处理结果、截图归档与盗用拒绝、字典停用后更正、潜在状态动态变更、发送前取消/刷新，以及非东八区与北京时间跨日。
- 独立 MySQL 8.0.46：`tests/portal_mysql/test_mysql_domestic_followup_edits.py`，**3 passed**。实际执行迁移 249，确认有历史时 downgrade 阻断；观察真实 InnoDB 锁等待，验证 RR 过期版本冲突、草稿/编辑双向竞争同一截图。新随机端口、新 datadir，仅回环连接；`tmp/mysql-followup-edit-04/mysql.log` 确认 Shutdown complete。
- 前端：`npm run test:domestic-followup`，**28 passed**；包含角色入口、表单映射、修改原因、409保留输入、不确定重试、迟到请求、跨页筛选及历史差异展示。构建通过（现有 vendor 体积与 auth 动静态引用警告保留）。
- 独立只读审查通过；修复了上传失败无反馈、历史字典值误校验、附件绑定竞争和发送准备后编辑的并发问题。
- 本地真实 Vue 组件模拟数据交互：管理员修改字段/移除截图并成功保存，列表刷新；历史显示人、原因与前后差异，旧截图可预览。处理中的条目删除禁用。业务员本人可改；有read_all但非超管不能改别人。409保留文本和原因、禁止覆盖，确认放弃后重载最新版本。
- 潜在筛选交互：管理总览24→8、业务员我的记录12→4、待办6→2、异常6→2、约定/异常计数3→1；切换页签保留勾选，取消恢复。
- 390×844 子视口发现并修复编辑弹窗横向溢出：限制视口内宽高、正文独立纵向滚动、头尾保留。复验标题、字段左右边界、保存/取消无需横向滚动，能滚至修改原因并实际输入；取消经过放弃确认后正常关闭。
- 约定检查、diff检查和本地快照Git巡检执行；未操作主目录或其他代理的成果。

浏览器验收使用本地 fixture，不能代替生产账号验收；未测试真实文件上传。原有列表/时间线 N+1 查询仍在。验证日志与可重建页面在 `tmp/` / `frontend/tmp/followup-overview/`。临时测试实例均已停止，日志确认 Shutdown complete；数据目录清理被工具自动审批拒绝（仅返回 blocked by policy），目录与日志暂时保留，未绕过拦截。

## 重现独立 MySQL 检查

从 backend 运行（不加载 backend/.env，业务数据库配置指向本地哨兵）：

```powershell
D:/MyProgram/commission-system/backend/.venv/Scripts/python.exe -B -m pytest tests/portal_mysql/test_mysql_domestic_followup_edits.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short --portal-mysqld=C:/Users/windb/.codex/worktrees/outbound-replenishment-reservation/commission-system/.deploy_state/tools/mysql/mysql-8.0.46-winx64/bin/mysqld.exe --portal-mysql-workspace=D:/MyProgram/commission-system-codex-followup-overview/tmp/mysql-followup-edit-new
```

工作目录必须是未存在的新目录，不能接入既有或共享数据库。生产迁移只能随正式授权的发布入口统一执行。
