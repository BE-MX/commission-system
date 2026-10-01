# 价格、名片管家、公告与 Operations 资源审查

审查日期：2026-10-02。工作目录：`C:/Users/windb/.codex/worktrees/list-filter-behavior/commission-system`。

## 结论

本轮资源接入通过独立审查，没有剩余已确认的交付问题。真实 API 信封、有限集合边界、草稿与已提交查询、读取失败恢复、客户纪要多附件写入快照、公告成员权限保护、Operations 停用取消和安静轮询已核验。

审查提出的生产单沉淀产品默认 200 条边界已由主代理补充 UI 提示。当前测试 27/27 通过；三个实际 Vue 页面首次错误挂载验证通过；10 个实际 API 读适配器透传验证通过。本报告由审查者落盘，业务源码和测试由主代理负责，审查者没有修改其他文件。

## 真实资源与接口形态

| 资源 | 页面 / API | 真正类型与限制 | 接入与反馈 |
| --- | --- | --- | --- |
| 标准参考价 | `InvoicePriceConfig` / `listStdPrices` / GET `/price/std` | `{items}`，无分页完整集合 | useAsyncResource；所有系列保留为下拉选项；已提交系列在本地过滤，刷新不提交草稿 |
| 色型映射 | `listColorTypes` / GET `/price/color-types` | `{items}`，无分页完整集合 | 独立资源，首错/旧数据错/空结果/重试 |
| 客户价格规则 | `listCustomerRules` / GET `/price/customer-rules` | `{items}`，完整集合，可 keyword | keyword/appliedKeyword 分离；写后刷新使用已提交关键词 |
| 生产单沉淀产品 | `listCustomProducts` / GET `/custom-products` | `{items}`，service 默认 limit=200，router 无分页参数 | 独立资源；已提交 keyword；UI 说明最近 200 个符合条件产品及搜索缩小范围 |
| 客户候选 | `searchInvoiceCustomers` / GET `/customers/search` | `{items}`，默认 20、最大 50 的远程候选 | 查询 latest guard；关闭规则弹窗清空并取消；不是主列表分页资源 |
| 配件标准价 | `AccessoryPriceConfig` / `listAccessoryPrices` / GET `/price/accessories` | `{items}`，无分页完整集合 | 原专用 createLatestAccessorySearch 接入 signal/错误；首错内联，刷新错保留旧行；已提交关键词 |
| OKKI SKU 候选 | `searchAccessoryCandidates` / GET `/price/accessory-candidates` | `{items}`，service 最大 50 个活跃产品/SKU | 专用 latest search；关闭/重新打开/unmount invalidate；候选错误独立重试 |
| 业务员档案 | `useCardButler` / GET `/admin/salespersons` | 业务信封 data 为完整数组 | useAsyncResource；首错/旧数据错/空结果/重试 |
| 客户档案 | GET `/admin/customers` | data.items/total，page/page_size，后端页大小最大 100 | 原 useListPage 分页；已提交筛选；CRUD 按 create/update/remove 刷新 |
| 询盘 | GET `/admin/inquiries` | data.items/total，真实分页 | 独立 useListPage；已提交状态与业务员筛选 |
| 客户沟通纪要 | GET `/admin/customers/{id}/entries` | data 为完整数组，按创建时间/id | 独立资源；切客户 clear/cancel；关闭抽屉 clear/currentCustomer=null；旧响应不能覆盖新客户 |
| 公告周报 | `AnnouncementWeekly` / GET `/weekly` | 直接返回数组，最新 52 版本 | 独立资源；UI 明示 52；首错不误显示暂无，刷新错保留旧版本 |
| 公告库配置 | `AnnouncementSettings` / GET `/config` | 直接返回对象 initialized/config 字段 | 首错与 initialized=false 成功明确区分；错误/未加载时不显示初始化入口 |
| 公告类别 | GET `/categories` | 直接返回完整数组 | 与配置/成员各自独立错误与重试 |
| 公告成员 | GET `/members` | 直接返回完整数组，可编辑角色 | 错误或加载中禁止整体 replace 写入，保护原权限；成功读取空数组才表示真实无成员 |
| 公告成员候选 | GET `/member-candidates?q=` | 直接返回数组，knowledge service 上限 20 | latest query 和 signal；独立候选错误重试；属于远程候选 |
| 公告投递 | GET `/deliveries` | 直接返回数组，最新 200 条 | 独立资源；UI 明示 200；读错保留旧投递，失败/不确定投递动作保留确认语义 |
| Operations 总览 | GET `/overview` | 业务信封 data 对象，含 scheduler/services/runtime_instances/summary | 专业聚合对象，不套分页；整体资源错误与独立重试；首次失败不造 0 指标 |
| Operations 运行记录 | GET `/job-runs` | 业务信封 data 数组，limit=30，API 上限 100，可 status | 已提交状态；UI 明示最新 30；总览/运行记录独立成功和错误 |

信封证据：共享 API client 拦截器返回业务 `{code,message,data}`；invoice API 的 unwrap 返回 data 的 `{items}`，Card/Operations 直接读取 response.data；announcementApi 进一步 unwrap 成直接对象/数组。源码与真实后端 router/service 一致。

## 行为审查

### 价格与配件

- 四个主资源独立读取，首次错误有重试，刷新失败保留成功行；晚响应由 sequence/signal 隔离。
- 标准价的所有系列选项来自原集合，筛选后不会丢其他系列选项。rule/custom/accessory 的刷新、保存、对账不会自动提交草稿关键词。
- 标准价/客户调整值只在展示格式化，不向 payload 写带千分位字符串。配件 payload 保留真实 product_id/sku_id，价格仍用 `Number(price).toFixed(2)` 的既定传输规范；编辑身份未被候选刷新覆盖。
- 标准价/色型/规则保存与删除、Excel 导入、对账后触发资源刷新；读失败 settle 不倒转已完成写入。配件 onSuccess 等待 loadRows，但 loadRows 在读错时返回 false，故弹窗正常关闭且保留保存成功提示。
- 配件删除取消不调用删除 API；请求错误交共享 interceptor，局部错误保留原 error 防重复反馈。

### Card

- 业务员保存成功后列表读取失败仍保存成功；旧业务员数组保留并提示过期。
- 沟通纪要切换客户先清空旧客户数据，关闭抽屉后取消并清空当前客户；旧 GET 即使迟到也不更新新客户列表。
- saveEntry 在开始时捕获 customerId、form 和 files；每张附件一条记录，文本只随第一条。保存中切客户或编辑新内容不会把第二张图写入新客户；旧客户写完不清空新客户草稿。
- 保存完成后纪要和客户主表刷新均不因独立 GET 错误把成功写入判失败。
- 多附件仍是多个顺序 POST 的既定后端契约，未增加自动写入重试或事务式承诺。

### 公告

- config 初始化读取失败时 hasLoaded=false/error 不空；只有成功读取且 initialized=false 才显示建立公告库和初始化按钮。
- categories/members/member-candidates 独立资源，不互相覆盖成功结果。members 加载错误阻止整体 PUT，避免把错误呈现的空数组保存成权限清空。
- saveMembers 写入后 config 或成员刷新失败仍保留成功提示，读错单独反馈；Weekly 排队成功后读取失败亦保留入队成功。
- 周报 body 原 escaping 和内部公告链接白名单保持；DELIVERY_STATUS/WEEKLY_STATUS 为状态字典唯一来源，中文标签/危险状态逻辑保留。

### Operations

- overview 和 runs 独立 settle；某项失败保留自身旧结果且不丢另一项成功结果。
- 筛选 draft/runStatus 与 appliedRunStatus 分离；手动刷新、30 秒轮询、动作后刷新都使用已提交状态。
- quiet 不占用整体 interactiveRequests/loading；交互刷新与后台刷新重叠不会把整体 loading 卡住。
- mount/activate 只创建一个 interval；隐藏 document 不发轮询；deactivate/unmount 清除计时器并 cancel 两个资源，保留成功数据，迟到结果被隔离。
- 操作确认取消正常 settle 并释放 actionJobId；真实动作成功后即使读取失败仍保留动作成功。确认文案与生产任务影响提示保留。

## 实际验证

### 现有测试

```text
node --test tests/invoicePriceResources.test.mjs tests/invoiceAccessoryPriceBehavior.test.mjs tests/invoicePricePrecision.test.mjs tests/remainingCollectionResources.test.mjs tests/operationsLifecycle.test.mjs tests/announcement.test.mjs
27 passed / 0 failed
```

覆盖：价格四资源首错/旧响应/旧数据保留、已提交查询、配件身份和精度、取消删除、业务员写后读失败、纪要换客户/关闭/多附件快照、Weekly 入队读失败、Settings 初始化/独立错误、候选最新结果、Operations 提交状态/独立错误/生命周期。

### 实际控制器与 API 补充探针（未新增测试文件）

- Card 捕获客户 1 的两附件后切客户 2：两次写入均 customerId=1、title 为原快照；第一条原文本、第二条 content=null；新客户草稿保留；旧客户读取迟到忽略、关闭后资源清空。
- Settings config 首错未加载，members 首错阻止 PUT；成功成员 `{user_id:1,role:'editor'}` 写入后 config GET 失败，保存成功提示仍成立。
- Operations 使用真实 useAsyncResource：已提交 failed 后 draft 改 success，刷新仍传 `{limit:30,status:'failed'}`；动作成功后两项 GET 错误保留成功；停用时 signal.aborted=true、timer=0、loading=false，迟到旧总览/记录不更新保留数据。
- 10 个实际 API 读适配器用后端一致的 ok 信封执行：invoice 六个、Card 两个、announcement config/weekly 两个；unwrap 结果正确，AbortSignal identity 保留，suppressToast=true/showLoading=false 保留。

### 真实 Vue 编译与挂载

实际编译并挂载 `AnnouncementSettings.vue`、`AnnouncementWeekly.vue`、`OperationsCenter.vue`，实际 useAsyncResource、ListPageStatus、GlassButton、Element Plus ElAlert 进入渲染。

验证结果：

- Settings config 首次失败显示实际错误，不出现“初始化公告库”/“建立公告库后”；点击真实 GlassButton 重试并返回 initialized=false 成功后，初始化入口才出现。
- Weekly 首次读取失败显示实际错误，不出现“暂无公告周报”。
- Operations 首次错误不挂载 aria-label 为“运行摘要”的指标区，不显示“0 个心跳正常”。

挂载边界：使用 Vue 自定义 renderer，表格/tabs/表单使用对应 slot 协议壳，API 是确定性 fixtures；不是浏览器全 Element Plus 组件 E2E，也没有真实外部消息、生产任务或数据库写入。初次挂载辅助器缺少 static host 操作，补足只在临时脚本中执行，未改业务源码或测试辅助器。
