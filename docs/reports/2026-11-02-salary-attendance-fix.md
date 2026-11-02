# 工资工作台按钮遮挡与考勤同步错误

状态：本地修复并验证；用户已授权本批提交、合并 main 与推送 origin，最终引用以 Git 回读为准。未部署，未修改生产业务数据。

工作区：`D:/MyProgram/commission-system-codex-salary-attendance`，分支 `codex/salary-attendance`，基点 `b817650a`。主目录已有其他任务的未提交成果，本次未修改。

## 根因与修复

- 工资明细与考勤标签内的 FilterBar 继承全局 sticky 筛选卡样式，滚动时盖住后续动作。两个 pane 复用 table-card 的普通流筛选区和独立 action-bar，局部去掉多余卡片外观。
- 办公室生产日志确认 `POST /api/salary/periods/3/attendance/sync` 返回 500：假期类型请求缺少 `op_userid`，钉钉返回错误 40，AttendanceSourceError 未被路由捕获。操作人现从当前有效 ArkUser 的钉钉绑定取得，缺绑定明确 400；类型调用失败返回 502，不进入落库。
- 真实只读调用确认 `vacation_source=all` 返回 6 类假期；请假明细 page size=50 返回 200003，20 正常并返回 has_more。已修正分页，并保留整批部分页失败不生效的保护。
- 年假余额实测返回 `result.leave_quotas`，原请求参数和响应形状均不符。补齐操作者、查询名单和分页参数；仅接受当前年度批次、本年度有效单条天数额度。小时制、多条、未完整分页、过期、未生效或坏值不推算；原有人工值保护不变。
- 独立审查发现：未知请假类型会被写成零并消除待人工状态。已加回归修复，未知类型或无效时长/单位的自动列置 NULL，持续进入原异常清单、不能判全勤；人工值保持，摘要和界面点名待核对人员。

## 验证

- 原有考勤路由/请假取数基线 30 项通过；新增操作人/异常响应/分页回归先出现 5 项预期失败；未知请假保护先出现 7 项预期失败（人工保护既有项通过），再实现修复。
- 薪资模块完整隔离回归：375 passed。命令为项目 `.venv` 的 `python -m pytest` 加全部 `tests/test_salary_*.py -q --tb=short`。工作区无 `.env`，全局数据库地址强制 `127.0.0.1:1`；测试使用内存 SQLite，没有生产写入。
- 前端资源/竞态回归：`node --experimental-vm-modules --test tests/salaryCollectionResources.test.mjs`，9 passed。
- 真实只读候选取数抽样：批次 3 为 2026-10，当前操作者一人考勤成功、1 条请假明细、0 取数失败、0 未知类型，年假余额成功解析。数据库读取使用 `SET TRANSACTION READ ONLY`；外部只调用钉钉查询接口，没有调用生产同步写入端点。此结果不等同于生产全员落库验收。
- 独立审查复核通过，并额外跑 22 项相关回归；未发现剩余阻断。
- 真实浏览器使用本地 Vite 与模拟工资接口验证滚动后的查询、重置、同步、工资明细切换及 390px 窄屏换行。截图位于 `C:/Users/windb/.codex/visualizations/2026/11/02/01a19b38-ce4b-74e2-8c20-a08cba3c7c65/salary-attendance/`（`attendance-scrolled.jpg`、`attendance-narrow.jpg`）。
- 前端构建、增量约定与 diff 空白检查通过；Git 巡检 `--no-fetch` 只代表本地远端引用快照。

## 恢复材料与清理限制

模拟预览服务 41789 已停止。截图目录 `recovery/` 保留预览源码；本工作区 `frontend/node_modules` 是指向主目录已安装依赖的 Junction。`frontend/tmp/salary-preview/` 仅为被忽略的模拟预览材料，不进入交付 diff；自动审批审查拒绝了该临时目录的删除命令，仅返回 `blocked by policy`，未绕过。前端构建日志保留于 `tmp/salary-final-build.log`。

参考接口：[假期类型](https://developer.alibaba.com/docs/api.htm?apiId=43093)、[假期额度](https://developer.alibaba.com/docs/api.htm?apiId=43050)。日志摘录不收录 access_token、员工账号或原始薪资/请假值。
