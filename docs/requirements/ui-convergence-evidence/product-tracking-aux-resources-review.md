# 产品辅助资源与运单统计修复

2026-10-02；`codex/list-filter-behavior` 工作树。本阶段仅修复已确认遗漏，未继续扩大全站扫描。

## 资源与范围

| 资源 | 类型 / 范围 / 上限 | 真实服务端契约 |
| --- | --- | --- |
| production.product-filter-options | 筛选维度集合；型号/分组全量 distinct 值；无分页与固定截断 | `getProductFilterOptions` → `{ models, group_names }`；读取原对象 |
| production.active-routes | 完整启用路线选择器；无分页与固定截断 | `getActiveRoutes` → 数组；原排序与选项字段保持 |
| production.product-route-preview | 绑定弹窗当前 route ID 的完整步骤集合；无分页与固定截断 | `getRouteSteps(id)` → `{ route_id, steps }`；读取 `steps` |
| tracking.stats | 当前登录用户数据权限范围的聚合快照；不是分页列表，无行数截断 | `getTrackingStats(undefined, config)` → body.data 计数字典；保留 total/active/status 的原统计口径 |

前三个资源各自独立，首错显示重试、同 scope 失败保上次成功结果。预览在切产品、切路线、解绑选择或关闭时清旧并取消，旧响应不能回填新选择；相同路线 ID 切产品仍是新弹窗作用域。筛选维度和路线选项错误不影响主产品列表读取或覆盖其已提交筛选。

运单统计用独立资源反馈错误；首次失败不渲染成全零看板，同 scope 刷新失败保留旧计数与旧完成时间。计数和完成时间在同一当前响应中提交；用户/权限作用域改变清除旧统计，晚响应无效。看板点击、查询提交、CRUD 主列表刷新及原状态计算不变。

单产品绑定捕获原 product ID 与 route ID（包括 `null` 解绑），批量绑定捕获原 product IDs 与 route ID。旧成功不关闭新打开/已修改的绑定弹窗。绑定成功后主列表读取失败保持写入成功，错误落列表资源。保留 `production:write` 权限、原绑定提示和确认文案；没有新增生产数据操作。

## 缺陷证据与回归

修复前实际当前 ProductManage 脚本探针：routeId 从1切2、2先成功、1晚回，结果为 `routeId=2, previewSteps=[{process_id:11}]`，确认了错路线预览。

新增 `tests/productTrackingAuxResources.test.mjs` **15/15 通过**。覆盖：两个独立选择器首错/重试/stale，预览晚响应与跨路线清旧、首错和同路线保留、关闭/解绑取消、同路线 ID 换产品，单绑定/批绑定原 payload 与新弹窗保护，解绑 null 和写成功读失败，统计首错与主表独立、旧统计/时间保留、晚统计响应、权限范围清旧、运单写成功统计失败，3 个实际 API 源码配置探针。

组合命令：

```text
node --test tests/productTrackingAuxResources.test.mjs tests/productionRouteResources.test.mjs tests/manualListAdoption.test.mjs tests/listAdoption.test.mjs tests/employeeStoreChildResources.test.mjs
```

结果 **91/91 通过**。其中一轮预览错误断言失败来自测试只等待一层 nextTick，API/资源两层 await 尚未 settle；改为完整 Node 事件轮完成后检查，保留错误断言与重试逻辑。

## 实际页面验证与项目检查

实际 SFC 编译与 Vue 自定义渲染器挂载 ProductManage、TrackingList，使用真实 ListPageStatus / GlassButton / useAsyncResource / Element Plus ElAlert；通过原生重试按钮分别完成筛选维度、路线选项、路线预览与统计读取。预览成功后路线选项仍失败，证明错误资源互不覆盖；统计首错不展示看板，主运单仍存在，重试成功展示真实统计。

输出：

```json
{"productMounted":true,"trackingMounted":true,"filterRetry":true,"routeSelectorRetry":true,"previewRetry":true,"independentErrors":true,"statsFirstFailureNotZero":true,"nativeRetry":true}
```

边界：表格列、对话框和选择器用插槽/事件协议壳；不作为真实浏览器焦点、遮罩、布局验收。

- `npm run build` 通过，3364模块，16.98秒；存在已有 chunk 与混合动态/静态引用警告。
- 最新 `python scripts/check_conventions.py` 输出增量无违规；先前并行 Dashboard 三条日期红项已通知主代理，最新检查已消失。
- 责任范围 `git diff --check` 通过。
- `python scripts/git_sweep.py --no-fetch` 通过；仅本地快照，未提交/推送/合并/部署。

## 责任文件

修改 `production/ProductManage.vue`、`tracking/TrackingList.vue`；仅在 `api/production.js` 为 getProductFilterOptions/getActiveRoutes 增加请求配置，在 `api/tracking.js` 为 getTrackingStats 增加第二配置参数；getRouteSteps 复用上一阶段已有配置契约。新增回归文件和本报告。API 文件其他代理已存在的改动保留。

本阶段已知确定遗漏已处理；总体文档与真正浏览器体验由主代理合并验收，本报告不代表全站所有资源已经验收完成。
