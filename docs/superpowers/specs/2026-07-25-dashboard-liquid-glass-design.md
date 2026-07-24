# 工作台 Liquid Glass 重构设计（2026-07-25）

> 决策记录：配置持久化方式（后端）与玻璃基调（浅色+金色极光）由亮哥逐题确认；
> 其余决策按推荐方案锁定（用户指令：按推荐方案执行直至完成）。

## 目标

1. 工作台卡片**可配置化**：每个用户可显隐、拖拽排序指标卡与快捷操作卡，配置跟人走（后端持久化）
2. 视觉升级为**半透明 liquid glass**：浅色玻璃卡片 + 金色极光背景，与现有 Luxury/Utilitarian 金色系和其他浅色内页衔接
3. **卡片逻辑重构**：硬编码模板 → 注册表驱动，新增卡片只加一条声明
4. 动效按 Emil Kowalski 框架收敛：克制、快速、有目的

## 非目标（YAGNI）

- 不做角色级默认布局下发（个人配置已够 30 日活场景）
- 不做卡片尺寸调节 / 自由网格（只做显隐+排序）
- 待办提醒区、Hero、动态概览**不可配置**——紧急信息不允许被用户关掉
- 指标数字不做 count-up 动画（功能性数据不装饰）
- 不改 useDashboardData.js 的数据获取逻辑

## 后端设计

### 表 `ark_dashboard_preference`（迁移 080_dashboard_preference）

| 列 | 类型 | 说明 |
|----|------|------|
| id | Integer PK autoincrement | 主键 |
| user_id | Integer FK→ark_users.id ON DELETE CASCADE, unique, index | 每用户一行 |
| prefs | JSON NOT NULL | 布局配置，shape 见下 |
| created_at / updated_at | DateTime | server_default=now / onupdate |

迁移带幂等检查（inspector 查表存在性），与 079 同风格。

### prefs JSON shape（version 1）

```json
{
  "version": 1,
  "metrics": { "hidden": ["employee_total"], "order": ["incomplete", "batch", "..."] },
  "actions": { "hidden": [], "order": ["payment_sync", "..."] }
}
```

- 服务端 pydantic 只校验**形状**（version int、hidden/order 为 str 列表、长度上限 100）
- **不校验 key 合法性**：卡片 key 的真相源在前端注册表；未知 key 前端渲染时忽略
- 向前兼容：注册表新增卡片不在 order 里 → 前端自动追加到末尾并默认可见

### 模块 `app/dashboard/`（四件套）

- `models.py`：DashboardPreference
- `schemas.py`：SectionPrefs / DashboardPrefs / DashboardPrefsIn
- `service.py`：get_prefs(db, user_id) / upsert_prefs / reset_prefs
- `router.py`：
  - `GET /api/dashboard/preference` → `ok(prefs | None)`
  - `PUT /api/dashboard/preference` → upsert，`ok(prefs)`
  - `DELETE /api/dashboard/preference` → 删行（恢复默认），`ok()`
- 鉴权：三端点均 `Depends(get_current_user)`，**不挂 require_permission**——个人域数据
  （同 `/api/auth/me` 模式），user_id 取自 JWT `sub`，天然行级隔离；router 内注释豁免理由
  （check_conventions AUTH_PATTERNS 白名单已含 get_current_user）
- `routers.py` 注册 `prefix="/api/dashboard"`

### 后端测试 `tests/test_dashboard_preference.py`

- GET 无配置 → data 为 null
- PUT → GET roundtrip 一致；再次 PUT 覆盖（upsert 幂等）
- DELETE 后 GET 回 null
- 用户 A 的配置对用户 B 不可见（行级隔离）
- 未带 token → 401/403
- 非法 payload（hidden 不是列表 / 超长）→ 422

## 前端设计

### 文件结构（Dashboard.vue 1244 行 → 拆分）

```
views/dashboard/
├── Dashboard.vue                  # 薄壳：组合 sections + aurora 背景 + 编辑态编排
├── cards.js                       # 卡片注册表（唯一真相源）
├── composables/
│   ├── useDashboardData.js        # 既有，不动
│   └── useDashboardConfig.js      # 配置加载/合并/编辑态/保存
└── components/
    ├── HeroSection.vue            # 深色玻璃 Hero（含几何装饰）
    ├── TodoAlerts.vue             # 玻璃变体待办条
    ├── MetricsGrid.vue            # 指标卡网格（registry 循环 + draggable）
    ├── ActionsGrid.vue            # 快捷操作网格（registry 循环 + draggable）
    ├── OverviewPanels.vue         # 最近动态 + 状态分布（玻璃面板）
    └── CustomizeBar.vue           # 编辑态底部操作条（恢复默认/取消/保存）
```

- `api/dashboard.js`：getDashboardPreference / saveDashboardPreference / resetDashboardPreference
- `clients.js` 登记 `dashboardClient`（baseURL /api/dashboard, timeout 15000）

### 注册表 cards.js

```js
export const METRIC_CARDS = [
  { key: 'incomplete', label: '待补充归属', perms: ['customer:read'], dot: 'amber',
    value: d => d.incompleteCount, highlight: d => d.incompleteCount > 0, ... },
  // ... 7 张
]
export const ACTION_CARDS = [
  { key: 'payment_sync', name: '回款同步', desc: '拉取业务系统数据',
    icon: 'Refresh', route: '/payment/sync', perms: ['payment:read'], bg: 'gold' },
  // ... 14 张
]
```

value/highlight 用函数取自 useDashboardData 的返回，MetricsGrid 内解引用。
badge（审批队列角标）等个别特化以可选字段声明。

### useDashboardConfig.js

- state：`prefs`（服务端真相）、`editing`、`draft`（编辑中副本）
- 初始化：先读 localStorage 镜像（key 含 user_id）立即应用 → GET 覆盖 → 写回镜像
- `visibleCards(section, allCards)`：权限过滤 → order 排序（未知 key 追加尾部）→ 非编辑态再过滤 hidden
- 编辑流：enterEdit（深拷贝 draft）→ 拖拽/toggle 改 draft → save（PUT+镜像）/ cancel（丢弃）/ reset（DELETE+清镜像）
- 保存失败：feedback 报错，保持编辑态不丢 draft

### Liquid Glass 视觉

tokens.css 新增（全局 token，rule 13）：

```css
--glass-bg:            rgba(255, 255, 255, 0.62);
--glass-bg-strong:     rgba(255, 255, 255, 0.78);
--glass-border:        rgba(255, 255, 255, 0.65);
--glass-highlight:     inset 0 1px 0 rgba(255, 255, 255, 0.8);
--glass-blur:          20px;
--glass-shadow:        0 8px 32px rgba(26, 24, 22, 0.08);
--glass-shadow-hover:  0 12px 40px rgba(26, 24, 22, 0.12);
--glass-dark-bg:       rgba(20, 18, 16, 0.85);
--glass-dark-border:   rgba(245, 203, 92, 0.18);
```

- aurora：`.dashboard-aurora` 三个 radial-gradient 光斑（金 #F5CB5C、主金 #D4941C、冷蓝 #6B8CBA，透明度 ≤0.12），`filter: blur(80px)`，transform 慢漂 60~90s 交错，`pointer-events:none`
- 玻璃卡：`background var(--glass-bg)` + `backdrop-filter blur(var(--glass-blur)) saturate(1.5)` + 描边 + 顶部内高光；`@supports not (backdrop-filter: blur(1px))` 降级 `var(--card-bg)`
- Hero：深色玻璃 `var(--glass-dark-bg)` + blur，金色几何装饰保留
- 待办条：warning/danger 色调玻璃变体（色底透明度 0.55 + blur）
- 性能红线：backdrop-filter 静态存在但**不参与动画**；动画只碰 transform/opacity

### 动效（Emil 框架逐条）

| 项 | 值 |
|----|-----|
| 入场 stagger | 250ms / translateY(8px) / 间隔 50ms / `cubic-bezier(0.23, 1, 0.32, 1)` |
| 卡片 hover | `transition: transform 200ms, box-shadow 200ms, border-color 200ms` 同曲线；`translateY(-2px)`；gated `@media (hover:hover) and (pointer:fine)` |
| 可点卡片按压 | `:active { transform: scale(0.98) }` 120ms |
| 拖拽 FLIP | vuedraggable `animation: 150` |
| 编辑态切换 | 控件 opacity/transform 180ms ease-out，不做 wiggle |
| donut | 首次 draw-in 400ms ease-out（stroke-dasharray 过渡） |
| reduced-motion | aurora 停漂；入场只保留 opacity；hover 不位移 |

## 交付清单

1. 分支 `claude/dashboard-liquid-glass`，当天 push -u（备份性）
2. 小步提交：spec → 迁移+后端 → 前端 api/registry/config → 组件拆分+玻璃视觉 → 测试 → docs
3. 迁移创建后本地 `alembic upgrade head`（共库直接执行，2026-07-12 指令）
4. DoD：check_conventions / pytest / npm run build 实跑贴证据
5. 对抗性审查（必触发：跨 3+ 文件 + 迁移）：边界条件、并发写（同一用户双端保存）、幂等、前后端契约
6. 文档：api-reference.md 加 3 端点；database.md 加表；auto-memory `project_dashboard_module.md`
