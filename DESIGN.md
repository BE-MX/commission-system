# Design System — LeShine Ark Platform

## Product Context
- **What this is:** 莱莎方舟平台 — 提成管理、物流跟踪、客户归属、设计预约一体化后台
- **Who it's for:** 莱莎发制品内部员工（业务员、主管、财务、管理员）
- **Project type:** 企业后台管理系统 (SPA)

## Aesthetic Direction
- **Direction:** Luxury/Utilitarian — 深色侧边栏 + 浅色内容区，金色点缀，grain 纹理
- **Decoration level:** intentional — 纹理叠加、几何装饰、卡片阴影层次
- **Mood:** "专业但有温度" — 不是冷冰冰的企业后台，是经过精心打磨的内部工具

## Typography
- **Display/Hero:** Outfit — 几何无衬线，粗体有力量感，用于标题、标签、按钮、导航
- **Body:** DM Sans — 柔和的人文无衬线，用于正文、表格数据、表单内容
- **UI/Labels:** Outfit（与 Display 同）
- **Data/Tables:** DM Sans + tabular-nums（保证数字列对齐）
- **Code:** 未使用
- **Loading:** Google Fonts CDN (`<link>` in index.html)
- **Scale:**
  - Hero title: 28px / 800
  - Page title: 17px / 700
  - Section heading: 15px / 700
  - Body text: 14px / 500
  - Table data: 13px / 400
  - Label/caption: 12px / 600
  - Micro label: 10-11px / 700, letter-spacing 0.1em+, uppercase

## Color
- **Approach:** restrained — 一个金色主色 + 中性色系统，颜色有语义不随意
- **Primary:** #D4941C — LeShine Gold，用于主按钮、链接、强调元素
- **Primary Hover:** #BB8218
- **Primary Light:** rgba(212,148,28,0.08) — hover 背景、输入聚焦光晕
- **Gold Accent:** #F5CB5C — 侧边栏活跃态、标签、徽章、装饰
- **Gold Soft:** #FDF4DC — 极浅金底色（hover/徽章；表格 header 已改用冷灰）
- **Danger:** #DC3545 / #C0392B (dark variant)
- **Success:** #2D9F6F / #1E7D50 (text)
- **Warning:** 使用 Gold 色系替代 — rgba(245,203,92,0.15) 背景 + #8B6914 文字
- **Neutrals (cool gray):**
  - Text primary: #1a1a2e
  - Text secondary: #4a5568
  - Text muted / placeholder: #a0aec0
  - Border: #e2e5ef
  - Border hover: #c5cce0
  - Page background: #f0f2f7
  - Card background: #ffffff
  - Toolbar / Table header: #fafbfe
  - Table row hover: #fef9f0（极浅金，行 hover 时使用）
- **Dark sidebar:**
  - From: #141210
  - To: #1E1B18
  - Menu text: #9C9590
  - Menu hover text: #D4C4A8
  - Active text: #F5CB5C

## Spacing
- **Base unit:** 4px
- **Density:** comfortable
- **Scale:**
  - 2xs: 2px
  - xs: 4px
  - sm: 8px
  - md: 16px
  - lg: 24px
  - xl: 32px
  - 2xl: 48px

## Layout
- **Approach:** grid-disciplined — 左侧固定侧边栏 + 右侧弹性内容区
- **Sidebar:** 240px（展开）/ 68px（折叠），dark gradient 背景
- **Header:** 56px 高，白色背景，底部 border
- **Content padding:** 24px 28px
- **Max content width:** 1440px
- **Grid:** 表格页用 100% 宽度；Dashboard 用 3 列 metric + 2 列 action grid
- **Border radius:**
  - Card/button: 12px (card-radius)
  - Input/select/dropdown: 8px
  - Tag/badge: 6px
  - Dialog/drawer: 16px
  - Menu item: 10px
  - Alert: 10px

## Motion
- **Approach:** intentional — 有意义的过渡，不滥用动画
- **Page transition:** fade + slide up (opacity 0→1, translateY 12px→0), 300ms ease
- **Stagger:** 页面子元素依次入场，间隔 70ms
- **Card hover:** translateY(-2px) + shadow 加深, 250ms ease
- **Sidebar toggle:** width transition 300ms cubic-bezier(0.4, 0, 0.2, 1)
- **Menu item hover:** background color 200ms ease
- **Input focus:** box-shadow ring 200ms ease

## Component Patterns
- **Toolbar:** sticky top bar, card 样式（白底 + border + shadow），包含筛选和操作按钮
- **Data table:** 无斑马纹，hover 高亮（`#fef9f0` 极浅金背景），header 用 `#fafbfe` 冷灰底色 + 13px/600 次字色（非 uppercase）。详细规范见「List Page Spec」一节
- **Status tags:** 自定义 Element Plus tag 颜色，语义明确（info/primary/success/danger/warning）
- **Button System:** 见下方「Button Spec」完整规范
- **Metric card:** 大数字 + 状态圆点 + 操作链接，hover 上浮
- **Dialog:** 16px 圆角，header 带 bottom border

## Button Spec

按钮统一使用 **Glass Button** 设计体系（浅色毛玻璃风格），覆盖中后台所有常见按钮场景。

### 尺寸体系

| 尺寸 | 名称 | 高度 | 内边距 | 字号 |
|------|------|------|--------|------|
| `xs` | 极小 | — | — | 11px |
| `sm` | 小 | — | — | 12px |
| `md` | 中（默认） | 36px | — | 13px |
| `lg` | 大 | — | — | 13px |
| `xl` | 极大 | — | — | 14px |

当前项目统一使用 `md`（36px）作为工具栏及操作按钮高度。

### 圆角体系

`none` / `sm` / `md` / `lg`（默认） / `xl` / `full`

列表页工具栏按钮默认 `12px`（对应 `lg`），操作列 link 按钮无圆角。

### 变体与适用场景

| 变体 | 风格 | 适用场景 |
|------|------|----------|
| `primary` | 品牌金渐变填充 | 主操作、提交、确认 |
| `secondary` | 白色毛玻璃 + 灰色边框 | 次操作、批量操作 |
| `outline` | 透明底 + 灰色描边 | 筛选、配置类操作 |
| `ghost` | 完全透明，hover 才显背景 | 工具栏、弱操作 |
| `soft` | 浅金底色 | 收藏、标记类柔和操作 |
| `link` | 纯文字 + hover 下划线 | 操作列跳转、查看 |
| `danger` | 红色渐变 | 删除、禁用、强警告 |
| `success` | 绿色渐变 | 保存成功、通过、启用 |
| `warning` | 橙色渐变 | 提交审核、提醒 |
| `info` | 蓝色渐变 | 帮助、提示、信息 |
| `white` | 清透白玻璃 + 弥散阴影 | 叠加在复杂背景上 |

### 列表页按钮映射

**工具栏按钮**
- 主操作：`variant="primary"`（金色渐变）
- 次操作：`variant="secondary"`（白底 + 边框）
- 筛选/切换：`variant="outline"` 或 `variant="ghost"`

**操作列按钮**
- 编辑/查看：`variant="link"` + 金色文字 + `<el-icon>` 前缀图标
- 通过/启用：`variant="link"` + `type="success"`
- 拒绝/禁用：`variant="link"` + `type="danger"`
- 统一要求：图标 + 文字，**禁止** `size="small"`

### 特殊状态

- **加载状态**：`isLoading` 自动显示旋转图标
- **禁用状态**：`isDisabled` 自动降低透明度 + 去色
- **激活状态**：`active` 显示品牌色 ring 聚焦环
- **图标组合**：支持 `leftIcon` / `rightIcon` / 纯图标按钮
- **全宽按钮**：`fullWidth` 撑满容器（表单底部提交场景）
- **阴影层级**：`shadow` 支持 `sm/md/lg/xl`

## List Page Spec

所有列表页（含表格的页面）必须遵循本规范。样式优先通过全局类实现，页面级只做最小化定制。

### 1. 表格基础

**DOM 结构**

```html
<div class="table-card">
  <el-table
    :data="tableData"
    v-loading="loading"
    :max-height="maxHeight"
    class="list-table"
    border
  >
    ...
  </el-table>
</div>
```

- **必须**包裹在 `.table-card` 中（圆角白底卡片）
- **必须**设置 `class="list-table"`
- **必须**保留 `border`（提供纵向边框 + 列宽拖拽把手）
- **禁止**使用 `stripe`（无斑马纹）

**列宽规则**

| 规则 | 说明 |
|------|------|
| 不固定 `width` | 全部使用 `min-width` + `max-width` |
| 下限保证表头完整 | `min-width` 必须 ≥ 表头文字完整显示所需宽度 |
| 上限防溢出 | `max-width` = `min-width` × 1.3 ~ 2.0 |
| 纯文本列 | 全部加 `show-overflow-tooltip` |
| 默认左对齐 | **禁止**使用 `align="center"`，全表左对齐 |

估算公式（13px 字体）：中文每字 ≈ 13px；cell 左右 padding 共 24px；`min-width = 字数 × 13 + 24 + 20(余量)`。

**行高**

- cell padding: `10px 12px`（上下 10px，左右 12px）
- 单行显示，**禁止**换行

### 2. 字体与排版

| 元素 | 字号 | 字重 | 颜色 | 其他 |
|------|------|------|------|------|
| 表头 | 13px | 600 | `var(--text-secondary)` | 非 uppercase，无 letter-spacing |
| 内容 | 13px | 400 | `var(--text-primary)` | — |
| 链接/主键 | 13px | 600 | `var(--color-primary)` | — |
| 操作按钮文字 | 13px | 500 | `var(--color-primary)` | link 样式 |

### 3. 标签与徽章

**状态标签（pill）**

```html
<el-tag size="small" effect="plain">...</el-tag>
```

- 圆角 `9999px`（胶囊）、padding `2px 10px`、字号 12px、字重 500
- 用 Element Plus `type` 控制颜色（全局已覆盖为品牌色）

**属性徽章**

仅用于「开发/分配」类业务属性：

```html
<span class="badge-dev">开发</span>
<span class="badge-assign">分配</span>
```

token 见 `tokens.css` 的 `--badge-dev-*` / `--badge-assign-*`。

### 4. 按钮

**操作列按钮**

```html
<el-button link type="primary" @click="...">
  <el-icon><Refresh /></el-icon> 刷新
</el-button>
```

- **禁止** `size="small"`
- 必须图标 + 文字
- link 样式，金色文字

**工具栏按钮**

- 次操作：默认样式（白底 + 边框）
- 主操作：`type="primary"`（金色渐变）
- 统一高度 36px

### 5. 快速检查清单

新增/修改列表页时逐项核对：

- [ ] 表格包裹在 `.table-card` 中
- [ ] 表格有 `class="list-table"` + `border`
- [ ] 无 `stripe`
- [ ] 列宽用 `min-width` + `max-width`，无固定 `width`
- [ ] 无 `align="center"`
- [ ] 纯文本列有 `show-overflow-tooltip`
- [ ] 操作按钮无 `size="small"`，带图标
- [ ] 状态 tag 用 pill 样式（如需）
- [ ] 不在 scoped style 里重复写表格样式

## Login Page — Kimi Design (Dark Theme)

登录页采用独立的深色科技风设计，与内部页面的 Luxury/Utilitarian 风格区分。

### 登录页设计语言
- **背景:** 纯黑 `#0a0a0f`，Canvas 实时渲染世界地图粒子动效
- **主题:** Glass Morphism — 半透明模糊卡片，浮于地图动效之上
- **色彩:**
  - 金色: `#d4af6e` / `#a08040`（与内页 #D4941C 不同，更柔和）
  - 青色: `#00d4ff`（装饰、粒子、大洋点阵）
  - 红色: `#ff6b6b`（青岛位置标记）
  - 绿色: `#54d468` / 橙色: `#ff9f43`（目的地高亮）

### 核心 CSS 类（来自 `kimi-design.css`）
| 类名 | 用途 |
|------|------|
| `.glass-card` | 玻璃态容器：`backdrop-filter: blur(20px)`，半透明深色背景 |
| `.gold-glow` | 金色外发光：`box-shadow` 三层叠加，用于登录卡片 |
| `.tech-btn-primary` | 主按钮：金色渐变 `#d4af6e→#a08040`，深色文字 |
| `.tech-btn-secondary` | 次要按钮：半透明白色描边 |
| `.tech-input` | 输入框：近透明底色，聚焦时金色边框 + 光晕 |
| `.badge-cyan/gold/green/amber` | 标签徽章，对应四种目的地颜色 |

### Canvas 世界地图动效
- **组件:** `frontend/src/components/WorldMapCanvas.vue`
- **渲染内容:** 大陆点阵（land/ocean 区分着色）、经纬度网格、星空闪烁
- **粒子轨迹:** 从青岛 (120.383°E, 36.067°N) 出发，沿贝塞尔曲线飞向 4 个目的地
- **涟漪效果:** 青岛位置每 4 秒发出一次扩散圆环
- **目的地:** 北美 (cyan)、欧洲 (gold)、中东 (amber)、澳洲 (green)

### 入场动画规范
| 类名 | 效果 | 时长 |
|------|------|------|
| `.animate-fade-in` | opacity 0→1 | 600ms |
| `.animate-fade-in-left` | opacity 0→1 + translateX(-30px→0) | 800ms |
| `.animate-fade-in-right` | opacity 0→1 + translateX(30px→0) | 800ms |
| `.animate-fade-in-up` | opacity 0→1 + translateY(30px→0) | 800ms |

延迟类：`.delay-200`、`.delay-300`、`.delay-350`、`.delay-500`、`.delay-650`

所有动画元素初始必须加 `.will-animate`（`opacity: 0`），配合延迟类实现交错入场。

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-29 | 统一 DESIGN.md，提取现有设计系统 | 之前设计变量分散在 App.vue 和各组件 scoped 样式中，需要集中管理 |
| 2026-04-29 | 字体 Outfit + DM Sans 已确认 | 系统已在使用，直接记录为正式方案 |
| 2026-04-29 | 语义色 Warning 复用 Gold 色系 | 系统已有实现，统一记录 |
| 2026-04-29 | 操作列按钮统一规范 | link style + `<el-icon>` 前缀图标 + 文字，无 `size` 属性；适用所有表格操作列；参考基准：CommissionBatch.vue |
| 2026-05-01 | 登录页采用 kimi 深色科技风设计 | 与内部页面差异化，营造进入平台的仪式感；Canvas 世界地图强化全球业务属性 |
| 2026-05-01 | 中性色从暖灰切换到冷灰（蓝调） | tokens.css 已落地新调色（页底 #f0f2f7、文字 #1a1a2e、表头 #fafbfe），DESIGN.md 同步对齐；列表页规范从 frontend/DESIGN.md 合并为 List Page Spec 节 |
