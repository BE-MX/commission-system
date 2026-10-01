# 工序路线详情资源修复与验证

日期：2026-10-02。工作目录：`C:/Users/windb/.codex/worktrees/list-filter-behavior/commission-system`，分支 `codex/list-filter-behavior`。

## 结论

工序路线的详情、条件规则与可添加工序已具备失败反馈、重试和作用域隔离。已确认的两项旧问题——旧路线迟到响应覆盖新路线编辑器、新路线读取失败保留旧路线步骤——已修复。路线详情未成功读取、正在刷新或发生读取错误时，写入入口会阻止保存；同一路线刷新失败仍保留已有编辑草稿。

## 本次修改责任范围

- `src/views/production/ProcessRouteManage.vue`：路线步骤与条件规则组合成一个完整配置资源；启用工序采用独立资源；编辑与保存门禁、选中作用域和迟到写响应隔离。
- `src/api/production.js`：只为 `getRouteSteps`、`getActiveProcesses` 新增可选请求配置，传递 `signal`、`suppressToast`，保留原响应。
- `src/api/domestic.js`：只为 `getDomesticRouteRules` 新增可选请求配置，传递 `signal`、`suppressToast`，保留原响应。
- `tests/productionRouteResources.test.mjs`：10 项实际页面控制器回归。
- `tests/domesticConditionalUi.test.mjs`：同步 API 配置参数和新增读取门禁的静态约束；继续检查权限分离、原子保存、草稿保护和条件规则。

两个 API 文件的其他并行修改属于其他代理，不在本修复责任范围。

## 数据与权限约束

| 资源 | 实际服务端契约 | 使用方式 |
| --- | --- | --- |
| 路线目录 | `getProcessRoutes({ page_size: 200 })` → `{ items, ... }` | 既有固定上限列表资源保持原样 |
| 路线步骤 | `GET /process-routes/{id}/steps` → `{ route_id, steps }` | 读取 `steps`，不再把 Axios 层信封当业务数据 |
| 内贸条件规则 | `GET /process-routes/{id}/rules` → `ok([...])`；请求拦截后为 `{ data: [...] }` | 读取 `data`；网络、5xx 及有规则编辑权限者的 403 均表现为可重试读取错误 |
| 启用工序 | `GET /active-processes` → 完整数组 | 独立资源；详情成功不依赖该选择器成功 |

生产编辑者没有内贸读取权限时，规则接口 403 可以仅降级为步骤编辑；不会吞掉其他失败。组合详情仅在步骤与所需规则均完成后开放编辑，避免把规则读取失败当作空规则提交。已有 `production:admin`、`domestic:admin` 权限分工、原子保存端点、离开未保存草稿确认保持有效。

更换路线或权限作用域会清除旧详情并取消旧请求。保存与模板确认同时记录路线 ID 和选择版本；A→B→A 重选也不会让旧写响应刷新新编辑器。迟到写失败不会标记新路线为错误或脏数据。

## 验证证据

1. 回归命令：

   ```text
   node --test tests/productionRouteResources.test.mjs tests/domesticConditionalUi.test.mjs tests/manualListAdoption.test.mjs tests/domesticRouteSaveFlow.test.mjs tests/routeDraftGuard.test.mjs
   ```

   结果 **28/28 通过**。其中本次新增 10 项覆盖：迟到详情、新路线首读失败与保存阻止、同路线脏草稿保留、规则网络失败与权限 403、工序独立重试、保存成功但刷新失败、迟到成功写、脏草稿离开取消、两类迟到失败写、同 ID 重选的保存隔离。

2. 实际 Vue SFC 编译及挂载探针通过。使用真实 `ProcessRouteManage.vue`、`ListPageStatus.vue`、`GlassButton.vue`、`useAsyncResource` 和 Element Plus `ElAlert`，通过原生按钮事件完成详情首错重试与工序独立重试。输出：

   ```json
   {"mounted":true,"stepsReads":2,"processReads":2,"detailRetry":true,"processRetry":true,"independentErrors":true,"firstErrorNotEmpty":true,"saveBlocked":true}
   ```

   边界：运行在 Vue 自定义渲染器；对话框、表单、选择器与 draggable 使用匹配插槽和事件协议的壳，验证页面状态及重试事件，不作为浏览器拖动、遮罩或真实布局验收。

3. 实际 API 源码探针通过：三个读取适配器均保留 `AbortSignal` 身份、`suppressToast: true` 和 `showLoading: false`，请求路径与原始数组/业务响应一致；未改写写入 payload。

4. `npm run build` 通过，3364 模块，构建耗时 16.66 秒。存在已有动态/静态重复引用及大 chunk 警告，无构建错误。

5. `python scripts/check_conventions.py` 通过；`git diff --check` 对责任范围文件通过。

6. `python scripts/git_sweep.py --no-fetch` 通过。为本地快照；本工作树处于共享任务的大范围未提交状态，未执行提交、推送、合并或分支清理。

## 交付边界

此次已处理确认缺陷与对应写入保护，未发现责任范围内的剩余已确认阻塞。浏览器中的拖动和布局仍由主代理整体 UI 验收；路线目录的固定 200 条上限是原有业务行为，本次未扩展分页契约。
