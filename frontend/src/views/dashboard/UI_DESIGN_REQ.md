# 莱莎方舟平台 — 工作台 UI 设计需求文档

> 交付对象：KIMI（前端代码生成）
> 项目路径：`frontend/src/views/dashboard/Dashboard.vue`

---

## 1. 项目背景

**莱莎方舟平台**是莱莎发制品企业内部综合后台，面向业务员、主管、财务、设计人员、管理员等多角色使用。

当前工作台（Dashboard）信息密度过低，仅展示 3 个指标卡 + 4 个快捷操作，未覆盖设计预约、物流跟踪等核心模块，也未针对不同角色做差异化展示。需要重新设计一个**角色感知、信息聚合、操作直达**的智能工作台。

---

## 2. 技术约束（必须遵守）

| 项 | 约束 |
|---|---|
| 框架 | Vue 3 + Element Plus + Vite 5 |
| 样式系统 | CSS Variables（`tokens.css` 为唯一真相源），禁止写死颜色值 |
| 字体 | Outfit（标题/导航/按钮）+ DM Sans（正文/表格）|
| 图标 | `@element-plus/icons-vue` |
| 状态管理 | Pinia `authStore`，通过 `authStore.hasAnyPermission([...])` 控制权限 |
| 设计规范 | 以 `DESIGN.md` 为准，所有颜色/字体/间距/圆角/动效必须对齐 |

### 2.1 颜色系统（直接用 CSS var）

```
主色:         var(--color-primary)        #D4941C
主色 Hover:   var(--color-primary-hover)  #BB8218
金色强调:     var(--color-gold)           #F5CB5C
成功:         var(--color-success)        #2D9F6F
危险:         var(--color-danger)         #DC3545
文字主色:     var(--text-primary)         #1a1a2e
文字次色:     var(--text-secondary)       #4a5568
文字弱化:     var(--text-muted)           #a0aec0
边框:         var(--border-color)         #e2e5ef
页面背景:     var(--page-bg)              #f0f2f7
卡片背景:     var(--card-bg)              #ffffff
表头背景:     var(--table-header-bg)      #fafbfe
行 Hover:     var(--table-row-hover)      #fef9f0
卡片圆角:     var(--card-radius)          12px
卡片阴影:     var(--card-shadow)
```

### 2.2 布局约束

- 内容区最大宽度：`1440px`
- 内容区 padding：`24px 28px`
- 卡片圆角：`12px`
- 卡片统一用 `background: var(--card-bg)` + `border: 1px solid var(--border-color)` + `box-shadow: var(--card-shadow)`
- 卡片 hover：`transform: translateY(-2px)` + `box-shadow: var(--card-shadow-hover)`，过渡 `250ms ease`

---

## 3. 工作台信息架构

工作台应分为**四大区域**，按信息优先级从上到下排列：

```
┌─────────────────────────────────────────────────────────────┐
│ ① Hero 欢迎区（角色化问候 + 今日概览）                        │
├─────────────────────────────────────────────────────────────┤
│ ② 待办提醒区（审批/异常/今日任务，有则显示无则隐藏）          │
├─────────────────────────────────────────────────────────────┤
│ ③ 数据指标区（按角色展示相关 KPI，3~4 列 grid）              │
├─────────────────────────────────────────────────────────────┤
│ ④ 快捷操作区（权限过滤，仅展示当前用户可访问的功能入口）      │
├─────────────────────────────────────────────────────────────┤
│ ⑤ 动态概览区（最近数据/状态分布，双栏布局）                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 区域详细设计

### 4.1 Hero 欢迎区

**功能**：展示平台品牌 + 根据角色和时间段给出个性化问候 + 今日关键数据摘要。

**视觉**：沿用现有的深色渐变背景（`linear-gradient(135deg, #141210, #1E1B18)`），圆角 `16px`。

**左侧内容**：
- 顶部 tag：`ARK PLATFORM`（10px/700/letter-spacing 0.15em/金色）
- 问候语：`{real_name}，{时段问候}` — 时段规则：
  - 05:00~11:00 → "早上好"
  - 11:00~14:00 → "中午好"
  - 14:00~18:00 → "下午好"
  - 18:00~05:00 → "晚上好"
- 副文案：根据角色动态显示（见下表）

| 角色特征 | 副文案 |
|---|---|
| 有 `design:audit` | 今日 X 条预约待审批，Y 条待排期 |
| 有 `design:manage` | 今日 Z 条拍摄任务待执行 |
| 有 `commission:write` | 本月提成批次已确认 / 待确认 |
| 有 `tracking:read` | 当前 N 条运单在途，M 条异常 |
| 其他 | 提成管理 / 物流跟踪 / 客户归属 / 设计预约 — 一句话概括 |

**右侧视觉**：保留现有的几何装饰（旋转的方块/六边形），微调为更精致的微动效（CSS animation，缓慢旋转/呼吸缩放）。

---

### 4.2 待办提醒区（条件渲染）

**规则**：该区域仅在用户有未处理事项时显示。无任何待办时整个区域隐藏，不占空间。

**展示内容**（按优先级排序，最多显示 3 条）：

1. **审批待办**：有 `design:audit` 权限时，显示待审批的预约数量。点击跳转 `/design/audit`。
2. **今日拍摄提醒**：有 `design:write` 或 `design:manage` 时，显示今日需要执行的拍摄任务数。
3. **归属待补充**：有 `customer:write` 时，显示 `incompleteCount`，点击跳转 `/customer/snapshot`。
4. **物流异常**：有 `tracking:read` 时，显示运单状态异常/长期未更新的数量。

**视觉样式**：
- 使用 Alert 风格的横幅条，圆角 `10px`
- 审批提醒：`var(--color-warning-bg)` 背景 + `var(--color-warning-text)` 文字 + `<el-icon><Bell /></el-icon>`
- 归属待补充：`var(--color-primary-light)` 背景 + `var(--color-primary)` 文字 + `<el-icon><Warning /></el-icon>`
- 物流异常：`var(--color-danger-bg)` 背景 + `var(--color-danger)` 文字 + `<el-icon><WarningFilled /></el-icon>`
- 右侧统一带 "前往处理 →" link 按钮

---

### 4.3 数据指标区

**布局**：响应式 grid，`grid-template-columns: repeat(auto-fit, minmax(240px, 1fr))`，gap `16px`。

**指标内容**（根据权限动态显示，无权限的指标不出现）：

| 指标名 | 适用权限 | 数据来源 | 视觉 |
|---|---|---|---|
| 待补充归属 | `customer:read` | `getSnapshotList({is_complete:'false'})` 的 `total` | 数量 > 0 时左侧金色竖线高亮，dot 琥珀色 |
| 本月提成批次 | `commission:read` | `getBatchList` 本月数据 | dot 蓝色 |
| 员工总数 | `employee:read` | `getEmployeeList` 的 `total` | dot 深灰 |
| 在途运单 | `tracking:read` | `getTrackingList` 状态筛选 | dot 青色（自定义 `#3B82F6`） |
| 今日拍摄 | `design:read` | `getDesignStats` 今日任务数 | dot 绿色 |
| 待审批预约 | `design:audit` | `getAuditQueue` 待审批计数 | dot 琥珀色，>0 时高亮 |
| 最近回款 | `payment:read` | `getPaymentList` 最新一条 | 显示金额/日期 |

**每个指标卡结构**：
```
┌────────────────────────┐
│ 指标标签          [dot] │  ← 12px/600/uppercase/次字色
│                        │
│ 123                    │  ← 30px/800/主字色
│                        │
│ [状态tag]  或  操作链接 →│  ← 12px/600
└────────────────────────┘
```

- 卡片：`background: var(--card-bg)` + `border: 1px solid var(--border-color)` + `border-radius: var(--card-radius)` + `padding: 20px 22px`
- hover：`transform: translateY(-2px)` + `box-shadow: var(--card-shadow-hover)`，过渡 `250ms ease`
- 有异常/待处理时左侧加 `3px` 金色竖线（`.metric-alert`）

---

### 4.4 快捷操作区

**布局**：`grid-template-columns: repeat(auto-fill, minmax(280px, 1fr))`，gap `12px`。

**快捷操作列表**（全部按权限过滤）：

| 标签 | 描述 | 路径 | 图标 | 权限 | 背景色 |
|---|---|---|---|---|---|
| 回款同步 | 拉取业务系统数据 | `/payment/sync` | `<Refresh />` | `payment:read` | 金色渐变 |
| 提成批次 | 计算与确认提成 | `/commission/batch` | `<List />` | `commission:read` | 深灰渐变 |
| 客户归属 | 补充客户归属信息 | `/customer/snapshot` | `<Document />` | `customer:read` | 金色渐变 |
| 员工属性 | 设置开发/分配属性 | `/employee/attribute` | `<UserFilled />` | `employee:read` | 深灰渐变 |
| 主管关系 | 维护业务主管关系 | `/supervisor/relation` | `<Connection />` | `employee:read` | 金色渐变 |
| 物流跟踪 | 查看在途运单状态 | `/tracking` | `<Van />` | `tracking:read` | 深灰渐变 |
| 提交预约 | 新建拍摄/设计预约 | `/design/submit` | `<EditPen />` | `design:write` | 金色渐变 |
| 我的预约 | 查看我提交的预约 | `/design/my-requests` | `<Document />` | `design:write` | 深灰渐变 |
| 排期甘特图 | 查看设计排期视图 | `/design/gantt` | `<Calendar />` | `design:read` | 金色渐变 |
| 审批队列 | 审批待处理的预约 | `/design/audit` | `<Stamp />` | `design:audit` | 金色渐变（带红点角标） |
| 设计管理 | 排期与任务管理 | `/design/manage` | `<Setting />` | `design:manage` | 深灰渐变 |
| 设计统计 | 查看设计业务数据 | `/design/stats` | `<TrendCharts />` | `design:manage` | 金色渐变 |
| 用户管理 | 管理系统用户 | `/system/users` | `<User />` | `user:read` | 深灰渐变 |
| 角色权限 | 配置角色与权限 | `/system/roles` | `<Lock />` | `user:read` | 金色渐变 |

**卡片结构**：
```
┌─────────────────────────────────────────┐
│ [38px 圆角图标]  操作名称            →   │
│                 操作描述                 │
└─────────────────────────────────────────┘
```

- 图标区：`38px × 38px`，`border-radius: 10px`，渐变背景，白色图标
- 操作名：`14px/600/Outfit/主字色`
- 操作描述：`12px/400/DM Sans/弱化字色`
- 箭头：`16px`，默认 `opacity: 0`，hover 时 `opacity: 1` + `translateX(2px)`
- 审批队列如有待审批项，图标右上角显示红色数字角标（`<el-badge>`）

---

### 4.5 动态概览区（双栏布局）

**布局**：`display: grid; grid-template-columns: 1fr 1fr; gap: 16px;`

**左侧：最近动态 / 快捷预览**

根据用户权限展示最相关的最近数据（2~3 条），带"查看全部 →" 链接。

| 权限 | 展示内容 | 链接目标 |
|---|---|---|
| `commission:read` | 最近 3 条提成批次（名称 + 状态 + 时间） | `/commission/batch` |
| `tracking:read` | 最近 3 条运单更新（单号 + 最新状态 + 时间） | `/tracking` |
| `design:read` | 最近 3 条设计预约（客户 + 状态 + 期望日期） | `/design/my-requests` |
| `payment:read` | 最近 3 条回款记录（客户 + 金额 + 时间） | `/payment/sync` |

展示为小型列表，无表格边框，行之间有 `1px` 分割线（`var(--border-color)`）。

**右侧：状态分布 / 快捷图表**

根据权限展示简单的状态分布：

| 权限 | 展示内容 |
|---|---|
| `tracking:read` | 运单状态分布饼图/环形图（在途/已签收/异常/其他） |
| `commission:read` | 本月提成批次状态分布（草稿/已计算/已确认/已作废） |
| `design:read` | 设计预约状态分布（pending/approved/scheduled/...） |

图表使用轻量级实现（CSS 环形图或简单 bar），**不要引入额外图表库**。
环形图参考实现：用 `conic-gradient` 或 SVG `<circle>` 的 `stroke-dasharray`。

---

## 5. 角色差异化逻辑

工作台的所有内容必须通过 `authStore.hasAnyPermission([...])` 做权限过滤。不同角色登录后看到的内容不同：

| 角色类型 | 典型权限组合 | 工作台重点 |
|---|---|---|
| 业务员 | `commission:self_read`, `customer:read`, `design:write`, `tracking:read` | 我的提成、客户归属、我的预约、物流跟踪 |
| 主管 | + `commission:write`, `employee:read`, `design:audit` | + 员工管理、审批待办 |
| 设计人员 | + `design:manage`, `design:read` | + 排期管理、设计统计 |
| 管理员 | `super_admin` 或全权限 | 全部模块、系统管理入口 |
| 财务 | `payment:read`, `commission:read`, `commission:write` | 回款同步、提成批次确认 |

---

## 6. 入场动效

页面加载时元素依次入场，间隔 `70ms`：

```css
.anim-stagger > * {
  animation: fadeInUp 0.5s ease forwards;
  opacity: 0;
}
.anim-stagger > *:nth-child(1) { animation-delay: 0ms; }
.anim-stagger > *:nth-child(2) { animation-delay: 70ms; }
.anim-stagger > *:nth-child(3) { animation-delay: 140ms; }
/* ... */

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

---

## 7. 响应式要求

| 断点 | 布局调整 |
|---|---|
| ≥1200px | 4 列指标 + 2 列快捷操作 + 双栏概览 |
| 768px~1199px | 2 列指标 + 1 列快捷操作 + 单栏概览 |
| < 768px | 1 列指标 + 1 列快捷操作 + 单栏概览（隐藏几何装饰） |

使用 CSS Grid 的 `auto-fit` + `minmax` 实现，不需要写媒体查询也能基本适配。

---

## 8. 数据接口参考

以下接口已存在，可直接调用：

```javascript
// api/customer.js
getSnapshotList({ is_complete, page, page_size })

// api/commission.js
getBatchList({ page, page_size })

// api/employee.js
getEmployeeList({ keyword, page, page_size })

// api/payment.js
getPaymentList({ page, page_size })

// api/tracking.js
getTrackingList({ carrier, status, page, page_size })

// api/design.js
getMyRequests({ page, page_size })
getAuditQueue({ page, page_size })
getDesignStats()  // 如有，否则从列表数据计算

// api/auth.js
getMe()  // 返回 { real_name, permissions, roles }
```

---

## 9. 输出要求

请 KIMI 生成完整的 `Dashboard.vue` 文件，要求：

1. **单文件 Vue 组件**，`<template>` + `<script setup>` + `<style scoped>` 三段式结构
2. **所有颜色/字体/间距使用 CSS Variables**（`var(--xxx)`），禁止写死颜色值
3. **权限过滤**：所有功能模块通过 `authStore.hasAnyPermission([...])` 控制显示
4. **图标全部来自 `@element-plus/icons-vue`**，使用 `<component :is="iconName" />` 或 `<el-icon><IconName /></el-icon>`
5. **样式写在 scoped style 中**，不重复定义 DESIGN.md 中已有的全局样式
6. **响应式**：使用 CSS Grid 的 `auto-fit` + `minmax` 自适应
7. **动效**：元素交错入场，卡片 hover 上浮
8. **注释**：用中文注释说明各区域的权限逻辑

---

## 10. 现有代码参考（Dashboard.vue 当前状态）

当前工作台只展示了：
- Hero 区（静态标题 + 几何装饰）
- 3 个指标卡：待补充归属 / 最近批次 / 员工总数
- 4 个快捷操作：员工属性 / 主管关系 / 回款同步 / 提成批次

新设计需要在此基础上大幅扩展，覆盖全部 6 大业务模块，实现角色感知和待办聚合。
