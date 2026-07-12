# 角色权限细化重构（2026-07-12）

> **性质**：设计 + 实施记录（当日完成，7 个提交 `5cdd2aa..0b2a1da`）
> **前置**：2026-07-03 权限重设计（docs/requirements/2026-07-03-permission-redesign.md）解决了元数据分层与配置 UI；本次解决"粒度不够 + 三层防线缺口"。
> **决策方式**：拆分粒度与迁移策略经用户反向访谈确认——按功能单元拆分（非每页独立）、平滑迁移不收紧、生产看板不拆。

## 一、审计结论（2026-07-12 全量核查）

| 层 | 发现 | 修复 |
|----|------|------|
| 端点鉴权 | `app/api/` 老共享层 30 个端点零鉴权（提成批次 9、客户归属 7、员工 5、主管 4、回款 2、报表导出 3）；tracking 4 个匿名；短链生成匿名 | 全部补 `require_permission`/`require_any_permission`；模板下载/报表打印类浏览器直链保持开放 + 白名单注释 |
| 路由拦截 | 15 个页面只有 menu 级权限、entry 级为空——任何登录用户可 URL 直达（含提成批次、设计审批、设计管理） | navigation.js 全部补 entry 级 permission/anyPermission |
| 按钮控制 | 32 个含写操作页面无按钮级权限；`user:read` 即可见用户/角色管理全部写按钮 | 17 个 read 可进的页面补 55+ 处 `v-permission`；整页 write/admin 管控页与个人数据操作有意不加 |
| 读写错位 | 约 23 处（写端点挂 read / 纯查询挂 write） | 逐一修正（tracking poll/refresh/scan→write、color verify→write、insight tasks→minutes write、cart/process-bindings GET→read 档等） |
| 粒度 | 一码控多页：user:read 捆 3 页、insight:read 捆 5 页、expo:read 捆 3 页、employee:read 捆 2 页 | 功能单元拆分（见下） |

## 二、拆分方案（新增 10 码 + 接线 3 个既有码）

| 页面 | 旧 | 新 |
|------|-----|-----|
| 角色权限 | user:read/write | **role:read/write/delete**（码已存在，端点与前端本次接线） |
| 基础字典 | user:read/write | **dict:read/write**（新增；字典数据 GET 保持任意登录可读，dict:read 只控页面入口） |
| 主管关系 | employee:* | **supervisor:read/write**（新增） |
| 业务员案例库 | insight:read/write | **insight_case:read/write**（新增） |
| 周会纪要 | insight:read/write | **insight_minutes:read/write**（新增） |
| 展会线索台 | expo:read | **expo_lead:read/write**（新增；kiosk 销售反馈端点兼容 expo:write——调用方是展位设备） |
| 售后分析 | aftersales:read | **aftersales_analytics:read**（062 迁移补充；售后四页至此各自独立：单=read / 审=write / SOP=admin / 分析=analytics） |

- `insight:write` 职责拆空 → legacy 下架（seed LEGACY_SEEDS + 061 置 is_legacy=1）
- 生产看板**不拆**（用户确认无"只给看板"的岗位需求）

## 三、平滑迁移（061_permission_split_grants）

持有旧捆绑码的角色自动补授新码，上线零感知，之后在角色管理页人工收紧：

```
user:read  → +role:read, dict:read      employee:read  → +supervisor:read
user:write → +role:write, dict:write,   employee:write → +supervisor:write
             role:delete(保持旧行为)      insight:read   → +insight_case:read, insight_minutes:read
user:delete→ +role:delete               insight:write  → +insight_case:write, insight_minutes:write
expo:read  → +expo_lead:read            expo:write     → +expo_lead:write
```

幂等（NOT EXISTS）；downgrade 只回收 10 个新码，不动既有 role:*。

## 四、对抗性审查结论（独立 agent，`git diff 5cdd2aa^..`）

高 1 / 中 4 / 低 5，全部修复或声明：kiosk 反馈契约错位（改 any 双码）、Dashboard 主管卡漏换码、案例库添加按钮漏指令、运单详情补数据范围过滤、周会 CSV 导出 window.open 直链改 axios blob（修掉一个改造前就存在的 403 断点）、061 补 user:write→role:delete、案例/周会导航补 insight:admin、expo 素材页端点补 expo:admin、运单详情路由放宽 read|write。

## 五、遗留与残余风险（未在本次处理）

1. `/uploads` 静态挂载无鉴权，可绕过 asset 下载权限直取原文件（审计发现，待专项）
2. 钉钉回调 `POST /api/dingtalk/callback` 无签名校验（encrypt 分支 TODO）
3. `POST /tracking/staging` 保持 m2m 开放（外部推送依赖，暂存区隔离风险）
4. ExpoLeads 页暂无「反馈录入」UI，`expo_lead:write` 前端消费待后续需求
5. `report:design` 把守报表版本历史 GET（设计使然，未放宽）
6. 若存在未记录的外部系统调用 `POST /api/shortlink`（如 n8n），需给它配 token——文档检索无记录

## 六、上线注意

- 部署顺序：`alembic upgrade head`（061 补授）→ 重启后端（seed upsert 刷新新码元数据/排序 + admin 自动补齐新码）
- 上线后所有角色可见/可操作范围与改造前一致；收紧在角色管理页逐角色取消勾选即可（矩阵已按新前缀分行：主管关系/基础字典/案例库/周会纪要/展会线索台独立成行）

## 七、第二批：导航页逐页拆分（2026-07-12 晚，062/063 迁移）

用户追加指令：**左侧导航中每个独立菜单页都必须能在权限矩阵单独配置**（该指令覆盖
本文第二节"生产看板不拆"的旧决策）。核对结论：61 个菜单页中 22 个与同域其他页共用
权限码。062 先拆售后分析，063 一次补齐其余 22 页：

- 每簇"主页面"保留旧码（label 收窄到只指该页）：发型库=expo:read、销量备货一览=
  stock:read、生产订单管理=production:read、工序管理=production:admin、素材库=
  asset:read、色板数据库=color:read、情报速览=insight:read、内部经营报告=
  insight:internal_read、概念注册表=governance:read
- 其余 22 页各发 `<域>_<页>:read` 页面码；nav 入口只挂新码（单码单页）；角色模板
  （roleTemplates.js）同步补页面码
- 端点接线**只加不减**：各页查询端点 require_any_permission 追加页面码，旧码全保留
  （kiosk 设备账号、发票编辑器复用端点零影响）；insight 三页面码并入 _require_insight_view，
  内部报告仍被 INTERNAL_REPORT_TYPES 内层校验拦截
- **页面码语义=该域数据读取，不是行级隔离**（对抗性审查中-2 记录在案）：如 design_my:read
  经 /requests 可读全公司预约单（端点本无 created_by 过滤）、insight 三页面码互通报告/条目端点、
  invoice_price:read 可搜客户名。补授来源=旧可见者，上线不放大任何人权限；单独授码时管理员
  需知道这一层。design 附件含客户资料，中期可考虑给 design_my:read 单独持有者加数据范围
- 审查修复：①三个原 admin 专属页（价格配置/回款修复/工序路线）写按钮补 v-permission
  （红线 15）；②/insight/reports 裸查询（不带 type）对无 internal 权限用户排除
  INTERNAL_REPORT_TYPES，关掉内部报告标题/元数据枚举缝隙（既有缺口）；③invoice_okki:read
  label 注明"页面数据需 invoice:admin"
- 例外：OKKI 推单设置页 GET 返回凭据配置，保持 invoice:admin，invoice_okki:read 只控
  菜单显隐；回款修复 preview/export-unmatched（只读试算）放行 invoice_repair:read，
  apply 仍锁 invoice:admin
- 063 迁移按旧导航可见性补授（如 design_gantt:read ← 任一 design:*；expo 三页 ←
  expo:read|admin），幂等，downgrade 只回收 22 个新码
- 既有 bug 记录（未修）：GanttView 导出按钮用裸 fetch 直链 GET /api/design/export/tasks
  （端点要求 audit|manage），不带 JWT 应已 401；api/design.js 有带 JWT 的 exportTasksExcel()
  未被使用
