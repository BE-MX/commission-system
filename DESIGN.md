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
- **Page transition:** 主站高频页面切换只淡入/淡出，进入 120ms、退出 80ms；不位移业务表格。
- **Stagger:** 业务表单和列表不延迟显示；低频介绍场景才使用短交错入场。
- **Card hover:** translateY(-2px) + shadow 加深, 250ms ease
- **Sidebar toggle:** width transition 300ms cubic-bezier(0.4, 0, 0.2, 1)
- **Menu item hover:** background color 200ms ease
- **Input focus:** box-shadow ring 200ms ease
- **Reduced motion:** 主站全局缩短 CSS 动画/过渡并关闭平滑滚动；组件中的持续 JS/Canvas 动画须自行遵循系统偏好和页面生命周期。GlassButton 在触屏、键盘聚焦及减少动态模式不产生位移；加载状态始终保留可读文字。

## Component Patterns
- **Toolbar:** sticky top bar, card 样式（白底 + border + shadow），包含筛选和操作按钮
- **Data table:** 无斑马纹，hover 高亮（`#fef9f0` 极浅金背景），header 用 `#fafbfe` 冷灰底色 + 13px/600 次字色（非 uppercase）。详细规范见「List Page Spec」一节
- **Status tags:** 自定义 Element Plus tag 颜色，语义明确（info/primary/success/danger/warning）
- **Button System:** 见下方「Button Spec」完整规范
- **Metric card:** 大数字 + 状态圆点 + 操作链接，hover 上浮
- **Dialog:** 16px 圆角，header 带 bottom border
- **Small viewport:** 主站窄屏导航使用抽屉，页面使用完整可用宽度；筛选栏允许换行，多列表单和上传/配置双栏转为单列。保留表格内部横向滚动，不通过隐藏整个页面溢出来掩盖不可达控件。
- **Overlay boundaries:** 非全屏弹窗最大宽度为视口减 24px，最大高度为动态视口减 32px；正文滚动、页头页尾保留。详情抽屉挂到 body，最大宽度不超过视口。欢迎提示使用标准 Dialog，支持焦点管理、Escape 与原生复选框。
- **PM overlays:** PM 站保留独立设计系统；Modal/Drawer 共用焦点栈，只有顶层处理 Tab/Escape，关闭后恢复触发控件焦点及原有页面滚动状态。

## Liquid Glass 页面材质体系（2026-07-25 起）

工作台首发的整页材质方案，已推广至订单发票管理及备货/售后/物流/设计预约模块全部列表页。材质配方源自「方案B-赛事直播频道-v2」大屏（渐变玻璃卡 + 彩色环境阴影 + 斜向光带），色调保持品牌暖金。

实现载体：`frontend/src/styles/liquid-glass.css`（main.js 全局引入）+ `tokens.css` 的 `--dash-glass-*` / `--dash-wash-*` / `--dash-aurora-*` / `--dash-card-radius` 令牌（`--dash-` 前缀是历史命名，令牌本身已跨页面共享）。

### 命名红线

禁止新增裸 `--glass-*` 变量或 `.glass-card` 类名：`kimi-design.css`（登录页深色主题）在 `:root` 重定义了 `--glass-bg`/`--glass-border` 且 main.js 后加载，会覆盖同名令牌把卡片染成深灰（2026-07-25 实翻车）。页面级玻璃一律用 `--dash-glass-*` 令牌 + `.lg-*` 类。

### 极光 backdrop（.lg-aurora）

页面根容器 `position: relative`，第一个子元素放：

```html
<div class="xxx-aurora lg-aurora" aria-hidden="true">
  <div class="lg-aurora__blob lg-aurora__blob--gold" />
  <div class="lg-aurora__blob lg-aurora__blob--amber" />
  <div class="lg-aurora__blob lg-aurora__blob--peach" />
</div>
```

- **底色 wash**：`linear-gradient(155deg, #fdf8ec 0%, #f8f3ea 52%, #f9efe7 100%)`（暖米白→暖桃）
- **三色 wash 光斑（全部静态）**：金 `rgba(245,203,92,.55)` 右上 640px / 琥珀 `rgba(230,160,60,.45)` 左中 560px / 蜜桃 `rgba(242,165,110,.38)` 右下 600px，径向渐变 68% 处衰减至透明
- **斜向光带**：两条 115° 高光带横扫（白 .55→.18、金 .30→.10）
- **底缘淡出**：最后 260px 渐出到 `--page-bg`，内容不满一屏时无硬接缝
- **页面级外溢**：scoped 里写 `.xxx-aurora { inset: -24px -28px; }`，盖住 main-content 的 padding 环
- **内容层叠**：点名列出内容块（页头/卡片栅格/面板/分页）设 `position: relative; z-index: 1`。**禁止** `> :not(.lg-aurora)` 通配——el-drawer/el-dialog 默认 `append-to-body=false` 就地渲染，通配选择器会覆盖 `.el-overlay` 的 `position: fixed`，抽屉打开后不可见（2026-07-25 实翻车）

### 玻璃卡片（.lg-card）

| 参数 | 值 |
|------|------|
| 背景 | `linear-gradient(160deg, rgba(255,255,255,.78), rgba(255,255,255,.5))`（0.78→0.5 白磨砂渐变） |
| 描边 | `1px solid rgba(255,255,255,.85)`，hover `.95` |
| 圆角 | `--dash-card-radius: 16px` |
| 阴影 | `0 10px 30px rgba(146,103,24,.14)`（暖金调彩色阴影，**不用灰色**）+ 顶部内高光 `inset 0 1px 0 rgba(255,255,255,.9)` |
| hover 阴影 | `0 14px 36px rgba(146,103,24,.18)` |
| hover 位移 | `translateY(-2px)`（仅 `@media (hover:hover) and (pointer:fine)`）；`.is-static` 非交互卡只加深阴影不上浮 |
| 按压 | `scale(.98)`（`:active`） |
| 过渡 | 200ms `cubic-bezier(0.23, 1, 0.32, 1)`，只 transition 具体属性不用 all |

### 表格融入玻璃

表格面板容器用 `--dash-glass-bg` 同款渐变 + 上述描边/阴影/圆角（scoped 覆盖全局 `.table-card` 白底），内部 el-table 透明化：

```css
.xxx-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}
```

- 工具栏条：`background: rgba(255,255,255,.4)` + 底部 1px `var(--border-color)` 分隔线
- **固定列必须磨砂不透明**（Element 2.13 起固定列是 sticky 单元格 + `background: inherit`，行透明时滑到它下面的内容会重影；Element 的 hover 规则还会把固定列刷回半透明白，必须单独覆盖）：

```css
.xxx-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.xxx-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.xxx-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }
```

### 页头按钮

页头/工具栏主按钮用 GlassButton（见 Button Spec）：主操作 `variant="primary"`（金渐变 `#D4941C→#BB8218`），次操作 `variant="secondary"`（半透明白磨砂），替换 Element 默认蓝/白按钮；`v-permission` 行为不变。操作列 link 按钮维持 List Page Spec 不变。

### 性能红线（2026-07-25 滚动卡顿的教训）

- **backdrop 全静态**：禁止给极光光斑加无限位移动画——动态 backdrop 会让与之重叠的 `backdrop-filter` 表面每帧重采样，合成器持续满负载、滚动掉帧
- **大面积重复卡片/表格禁用 backdrop-filter**（20+ 张卡滚动时逐帧重采样必卡）；实时模糊只留给 ≤5 个小浮层（Hero、提醒条、悬浮按钮），规格 `blur(16px) saturate(1.4~1.6)`
- **禁止给大面积元素叠 `filter: blur()`**——柔和效果一律用大半径径向渐变实现

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

规范条目用以下标注区分执行方式（2026-09-30 起，适用于 List Page Spec 及其后各组件规范节）：

- **[门禁]**：已由 `scripts/audit_frontend_ui.py` / `check_conventions.py` 机器强制，提交即检查。现有表格门禁：`stripe` / `border` / `list-table` 类 / 固定 `width` / `align="center"` / 按钮 `size="small"`
- **[可门禁]**：可静态判定的条目，已全部接入 `scripts/audit_frontend_ui.py`（2026-09-30，15 项度量）：存量计数冻结进债务基线、变动即报 stale，白名单项按违例计数冻结；标注保留，用于区分其「冻结存量、渐进消化」与 **[门禁]** 「硬失败」的性质差异
- **[评审]**：无法静态判定，靠 code review 与 QA 对照本节核查

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

操作/处理列统一加 `class-name="table-action-column"`，布局由 `frontend/src/styles/table-actions.css` 管理：按钮按原顺序换行，单元格随内容增高，不继承普通文本列的单行省略。需要额外包裹按钮时使用 `<div class="table-actions">`，不要另设 `nowrap`、固定高度或裁切。长按钮文字允许换行，间距统一使用 `gap`，不叠加相邻按钮的 margin。

表格容器宽度不超过 768px 时取消左右固定列，通过表格横向滚动访问所有列，避免手机和窄抽屉中固定列互相覆盖；桌面宽表仍保留原固定列配置。普通文本列继续按原规则省略，既有下拉菜单、权限、加载和禁用状态不变。PM 站使用独立样式实现相同的换行与横向可达原则。

新增操作列后运行 `node --test frontend/tests/tableActions.test.mjs` 检查接入。浏览器布局验证页见 `frontend/tests/fixtures/table-actions/index.html`（Vite 开发服务下访问；隔离数据，不调用业务 API），覆盖多按钮、长文案、窄图标列、下拉及确认弹层。

**工具栏按钮**

- 次操作：默认样式（白底 + 边框）
- 主操作：`type="primary"`（金色渐变）
- 统一高度 36px

### 5. 筛选区（FilterBar）

职责划分（借鉴 Art Design Pro `ArtSearchBar`）：**页面负责筛选字段与提交逻辑，规范负责布局、展开收起与操作区一致性**。现状各页写法不一（`.toolbar` / `el-row` / 原生 form / 侧栏标签云并存，控件内联宽度，约一半页面无重置），按本节收敛。

**布局**

- 筛选区统一放在全局 `.toolbar`（`app.css`）容器内，flex 横向排列、允许换行；**禁止**另造 `el-row` 分栏或原生 `<form>` 容器 **[评审]**
- 控件高度统一 36px（与按钮 md 对齐）；**禁止** `el-input` / `el-select` / `el-date-picker` 使用 `size="small"` **[可门禁：`_tags` 扫描这三类标签的 `size="small"`，存量计数进债务基线]**
- 控件宽度只用三档：`160px`（短文本/状态）/ `200px`（默认）/ `280px`（日期范围）；**禁止**内联 `style="width:…"` 写任意值 **[可门禁：`.toolbar` 区块内控件标签的 `style=` 宽度计数进债务基线]**

**操作区**

- 「查询 + 重置」必须成对出现，固定在筛选区末尾；查询用主按钮（GlassButton `variant="primary"`），重置用次按钮 **[评审]**
- 筛选字段 > 4 个时，默认只展示首行，其余收进「展开/收起」切换；参考实现 `views/asset/useAssetTagFilters.js` **[评审]**
- 输入类控件 `@keyup.enter` 触发查询 **[评审]**

### 6. 分页

现状 `el-pagination` layout 有 5 种并存，按本节收敛为唯一形态；存量页面在下次触碰时补齐，不一蹴而就。

- layout 固定为 `total, sizes, prev, pager, next`；`page-sizes` 固定 `[20, 50, 100]`，默认 20 **[可门禁：`_tags("el-pagination")` 的 `layout` 属性白名单比对]**
- 类名统一 `class="pager"`，置于表格卡片内底部 **[评审]**
- 分页状态走 `useListPage.js`（新列表页必须使用），不自建分页状态 **[评审]**

### 7. 表格三态（loading / empty / error）

借鉴 Art Design Pro 通用组件状态清单，所有列表表格必须显式处理三种状态：

- **loading**：`v-loading`（全站既有做法，不变）
- **empty**：统一用 `el-table` 的 `empty` 插槽或 `el-empty`，文案「暂无数据」，有筛选条件时给出「重置筛选」引导；**禁止**新增手写「暂无…」裸 div，`empty-text` 属性不再新增 **[可门禁：`empty-text=` 属性计数进债务基线冻结]**
- **error**：接口错误提示统一走 `api/request.js` 拦截器 + `utils/feedback.js`，页面 `catch` 里只处理业务回滚，不各自弹裸消息（见 Feedback Spec）**[评审]**

### 8. 快速检查清单

新增/修改列表页时逐项核对：

- [ ] 表格包裹在 `.table-card` 中
- [ ] 表格有 `class="list-table"` + `border`，无 `stripe` **[门禁]**
- [ ] 列宽用 `min-width` + `max-width`，无固定 `width`、无 `align="center"` **[门禁]**
- [ ] 纯文本列有 `show-overflow-tooltip`
- [ ] 操作按钮无 `size="small"`，带图标 **[门禁]**
- [ ] 筛选区在 `.toolbar` 内，控件无内联宽度、无 `size="small"`
- [ ] 「查询 + 重置」成对出现；筛选字段 > 4 个时有展开/收起
- [ ] 分页 layout 为 `total, sizes, prev, pager, next`
- [ ] 表格有统一 empty 处理，无新增 `empty-text`
- [ ] 状态 tag 用 pill 样式（如需），状态映射查域字典
- [ ] 不在 scoped style 里重复写表格样式

## Dialog & Form Spec

弹窗与表单的用途、尺寸与底部操作区统一约定。现状：`el-dialog` 宽度手写值多达 11 档、`el-form` label 对齐两种并存（145 个表单仅 47 个显式 `label-position`）、底部按钮区类名三套并存，按本节收敛。

### 1. 用途边界

| 场景 | 组件 |
|------|------|
| 新增 / 编辑 / 短流程操作 | `el-dialog` |
| 详情 / 预览 / 长内容查看 | `el-drawer`，新页面统一走 `components/DetailDrawer.vue` |
| 危险确认 | `utils/feedback.js` 的 `confirmDanger`，不自建确认弹窗 |

**[评审]**；存量混用（如 drawer 做编辑器）在下次触碰时归位。

### 2. 宽度档位

- `el-dialog` 宽度只允许三档：`480px`（简单表单/确认）/ `640px`（标准表单）/ `760px`（宽表单、多列栅格）**[可门禁：`_tags("el-dialog")` 的 `width` 值白名单比对，其余值计数进债务基线]**
- `el-drawer` 默认 `640px`（DetailDrawer 默认值即锚点），宽详情可用 `760px`；**禁止**新增 `94%` 等百分比尺寸 **[可门禁：`_tags("el-drawer")` 的 `size` 值白名单比对]**
- 仍受「Overlay boundaries」节约束：最大宽度为视口减 24px

### 3. 表单

- 弹窗内表单统一 `label-position="top"`（FilterBar 筛选用行内控件，不用 `el-form-item` 标签）**[评审]**；存量 right 对齐表单在下次触碰时迁移
- 通用校验规则（手机号、邮箱、金额等）收敛到共享 validators（新建 `utils/validators.js`，参照 `utils/datetime.js` 的收敛路径），新表单不自写正则 **[可门禁：validators.js 落地后，页面内手机号等正则字面量计数冻结]**
- 必填标记、错误提示位置沿用 Element Plus 默认，不自定义 **[评审]**

### 4. 底部按钮区

- dialog：统一 `#footer` 插槽 + `class="dialog-footer"`，取消在左、主按钮在右 **[评审]**；`form-actions` / `drawer-actions` 别名不再新增 **[可门禁：后两者类名计数进债务基线冻结]**
- drawer：用 DetailDrawer 内置 footer，不另写按钮区
- 提交按钮必须带 loading（GlassButton `isLoading` 或 `el-button :loading`），防重复提交 **[评审]**

## Status Badge & 状态字典

状态色的唯一职责是「让状态一眼可辨」，颜色映射必须单点维护。

- **状态字典**：每个业务域在自己的 `use*.js` 或共享字典文件中维护 `状态枚举 → { label, tagType }` 映射；新增状态字段必须先登记字典 **[评审]**。参照 PM 站 `utils/labels.js`（标签 + 语义色单点维护，「状态色仅用于徽标」纪律）
- **渲染**：表格/详情中状态一律用 pill tag（见 List Page Spec 第 3 节），`type` 从字典取；存量模板里静态 `type="success"` 等裸映射在触碰时迁入字典 **[可门禁：`el-tag` 标签上静态 `type=` 属性计数进债务基线，只许降不许升]**
- 后续可提取 PM 站 `StatusBadge.vue` 思路做主站统一封装；两站 token 不互通的现状维持不变

## Feedback Spec

消息、确认、加载、空态的统一出口。现状 `utils/feedback.js` 已建成但裸调用过半（约 497 处裸 ElMessage/ElNotification、105 处裸 ElMessageBox.confirm），按本节收敛存量。

- **操作反馈**：成功/失败消息一律 `utils/feedback.js` 的 `msgSuccess` / `msgError`；**禁止**新代码直接 `import { ElMessage } / ElNotification` **[可门禁：`.vue`/`.js` 中两者 import 计数进债务基线，只许降不许升]**
- **危险确认**：删除、禁用、驳回等必须 `confirmDanger`，不裸调 `ElMessageBox.confirm` **[可门禁：ElMessageBox import 计数冻结，同上]**
- **接口错误**：统一由 `api/request.js` 拦截器弹出；页面 `catch` 里只处理业务回滚，不重复提示 **[评审]**
- **加载**：按钮提交带 loading；表格 `v-loading`；首屏大区块可用 `el-skeleton`（适度使用，不为每个列表补骨架）**[评审]**
- **空状态**：列表/卡片区统一 `el-empty` 或组件 empty 插槽，文案「暂无数据」+ 可选引导操作；手写「暂无…」裸 div 不再新增 **[评审]**
- PM 站对应纪律：`toast.success/error` + `EmptyState.vue`，维持不变

## Format Spec（金额与数字）

时间是全站规范执行最好的样例（`utils/datetime.js` + 机器检查），金额按同一路径收敛。

- **金额**：收敛到单一格式化出口（新建 `utils/money.js`：统一货币符号、千分位、两位精度）；新代码**禁止**新增 `toLocaleString` / `Intl.NumberFormat` / 裸 `toFixed(2)` 格式化金额 **[可门禁：三者在 `frontend/src` 的出现计数进债务基线冻结；现状 4 份 money 实现并存、24+ 处散写]**。显示约定：列表内默认两位小数 + 千分位；负金额前置 `-`
- **数字列**：表格数字沿用 DM Sans + tabular-nums（见 Typography）；维持全表左对齐红线，数字列暂不强制右对齐
- **日期控件**：`el-date-picker` 的 `value-format` 统一 `YYYY-MM-DD`（纯日期）与 `YYYY-MM-DD HH:mm:ss`（日期时间），不新增 ISO `T` 格式 **[可门禁：`_tags("el-date-picker")` 的 `value-format` 白名单比对]**

## Component Adoption（复用与晋升）

借鉴 Art Design Pro / vue-pure-admin 的组件治理方式，解决「基建已建成但采用率低」问题（`useListPage` 仅 27 个文件引用、`DetailDrawer` 仅 22 个）。

### Element Plus 使用三原则

1. 动手前先查项目已有高层封装：`AppUpload`、`DetailDrawer`、`utils/feedback.js`、`useListPage.js`、`GlassButton`；有封装必须用封装 **[评审]**
2. 相同功能保持一致的尺寸、状态与反馈方式（36px 控件高度、md 按钮、pill tag、feedback.js 消息）**[评审]**
3. 不在页面 scoped 里大面积覆盖组件库内部选择器；全局视觉调整放 `tokens.css` / 全局样式层 **[可门禁：`:deep(.el-` 计数进债务基线冻结，弱信号]**

### 公共组件晋升流程

新组件先放页面/域目录（`views/<域>/components/`），满足以下条件再晋升到 `components/`：

1. 已在至少两个独立业务域复用
2. props / emits / slots 脱离原页面可理解，不依赖特定 API、Store 或路由
3. 覆盖完整状态清单：**loading / empty / disabled / error / readonly / 超长文本 / 小屏布局**
4. 在真实页面完成至少一次复用验证

**[评审]**；晋升时同步在 DESIGN.md 登记一行。

### 新页面基建采用红线

- 新列表页**必须**基于 `useListPage.js` **[评审]**
- 新详情抽屉**必须**基于 `DetailDrawer.vue` **[评审]**

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

以上长入场类是历史展示页模式，不用于新的业务操作页。新组件默认可见；如展示场景使用 `.will-animate`，必须提供减少动态及初始化失败时的可见兜底。当前登录页以文末 2026-09-06 航行主题记录为准。

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-29 | 统一 DESIGN.md，提取现有设计系统 | 之前设计变量分散在 App.vue 和各组件 scoped 样式中，需要集中管理 |
| 2026-04-29 | 字体 Outfit + DM Sans 已确认 | 系统已在使用，直接记录为正式方案 |
| 2026-04-29 | 语义色 Warning 复用 Gold 色系 | 系统已有实现，统一记录 |
| 2026-04-29 | 操作列按钮统一规范 | link style + `<el-icon>` 前缀图标 + 文字，无 `size` 属性；适用所有表格操作列；参考基准：CommissionBatch.vue |
| 2026-05-01 | 登录页采用 kimi 深色科技风设计 | 与内部页面差异化，营造进入平台的仪式感；Canvas 世界地图强化全球业务属性 |
| 2026-05-01 | 中性色从暖灰切换到冷灰（蓝调） | tokens.css 已落地新调色（页底 #f0f2f7、文字 #1a1a2e、表头 #fafbfe），DESIGN.md 同步对齐；列表页规范从 frontend/DESIGN.md 合并为 List Page Spec 节 |
| 2026-09-29 | 登录页地图去点阵与经纬网，改渐变光效填色 + 等高线，目标市场海岸线柔光 | 点阵与网格显碎，非目标大陆单调偏暗；目标市场要一眼可辨但不抢标题与登录卡。对比过“光墙”竖向挤出方案，因北欧碎海岸线过密、压标语而弃用 |
| 2026-07-25 | 整页 Liquid Glass 材质体系（.lg-aurora + .lg-card + --dash-glass-* 令牌） | 工作台首发，配方源自赛事大屏、色调保暖金；含命名/层叠/固定列/性能四条红线（均为当日实翻车教训）；同日推广至发票/备货/售后/物流/设计预约模块 |
| 2026-09-30 | 组件规范扩容：List Page Spec 增补筛选区/分页/三态三节，新增 Dialog & Form / Status Badge / Feedback / Format / Component Adoption 五个规范节 | 参考 Art Design Pro、vue-pure-admin、Soybean Admin、vben5、shadcn-admin 调研结论（表格之外无统一规范：筛选区 6 种写法并存、dialog 宽度 11 档、裸 ElMessage 497 处、money 格式化 4 份并存）；条目按 [门禁]/[可门禁]/[评审] 三级标注，[可门禁] 项同日扩展进 scripts/audit_frontend_ui.py（债务基线 15 项度量 + 白名单比对，新基线随本行文档一并提交后 check_conventions 门禁生效） |

## 登录页背景与动效（2026-09-06）

登录页延续黑金品牌，以静态暖光、低透明度水印和品牌区中部的金色光效地图组成背景。“莱莎方舟”叠在地图上，标题左侧向后散开的金色粒子形成航行尾迹；地图止于登录卡左侧。卡片使用近不透明渐变与细金边，不对动态背景实时模糊。颜色统一引用 `tokens.css` 的 `--login-*`。

- 入场只做 8px 位移与淡入，280ms，品牌正文错开 60ms；表单无延迟，不等待装饰入场。
- 标题 7 秒缓慢浮动（横向 8px、纵向 3px）；标题即飞船，尾迹由 `components/ArkWakeCanvas.vue` 单独一层 canvas 绘制（2026-09-29 起取代 DOM 粒子），`mix-blend-mode: screen` 叠加在地图上只加光不遮挡，四周羽化无硬边：①光尾（主体）——首字后方一道沿航向拉长的渐变光晕，贴近文字最亮、向后变细消散，内含一条细亮芯；尾内是发丝级细粒子（0.3–0.75px、低透明度），沿 5 条喷口轨道喷出后先快后稳、逐渐散开，只做质感不抢眼（2026-09-29 用户反馈粒子过大过抢眼后定稿）；②航迹——记录标题真实经过的位置并以航速后退，浮动会在其上留下轻微波纹；③航道——船后两条缓缓张开的弧形边线与船前虚线航向，刻度向后流动；④远处尘埃只在船后，提供视差。模拟上限 30fps、DPR 上限 2，预热后首帧即满尾迹；减少动态模式保留一帧静态尾迹，关闭浮动与运动。
- 世界地图使用静态与动态双 canvas；静态层只在尺寸变化时重绘，不画点阵与经纬线（2026-09-29 起）：陆地为左上受光的渐变填色 + 海岸内缘微光 + 4 圈向内渐隐的等高线 + 极淡颗粒，并在五个节点处晕开暖光；目标市场（北美仅美国与加拿大、欧洲、中东、澳洲）海岸线加亮金描边与向外扩散的柔光，区域由 `GLOW_REGIONS` 粗略经纬度外壳加羽化圈定，非洲与墨西哥/加勒比由 `EXCLUDED_REGIONS` 沿边界扣除。模糊一律用 canvas shadowBlur（各引擎均支持），不用 `ctx.filter`。四条航线保留固定起点、控制点与终点，按时间推进，绘制上限 30fps，DPR 上限 2。青岛为主节点：核心半径 4.5px、静态光晕半径 34px，动态核心轻微呼吸、双层光圈在 3.6 秒内向外扩散（半径 10–38px）；减少动态/窄屏保留静态光晕。
- 页面隐藏时暂停；系统切换减少动态偏好即时生效；宽度小于 1024px 使用静态地图。卸载清理帧请求、ResizeObserver 和事件监听。
- 短屏允许纵向滚动，备案信息始终位于表单下方；手机输入字号 16px，密码显隐有可访问名称、焦点轮廓与 40px 点击区域。

登录页文案按能力概括，不按模块数量或菜单逐项罗列：定位“AI 驱动的企业协同平台”；价值主张“贯通业务 · 沉淀知识 · 智能协同”；能力分类“客户经营 · 产销履约 · 业绩核算 · 创意设计 · 知识洞察”。依据当前导航与已实现功能归纳，避免绑定易过时的模块数量。

地图来源：[Natural Earth 1:110m land](https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson)，[public domain 使用条款](https://www.naturalearthdata.com/about/terms-of-use/)。本地资源 `frontend/src/assets/world-land.json` 保留陆地外环、去掉完全位于南纬 60° 以南的南极多边形，经纬度取两位小数；119 个多边形、4,427 个坐标点，65,219 字节，不依赖页面运行时网络加载。原始下载 SHA-256：`9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9`。只展示海岸线，不绘制行政区界。
