# 工资批次与工作台资源审查

审查日期：2026-10-02。工作目录：`C:/Users/windb/.codex/worktrees/list-filter-behavior/commission-system`。

## 结论

资源接入和金额/人工值契约已核验；独立读取失败不会把成功的写入误判为失败。审查发现的跨批次锁定确认风险已由主代理修复，并经审查者重新运行同一实际控制器探针确认：批次 1 的确认返回时，已打开批次 2，写入次数为 0。

推进/锁定/解锁现已使用独立 `periodReady` 门禁，读取错误或刷新中禁用；已锁定批次的 `writable=false` 不会误禁合法解锁。考勤截断、批次 60 条和事件 200 条边界已说明。最终相关测试 14/14 通过；本次审查没有剩余已确认的交付问题。

审查只读取业务源码/现有测试；仅本报告为审查者新增文件，没有修改业务代码、测试或生产数据。

## 资源、接口与状态

共享 `salaryClient` 的响应拦截器解包业务信封，调用方正确读取 `res.data`。所有新增读适配器透传 `signal` 和 `suppressToast:true`；失败由各自 `ListPageStatus` 承担反馈。`useAsyncResource.load` 返回布尔值，首次失败不标记成功；后续失败保留上次成功数据；`clear` 中止并隔离旧请求。

| 资源 | 页面/编排器与 API | 真正类型及元数据 | 提交/重试/作用域 |
| --- | --- | --- | --- |
| 工资批次 | `SalaryPeriods.vue` / `useSalaryPeriods` → `listPeriods` → GET `/periods` | 有限数组：后端默认 `limit=60`，上限 200；按月份降序，没有分页 total | `statusFilter` 草稿、`appliedStatus` 提交快照；查询/重置提交，刷新/重试使用已提交状态；首错和旧数据错分开显示；UI 说明最近 60 个符合条件批次 |
| 批次详情 | `SalaryWorkbench.vue` / `useSalaryWorkbench` → `getPeriod` | 单对象：status/version/writable/next_steps/年月/工作日 | 独立错误和重试；错误或加载时 `writable=false`；路由 id 改变清空旧详情并重新加载 |
| 异常清单 | `listAnomalies` → GET `/{id}/anomalies` | 对象：items/by_kind/blocking_count/info_count/ready_to_calculate/payroll_headcount | 独立状态；保留成功清单；只按前置异常计算推进提示；记录级异常分流到明细 |
| 考勤 | `listAttendance` → GET `/{id}/attendance` | 有限对象集合：items/total/pending_manual_count/unbound/truncated；默认 limit 500、上限 2000 | keyword/only_pending 草稿与 `attendanceApplied` 分离；写后刷新不提交新草稿；空表错误在 empty slot，旧行错误在表外；truncated 提示使用姓名筛选缩小范围 |
| 社保导入摘要 | `listImportRows(id,'insurance',{limit:500})` | 有限 items + 全量 total/match_counts/个人 matched/all 合计/truncated | 独立资源；页面只消费摘要，不消费 items；重试用资源保存的批次参数 |
| 公积金导入摘要 | `listImportRows(id,'fund',{limit:500})` | 同上 | 与社保独立，任一失败不覆盖另一项结果 |
| 事件时间线 | `listPeriodEvents` → GET `/{id}/events` | 有限数组，service 默认最新 200 条；含中文 event/status/operator 标签 | 独立错误、加载、空结果、重试；路由变化清空并隔离旧响应；UI 说明最新 200 条 |
| 工资明细 | `useSalaryRecords` → `listRecords(id,{keyword})` | 有限集合：items/total/totals/truncated；service 默认 500，total 为返回行数，totals 为返回集的金额汇总 | keyword/appliedKeyword 分离；切入明细 tab 才拉；路由变化清空；显示 truncated 提示；静默刷新仍显示读取错误 |

后端证据：`backend/app/salary/router.py` 的 periods/imports/attendance/records 端点；`period_service.py:list_periods/list_events`；`attendance_service.py:list_rows`；`calc_service.py:list_records`；`import_persist.py:list_rows`。

## 已核验行为

1. `refreshAll` 的详情、异常、事件、考勤、两类导入都各自 settle；一项失败不会清空其他成功结果，也不会让 Promise.all 因读失败 reject。
2. 工资批次筛选、考勤筛选、明细关键词明确提交；TableTools 刷新、重试、写后刷新继续使用提交快照。
3. 工作日保存成功后，即使批次读取失败，保存提示成立且弹窗关闭；保留的旧批次不会继续暴露 `writable=true`。
4. 考勤人工录入逐字段构建 patch，未修改字段不传；数字 `8` 与字符串 `'8'` 不被误当改动；显式 null 表示清除，0 表示真实零；expected_version 保留。
5. 明细人工改数原样传 `value`，携带 expected_row_version。成功响应原地替换返回行版本，再发静默刷新；读取失败仍返回 true，保留最新写入行，输入框可以结束保存。
6. 路由切换取消旧作用域读取，批次/异常/事件/考勤/社保/公积金立即清空后加载新批次；明细亦监听动态 periodId。成功行写入的旧批次响应不会替换新批次行。
7. 两类导入的 total/match_counts/personal_total_matched/personal_total_all 由独立 SQL GROUP BY / SUM 得到，不以 500 条 items 计算；现有摘要 UI 不需要把它迁为可翻页行表。
8. 金额仅在展示用 `money`；payload、工作日数、请假小时、计数、status_version/row_version 没有套金额格式。null 小时仍为“待录入”，零小时显示真实零。

## 已修复复验：跨批次锁定确认

位置：`frontend/src/views/salary/composables/useSalaryWorkbench.js:261` 的 `doStep`。

本次把固定 periodId 改为路由计算值后，确认框 await 后仍取当前 `periodId.value`、`version.value`。这会将针对旧批次的确认应用到新批次。

实际控制器探针使用真实 Vue reactive/watch、真实 useAsyncResource 和源码转换辅助器，只替换 API/确认框：

```text
批次 1：version=10，year_month=2026-08
doStep({status:'confirmed',endpoint:'confirm'}) → confirmDanger 悬而未决
route.params.id=2 → 新批次加载成功，version=20
旧 confirmDanger resolve
实际写入：confirmPeriod(2,{expected_version:20})
```

已实现：进入 doStep 时捕获批次 id、version、year_month；每次确认 await 返回后核验批次未变且 periodReady，变化则结束动作；后续写入使用捕获的 id/version。stepping 在所有确认前设置，结束或取消释放。现有新增回归还验证同批次确认过程中版本变化仍使用原版本，交给后端冲突检测，不借新版本取得有效写入。

动作区下一步按钮、解锁入口/提交与对应 handler 已接入 periodReady。doUnlock 捕获 id/version/reason，旧作用域成功响应不关闭新批次表单；saveWorkday 同样只结束同批次表单。confirmed 的只读批次仍能依据可靠快照和 admin 权限正常解锁。

审查者修复后复跑同一独立探针：`{startedPeriod:1,currentPeriod:2,writes:[],busy:'',periodReady:true}`。确认旧批次零写入且忙碌状态正常释放。

## 原有边界与未扩大范围事项

- 考勤原有 truncated 提示缺失已补齐；明细已有对应提示。
- 批次默认只列最新 60 条、时间线默认最新 200 条；这两项是有限数组，现有 UI 已明确说明。资源失败恢复已接入；扩展历史访问能力需另外设计 API。
- `doCalculate` 等写入完成后仍可能弹旧批次结果摘要；与明确的锁错新批次相比，这类结果提示作用域问题不构成第二个跨批次写入点。成功写操作本身不会被重复提交。
- 未运行后端写入型测试或触碰生产；本任务改变前端编排，后端 envelope 和聚合范围由源码直接核验。

## 实际验证

在工作目录的 frontend 执行：

```text
node --test tests/salaryCollectionResources.test.mjs
5 passed / 0 failed

node --test tests/salaryCollectionResources.test.mjs tests/useAsyncResource.test.mjs tests/sharedFormats.test.mjs tests/listPageComponents.test.mjs
10 passed / 0 failed

主代理修复确认作用域后，审查者重跑同一组：
node --test tests/salaryCollectionResources.test.mjs tests/useAsyncResource.test.mjs tests/sharedFormats.test.mjs tests/listPageComponents.test.mjs
14 passed / 0 failed（工资专用 9 条，其余共享契约 5 条）
```

补充未落盘控制器探针：

- 考勤原值 personal_leave_hours=4、sick_leave_hours=null、annual_leave_days=8；编辑为 null/0/'8'，真实 payload 为 `{personal_leave_hours:null,sick_leave_hours:0,expected_version:31}`。保存返回成功、editRow 清空，6 个独立读全部失败且错误各自保留，writable=false。
- 上述跨批次锁定修复前复现实际记录 `{id:2,payload:{expected_version:20}}`；修复后复跑同探针得到 `writes:[]`，没有真实网络或数据库写入。

验证边界：现有测试运行实际 composable/shared resource，API 为确定性 fixtures；没有把这些结果宣称为真实浏览器工资页面全流程或生产 API 验证。
