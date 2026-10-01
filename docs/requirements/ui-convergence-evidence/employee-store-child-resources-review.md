# 员工历史与门店人员子集合修复

日期：2026-10-02；工作树 `codex/list-filter-behavior`。本报告按实际资源验收，主列表既有业务未改。

## 已完成资源

| 资源 | 类型 / 查询范围 / 上限 | 实际响应与实现 |
| --- | --- | --- |
| employee.attribute-history | 员工范围完整历史集合；`employee_id`；无分页、无固定截断 | `GET /employee/attribute/history` → body.data 数组，服务端 `.all()`，生效起点倒序；独立 historyEmployee + useAsyncResource |
| expo.store-users | 门店范围完整绑定集合；store ID；无分页、无固定截断 | `GET /stores/{id}/users` → body.data 数组，服务端 `.all()`；店长优先、绑定 ID 升序；独立 usersStore + useAsyncResource |
| expo.store-user-candidates | 人员抽屉内账号选择器；keyword；固定第一页20项 | `getUserList({keyword,page:1,page_size:20})` → body.data.items；同抽屉作用域内独立资源、latest query 与重试，不扩展为完整用户列表 |

首次读取错误可见并提供重试，不展示成空集合；同作用域刷新失败保留上次成功数据并提示过期。更换员工/门店立即清旧数据，关闭抽屉取消请求并清作用域，迟到响应不再写回。

历史标题和请求不再共用员工编辑弹窗 currentRow；门店人员读写不再共用额度抽屉 activeStore。绑定与解绑捕获原门店和选择版本，确认期间切店不会把解绑写到新门店，迟到绑定成功不会清新表单；写成功后读取失败仍记录绑定成功，并把错误交给读取资源。原写权限、payload 和解绑确认文案保留。

## 验证

- 修复前实际旧员工页面慢读探针输出：`selectedEmployee=B, actualHistory=[{id:A}]`，确认了覆盖缺陷。新增测试首次执行失败是未实现资源名缺失；不能把这次 ReferenceError 当作业务行为失败证据。
- 当前命令：`node --test tests/employeeStoreChildResources.test.mjs tests/manualListAdoption.test.mjs tests/listAdoption.test.mjs`：**66/66 通过**，其中新增子集合文件 **21 项**，包含下述主管附录。
- 回归覆盖：首次错误/重试、同 scope stale、跨 scope 读取失败清旧、旧响应忽略、关闭取消、独立弹窗身份、候选 query race、绑定成功读取失败、迟到绑定以及同 ID 重开表单隔离、解绑确认期间切店阻止错误写入。
- 4 个实际 API 源码执行检查：员工历史、主管历史、门店人员、账号候选均传递 signal 身份、suppressToast、showLoading=false、原查询参数，并保留各自业务信封。
- 实际 SFC 编译及 Vue 自定义渲染器挂载三个页面，使用真实 ListPageStatus / GlassButton / useAsyncResource / Element Plus ElAlert，通过原生按钮事件完成员工历史、主管历史和门店人员首错重试；错误时不出现无数据，成功空历史才显示暂无历史，门店重试后显示实际用户。
- 挂载边界：表格列、抽屉、表单与选择器使用插槽/事件协议壳，验证实际页面状态和重试事件，不作为真实浏览器布局、遮罩与焦点验收。
- `npm run build`：通过，3364模块，最后一次17.24秒；已有大 chunk 和混合动态/静态引用警告。
- `python scripts/check_conventions.py`、作用域文件 `git diff --check`、`python scripts/git_sweep.py --no-fetch`：均退出0。Git巡检为本地快照；未提交、推送、合并或部署。

## 主管历史附录

父代理随后把同类遗漏扩展到 `supervisor/SupervisorRelation.vue`，已完成。

| 资源 | 类型 / 查询范围 / 上限 | 实际响应与实现 |
| --- | --- | --- |
| supervisor.relation-history | 业务员范围完整关系历史；`salesperson_id`；无分页、无固定截断 | `GET /supervisor/history` → body.data 数组，服务端 `.all()`，生效起点倒序；独立 historyRow + useAsyncResource |

修复前实际探针为 `currentSalesperson=B, actualHistory=[{id:A}]`。现在用独立 historyRow 保护标题和查询；同 scope 失败保数据，换人/关闭清旧与取消；首次失败独立反馈和重试。主管变更写权限、原查询范围、完整历史与写入字段保持有效。新增主管回归覆盖晚返回、编辑弹窗不改历史对象、首错重试、stale、关闭取消，以及换人读取失败清旧；已包含在21/21与66/66中。

## 责任文件与后续已知范围

本阶段修改三个页面、`api/employee.js` 的 getAttributeHistory、`api/expo.js` 的 getStoreUsers、`api/supervisor.js` 的 getSupervisorHistory，以及新增回归文件。上述 API 文件其余并行改动未覆盖。

补漏只读探针又确认 ProductManage 的路线预览迟到覆盖与 TrackingList 统计无独立错误状态；已通知主代理，主代理随后授权另一个修复阶段。该阶段会另列资源与证据，不计入本报告已完成的三处业务子集合。
