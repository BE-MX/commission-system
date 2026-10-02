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
- **Approach:** restrained — 品牌金 + 中性色系统，操作按钮使用科技轻快色系：能量金、青碧、杏橙、绯红
- **Primary:** #D4941C — LeShine Gold，用于品牌强调、导航与表单聚焦；按钮独立使用 `--button-*`
- **Button Primary:** #E0A50B，hover #C9930A，active #A87C08；深墨字 #211903。链接使用深金 #8F6508。按钮色值以 `frontend/src/styles/tokens.css` 的 `--button-*` 为准；正常、hover、active 文字对比度均 ≥4.5:1。
- **Primary Hover:** #BB8218
- **Primary Light:** rgba(212,148,28,0.08) — hover 背景、输入聚焦光晕
- **Gold Accent:** #F5CB5C — 侧边栏活跃态、标签、徽章、装饰
- **Gold Soft:** #FDF4DC — 极浅金底色（hover/徽章；表格 header 已改用冷灰）
- **Button Danger:** 实心 #D5363C + 白字；链接 #C62A30。状态标签独立引用 `--tag-danger-*`。
- **Button Success:** 实心 #0F8479 + 白字；链接 #0B6E63。状态标签独立引用 `--tag-success-*`。
- **Button Warning:** 实心 #B75B09 + 白字；链接 #9A4E08。提醒使用杏橙，区别于主操作的品牌金。
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
- **Header:** 56px 高，与页面标签栏共用浅色毛玻璃表面，细分隔线；见下方 Navigation Chrome Spec
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

## Navigation Chrome Spec（2026-10-02）

主站顶栏和已打开页面标签栏作为一个连续的浅色磨砂表面。参考 [shadcn-admin 的 Header 实现](https://github.com/satnaing/shadcn-admin/blob/main/src/components/layout/header.tsx) 的半透明底色、背景模糊和轻阴影，沿用平台品牌金、Vue / Element Plus 与现有标签交互。

- **材质**：外层 `.navigation-chrome` 使用 `--dash-glass-nav-bg`（白色 0.58 → 0.38 渐变）、`blur(16px) saturate(1.4)`、细边和顶部内高光；顶栏、标签栏内部透明，共用一层模糊，单个标签不另加滤镜。
- **环境**：右侧布局顶部使用 `--dash-glass-nav-backdrop` 静态浅金 / 蜜桃 wash。导航绝对定位覆盖正文滚动区顶部，内容从真实玻璃后方滚过，透出被模糊的色块 / 轮廓；不新增滚动监听或材质动画。
- **滚动安全**：正文首屏 padding 和 scroll-padding 为 `--navigation-chrome-height` 加原内容间距，初始内容与定位目标在导航下方。直接依赖正文滚动区的吸顶元素（共享独立工具栏、提成标签头、回款同步卡、素材筛选 / 工具栏、概念章节导航）使用该高度作为 top 偏移；内部独立滚动区的 sticky 仍采用内部坐标。壳内 fullscreen 元素将导航高度归零。
- **层级**：顶栏高度仍为 `--header-height: 56px`，标签栏保留 7px 顶部留白及 36px 标签高度。顶栏下为淡分隔线，两栏整体底部为细边与轻阴影；选中标签保留深金文字、金色顶线和较实的浅色底。
- **可用性**：保留标签切换、关闭、方向键 / Home / End、焦点环及窄屏横向滚动；切换标签和栏宽变化后立即露出当前标签，高频操作不加平滑滚动动画。用户菜单和记任务浮层挂到 body，不在玻璃表面上裁切。
- **降级**：不支持 backdrop-filter 或系统选择减少透明效果时使用 `--dash-glass-nav-fallback` 实色底，关闭模糊；文字颜色与选中标记保持清晰。
- **令牌**：颜色与阴影集中在 `tokens.css` 的 `--dash-glass-nav-*`；遵循 Liquid Glass 命名与性能约定。两栏只算一个局部滤镜区域，不给页面、卡片或表格增加模糊。

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

主操作按钮位置已统一到卡片内操作行（Action Bar Spec，2026-10-01 起），页头不再放按钮。主操作 `variant="primary"`（亮金实心深墨字），次操作 `variant="secondary"`（白底灰边），共享 GlassButton、Element Plus 与独立操作按钮统一引用 `--button-*`；`v-permission` 行为不变。操作列 link 按钮使用对应语义的深色文字。

### 性能红线（2026-07-25 滚动卡顿的教训）

- **backdrop 全静态**：禁止给极光光斑加无限位移动画——动态 backdrop 会让与之重叠的 `backdrop-filter` 表面每帧重采样，合成器持续满负载、滚动掉帧
- **大面积重复卡片/表格禁用 backdrop-filter**（20+ 张卡滚动时逐帧重采样必卡）；实时模糊只留给 ≤5 个小浮层（Hero、提醒条、悬浮按钮），规格 `blur(16px) saturate(1.4~1.6)`
- **禁止给大面积元素叠 `filter: blur()`**——柔和效果一律用大半径径向渐变实现

## Button Spec

按钮统一使用 **GlassButton** 的现有尺寸、圆角和接口。最新组件规范为科技轻快色系（2026-10-02）：主操作亮金底 + 深墨字，次操作白底灰边，成功青碧、提醒杏橙、危险绯红。主站 GlassButton、Element Plus、`.tech-btn-primary` 和 PM 原生按钮共用按钮语义；主站、PM 的独立 token 文件分别维护相同 `--button-*` 色值，由回归测试核对一致性，部署制品互不依赖。导航、状态标签、表单及专属展会/客户门户场景采用对应 token。完整接口、颜色与验收示例见 [操作列与按钮设计契约](docs/requirements/2026-10-02-action-button-design.md)。

### 尺寸体系

| 尺寸 | 名称 | 高度 | 内边距 | 字号 |
|------|------|------|--------|------|
| `xs` | 极小 | 28px | 0 10px | 11px |
| `sm` | 小 | 32px | 0 12px | 12px |
| `md` | 中（默认） | 36px | 0 16px | 13px |
| `lg` | 大 | 40px | 0 20px | 13px |
| `xl` | 极大 | 48px | 0 24px | 14px |

工具栏使用 `md`（36px）。操作列 link 覆盖尺寸体系：桌面最小高度 24px、padding 4px 8px、13px/500、line-height 16px、图文间距 4px；触屏或粗指针最小高度 44px。长文案自然增高。

### 圆角体系

`none` / `sm` / `md` / `lg`（默认） / `xl` / `full`

列表页工具栏按钮默认 `12px`（对应 `lg`），操作列 link 按钮无圆角。

### 变体与适用场景

| 变体 | 风格 | 适用场景 |
|------|------|----------|
| `primary` | 亮金实心 + 深墨字 | 主操作、提交、确认 |
| `secondary` | 白底 + 灰色边框 | 次操作、批量操作 |
| `outline` | 白底 + 灰色描边 | 筛选、配置类操作 |
| `ghost` | 完全透明，hover 才显背景 | 工具栏、弱操作 |
| `soft` | 浅金底 + 深金字 | 收藏、标记类柔和操作 |
| `link` | 深色语义文字 + hover 同族浅底 | 操作列跳转、查看 |
| `danger` | 红色实心 + 白字 | 删除、禁用、强警告 |
| `success` | 青碧实心 + 白字 | 保存成功、通过、启用 |
| `warning` | 杏橙实心 + 白字 | 提交审核、提醒 |
| `info` | 亮金实心 + 深墨字 | 帮助、提示、信息 |
| `white` | 白底 + 灰边 | 叠加在复杂背景上 |

### 列表页按钮映射

**工具栏按钮**
- 主操作：`variant="primary"`（亮金实心深墨字）
- 次操作：`variant="secondary"`（白底 + 边框）
- 筛选/切换：`variant="outline"` 或 `variant="ghost"`

**操作列按钮**
- 编辑/查看：GlassButton `variant="link"`（默认 primary 深金文字），Element Plus `link type="primary"`；带前缀图标
- 通过/启用：GlassButton `variant="link" link-tone="success"`；Element Plus `link type="success"`
- 删除/拒绝：GlassButton `variant="link" link-tone="danger"`；Element Plus `link type="danger"`
- 暂停/禁用/撤销发布等可恢复状态变更：warning；恢复/启用为 success。业务失败或破坏性动作使用 danger
- 发送确认、待审核提醒：warning；普通查看、编辑、打印、AI 辅助为 primary，明确提醒场景可选 warning
- 统一要求：图标 + 文字，操作列不传 size、不写内联颜色、不使用实心/描边按钮；link 无圆角、无边框、无阴影、无按压缩放。相邻按钮间距 4px 8px

### 特殊状态

- **加载状态**：`loading` 显示旋转图标，保留变体颜色，阻止重复点击
- **禁用状态**：`disabled` 使用浅灰底、灰字、灰边；文字/ghost 按钮保持透明底，不响应 hover/active
- **激活状态**：实心按钮 `active` 显示品牌金 ring；键盘 `:focus-visible` 显示 2px 品牌金轮廓、offset 3px。link 无阴影，鼠标点击不保留 hover 背景，键盘焦点保留轮廓
- **Element Plus**：solid/plain/text/link 使用同一语义色族；默认实心按钮保持中性配色；默认 link 与 primary link 一致使用深金文字；warning link 使用深杏橙；hover/active 使用对应 `--button-{tone}-text-hover/active`，不借用实心底色
- **图标组合**：支持 `leftIcon` / `rightIcon` / 纯图标按钮
- **全宽按钮**：`fullWidth` 撑满容器（表单底部提交场景）
- **阴影层级**：实心/描边 `shadow` 支持 `sm/md/lg/xl`；link 忽略 shadow，频繁行操作只做 160ms 颜色反馈，减少动态模式关闭过渡

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
  <div class="toolbar">…筛选区（见第 5 节）…</div>
  <div class="action-bar">…主操作按钮组 + TableTools（见 Action Bar Spec）…</div>
  <el-table
    :data="tableData"
    v-loading="loading"
    :max-height="maxHeight"
    class="list-table"
    border
  >
    ...
  </el-table>
  <el-pagination class="pager" layout="total, sizes, prev, pager, next" ... />
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
- 普通文本列单行省略；操作列与多标签单元格按对应规范换行

### 2. 字体与排版

| 元素 | 字号 | 字重 | 颜色 | 其他 |
|------|------|------|------|------|
| 表头 | 13px | 600 | `var(--text-secondary)` | 非 uppercase，无 letter-spacing |
| 内容 | 13px | 400 | `var(--text-primary)` | — |
| 链接/主键 | 13px | 600 | `var(--color-primary)` | — |
| 操作按钮文字 | 13px | 500 | `var(--button-{tone}-text)` | link 样式；默认 primary |

### 3. 标签与徽章

**状态标签（pill）**

最新科技轻快标签使用独立 `--tag-*` 色族，不从按钮实心底色推导文字色；按钮加深色阶不会改变标签。浅底 + 同族深字为默认，`dark` 使用 solid，Gold dark 配深墨字：

| type / 色族 | 浅底 | 文字 | 边框 | solid |
|---|---|---|---|---|
| primary / gold | #FDF6DD | #8F6508 | #F0D889 | #E0A50B |
| success / 青碧 | #E4F7F3 | #0B6E63 | #A8E3D6 | #0D9488 |
| warning / 杏橙 | #FEF0DE | #9A4E08 | #F4CCA0 | #C2610A |
| danger / 绯红 | #FDEBEC | #C62A30 | #F6C6CA | #E5484D |
| 电光蓝（信息备用色族） | #EBF1FE | #1D4ED8 | #BFD4FB | #2563EB |
| info / neutral | #F6F7F9 | #4A5563 | #E2E5EA | #64748B |

Element Plus `info` 当前映射 neutral；电光蓝为备用 token，不把所有 info 标签改蓝。

```html
<el-tag size="small" effect="plain">...</el-tag>
```

- 圆角 `9999px`（胶囊）、padding `2px 10px`、字号 12px、字重 500
- 用 Element Plus `type` 控制颜色（全局已覆盖为品牌色）
- 状态标签保持单行，禁止 `white-space: normal` 或任意位置换行把中文压成竖排。表格列宽应包含标签、单元格的内边距，完整展示已登记状态；超长未知值可省略，并通过列的 overflow tooltip 查看全文。
- 单个 StatusBadge 不换行；同一普通单元格内的多个标签可以在标签之间换行。操作列继续遵守下方按钮布局约定。
- 标签文字始终保留完整 `title`，插槽文字变化时同步更新；调用方显式提供的 title（包括空值）优先。可关闭标签只截断文字，为关闭按钮保留空间。
- 状态列至少100px；按实际最长状态文案增加宽度，不把100px当作所有状态都够用。新增或修改状态列后在 frontend 运行 `npm run audit:status-badges`；脚本检查静态列宽和字面量文案，并单独核对发票动态列控制器。动态字典文案还需按最长值检查实际显示。

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
- link 样式，使用 Button Spec 的深色语义文字、尺寸、状态与无阴影规则

操作/处理列统一加 `class-name="table-action-column"`，布局由 `frontend/src/styles/table-actions.css` 管理：按钮按原顺序换行，单元格随内容增高，不继承普通文本列的单行省略。需要额外包裹按钮时使用 `<div class="table-actions">`，不要另设 `nowrap`、固定高度或裁切。长按钮文字允许换行，间距统一使用 `gap`，不叠加相邻按钮的 margin。

表格容器宽度不超过 768px 时取消左右固定列，通过表格横向滚动访问所有列，避免手机和窄抽屉中固定列互相覆盖；桌面宽表仍保留原固定列配置。普通文本列继续按原规则省略，既有下拉菜单、权限、加载和禁用状态不变。PM 站使用独立样式实现相同的换行与横向可达原则。

新增操作列后运行 `node --test frontend/tests/tableActions.test.mjs` 检查接入。浏览器布局验证页见 `frontend/tests/fixtures/table-actions/index.html`（Vite 开发服务下访问；隔离数据，不调用业务 API），覆盖多按钮、长文案、窄图标列、下拉及确认弹层。

运行 `python frontend/tests/actionButtons.browser.py --url http://localhost:3000/tests/fixtures/table-actions/` 验证共享按钮状态、单个加载图标、次操作对比度、键盘焦点、点击后移出、权限切换及触屏目标；需要 Python Playwright 与 Chrome。

**工具栏按钮**

- 次操作：默认样式（白底 + 边框）
- 主操作：`type="primary"`（亮金实心深墨字）
- 统一高度 36px

### 5. 筛选区（FilterBar）

职责划分（借鉴 Art Design Pro `ArtSearchBar`）：**页面负责筛选字段与业务逻辑，`components/FilterBar.vue` 负责布局、展开收起与查询/重置操作区**。发票、回款、内销订单已接入；存量页面按业务域逐批迁移。

**布局**

- 筛选区统一放在全局 `.toolbar`（`app.css`）容器内，flex 横向排列、允许换行；**禁止**另造 `el-row` 分栏或原生 `<form>` 容器 **[评审]**
- 控件高度统一 36px（与按钮 md 对齐）；**禁止** `el-input` / `el-select` / `el-date-picker` 使用 `size="small"` **[可门禁：`_tags` 扫描这三类标签的 `size="small"`，存量计数进债务基线]**
- 控件宽度只用三档：`160px`（短文本/状态）/ `200px`（默认）/ `280px`（日期范围）；**禁止**内联 `style="width:…"` 写任意值 **[可门禁：`.toolbar` 区块内控件标签的 `style=` 宽度计数进债务基线]**

**操作区**

- 「查询 + 重置」必须成对出现，固定在筛选区末尾；查询用主按钮（GlassButton `variant="primary"`），重置用次按钮 **[评审]**
- 默认插槽放最多 4 个常用字段，其余放 `#advanced`，默认收起；收起保留输入，不自动查询；窄屏宽度不超过可用空间 **[评审]**
- 文本输入 Enter 由 FilterBar 统一触发一次查询；输入法确认、下拉/日期选项的 Enter 不提交查询，字段不重复绑定 Enter **[评审]**
- `useListPage.searchForm` 是编辑中的条件，`appliedSearchForm` 是已提交快照（日期也包含在内）。只有查询、Enter 或重置提交条件并回到第一页；翻页、切换每页条数、刷新均读取已提交条件。`hasPendingSearch` 驱动“查询后生效”提示 **[评审]**
- FilterBar 通过 `@search` / `@reset` 调用页面方法；`loading` 禁用查询，重置仍可取消旧查询；`advancedCount` 表达已提交高级条件数。内销重置保留当前订单大类标签 **[评审]**

### 6. 分页

现状 `el-pagination` layout 有 5 种并存，按本节收敛为唯一形态；存量页面在下次触碰时补齐，不一蹴而就。

- layout 固定为 `total, sizes, prev, pager, next`；`page-sizes` 固定 `[20, 50, 100]`，默认 20 **[可门禁：`_tags("el-pagination")` 的 `layout` 属性白名单比对]**
- 类名统一 `class="pager"`，置于表格卡片内底部 **[评审]**
- 分页状态走 `useListPage.js`（新列表页必须使用），不自建分页状态 **[评审]**
- 成功编辑使用 `refreshUpdate()` 保留有效页；删除使用 `refreshRemove()`，根据服务端 total 修正失效末页并重读；新增使用 `refreshCreate({ firstPage })`，依据业务排序定位。发票（created_at 倒序）、回款（id 倒序）新增回第一页；内销新增通过带新单号的返回路由查询定位，缓存实例也接收该查询 **[评审]**

### 7. 表格三态（loading / empty / error）

借鉴 Art Design Pro 通用组件状态清单，所有列表表格必须显式处理三种状态：

- **loading**：`v-loading`（全站既有做法，不变）
- **empty**：统一用 `el-table` 的 `empty` 插槽或 `el-empty`，文案「暂无数据」，有筛选条件时给出「重置筛选」引导；**禁止**新增手写「暂无…」裸 div，`empty-text` 属性不再新增 **[可门禁：`empty-text=` 属性计数进债务基线冻结]**
- **error**：列表用 `components/ListPageStatus.vue` 展示首次失败与重试；已有行时保留上次成功结果，提示结果所在页码和可能过期。列表请求传 `suppressToast: true` 避免重复消息；401 仍由拦截器处理，写入失败沿用域内反馈。首次失败不得展示为无数据 **[评审]**
- `fetchList()` / 查询 / 刷新成功返回 `true`，读取失败保存 `error` / `errorMessage` 并返回 `false`；写入成功后的读取失败不能反向报告为写入失败。调用方若原本依赖列表异常抛出，须改读共享错误状态 **[评审]**
- 请求带 `signal` 和 `isCurrent()`；仅最新请求可更新行、total、loading、错误及域元数据；卸载取消请求。发票概览有独立请求序号，回款同步开关须在 `isCurrent()` 后更新 **[评审]**

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
- [ ] 主操作按钮在 `.action-bar`（卡片内、筛选区下方），页头无操作按钮
- [ ] 操作行右侧为 TableTools 四图标（密度/列显隐已接线）
- [ ] 分页在卡片内底部 `class="pager"`

### 9. 扩展增强项

以下条目来自 2026-09-30 参考框架调研（Art Design Pro / vue-pure-admin / Soybean / shadcn-admin 等）。表格工具栏四图标已于 2026-10-01 转为列表页标配并推广全站，接入方式见「Action Bar Spec」。

**列配置数组驱动**（借鉴 pure-admin / Art Design Pro）

- 列定义为配置数组（`key / label / prop / minWidth / maxWidth / align / tooltip / className`），渲染层仍输出标准 `el-table-column`，列宽等既有规则不变 **[评审]**
- 列配置数组是 TableTools 列显隐的数据源；复杂单元格用 `key` 分发插槽，操作列保持独立模板列、不进配置数组
- 配置化只是组织方式，不追求「页面无模板代码」（Art Design Pro 自身亦警示过度配置化会隐藏业务流程）
- 配置数组便于机器检查列宽规则，是未来把列宽门禁做到字段级的前提

**行密度**（借鉴 Soybean / shadcn-admin）

- 三档值固定在 `tokens.css`：`--table-cell-padding-compact / -default / -comfort`（纵向 6/10/14px），由 `app.css` 的 `.list-table.density-compact / .density-comfort` 全局类消费；页面不手写像素值 **[评审]**
- 用户级切换通过 TableTools 密度图标提供，状态持久化到 localStorage 页面键（见 Action Bar Spec）

## Action Bar Spec（操作行）

列表页主操作按钮的统一位置（2026-10-01 起）：**操作行位于筛选区与表格之间，同在表格卡片内**。

**布局**

- 左侧：页面主操作按钮组（新建 / 批量操作 / 导入导出等），GlassButton 变体按 Button Spec（主操作 `primary`、次操作 `secondary`、配置类 `outline`/`ghost`） **[评审]**
- 右侧：TableTools 四图标（刷新 → 列显示 → 密度 → 全屏），统一用全局组件 `components/TableTools.vue` **[评审]**
- 换行与窄屏行为同筛选区（flex-wrap，不裁切）
- 全局结构类：`.table-card > .action-bar`（`app.css`），页面级只做玻璃皮肤等最小覆写

**页头**

- 页头只保留标题 + 一句描述，**不再放操作按钮**（原页头主操作全部迁入操作行） **[评审]**
- 页面级提示（`el-alert`）留在页头与卡片之间，不入操作行

**TableTools 接入**

- 四图标顺序固定；`columns` 传列配置数组（驱动列显隐，可空——空时不渲染列设置图标），`density` / `visibleKeys` 用 `v-model`，状态持久化到 localStorage 页面级键（`<页面名>-table-view`）
- 表格挂 `:class="`density-${density}`"`；全屏切换让表格卡片覆盖视口，全屏时取消 `max-height`，Esc 退出。保持弹窗、抽屉仍在页面根节点内可见。
- 列配置数组的字段约定见 List Page Spec 第 9 节

## Dialog & Form Spec

弹窗与表单的用途、尺寸与底部操作区统一约定。主站已按三档宽度、顶部标签和标准footer收敛，具体实现与专业场景边界见下文「规范实现与验收索引」。

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

- 弹窗内表单统一 `label-position="top"`（FilterBar 筛选用行内控件，不用 `el-form-item` 标签）**[门禁：主站 form_label_position]**
- 通用校验使用已落地 `utils/validators.js`，新表单不自写手机号/邮箱正则；国际号码、展会号码及金额精度由业务明确选择策略，不能扩大原校验范围 **[门禁：inline_public_validator]**
- 必填标记、错误提示位置沿用 Element Plus 默认，不自定义 **[评审]**

### 4. 底部按钮区

- dialog：统一 `#footer` 插槽 + `class="dialog-footer"`，取消在左、主按钮在右 **[评审]**；`form-actions` / `drawer-actions` 别名不再新增 **[可门禁：后两者类名计数进债务基线冻结]**
- drawer：用 DetailDrawer 内置 footer，不另写按钮区
- 提交按钮必须带 loading（GlassButton `:loading` 或 `el-button :loading`），防重复提交 **[评审]**

## Status Badge & 状态字典

状态色的唯一职责是「让状态一眼可辨」，颜色映射必须单点维护。

- **状态字典**：每个业务域在自己的 `use*.js` 或共享字典文件中维护 `状态枚举 → { label, tagType }` 映射；新增状态字段必须先登记字典 **[评审]**。参照 PM 站 `utils/labels.js`（标签 + 语义色单点维护，「状态色仅用于徽标」纪律）
- **渲染**：表格/详情中状态一律用 pill tag（见 List Page Spec 第 3 节），`type` 从字典取；存量模板里静态 `type="success"` 等裸映射在触碰时迁入字典 **[可门禁：`el-tag` 标签上静态 `type=` 属性计数进债务基线，只许降不许升]**
- 主站已落地 `components/StatusBadge.vue` 与 `utils/status.js`，支持域字典和未知值可读兜底。PM 站继续使用自己的组件、token与反馈规范。

## Feedback Spec

消息、确认、加载、空态的统一出口。主站裸消息/确认已收敛到 `utils/feedback.js`；原动作、标题、校验条件与精确成功文案必须保留。

- **操作反馈**：成功/失败消息一律 `utils/feedback.js` 的 `msgSuccess` / `msgError`；**禁止**新代码直接 `import { ElMessage } / ElNotification` **[可门禁：`.vue`/`.js` 中两者 import 计数进债务基线，只许降不许升]**
- **危险确认**：删除、禁用、驳回等必须 `confirmDanger`，不裸调 `ElMessageBox.confirm` **[可门禁：ElMessageBox import 计数冻结，同上]**
- **接口错误**：普通请求由 `api/request.js` 拦截器提示；具有行内错误/重试的读取传 `suppressToast: true` 和 AbortSignal，页面负责展示。`msgError(text, error)`识别已提示错误，避免重复消息。取消确认正常退出 **[评审]**
- **加载**：按钮提交带 loading；表格 `v-loading`；首屏大区块可用 `el-skeleton`（适度使用，不为每个列表补骨架）**[评审]**
- **空状态**：使用 `EmptyState` 或组件 empty 插槽，按已应用条件提供清筛选/创建等恢复动作。读取失败由 `ListPageStatus` 展示，首次失败不能显示成功空态；刷新失败保留旧数据并说明过期 **[评审]**
- PM 站对应纪律：`toast.success/error` + `EmptyState.vue`，维持不变

## Format Spec（金额与数字）

时间是全站规范执行最好的样例（`utils/datetime.js` + 机器检查），金额按同一路径收敛。

- **金额**：使用已有 `utils/money.js` 的 `formatMoney`；按币种、精度、缺失值、正负号明确配置。金额计算、cents解析、序列化不交给显示函数；百分比/重量/数量不改成金额。新代码禁止新增散写金额格式化 **[门禁：money_format 计数冻结，共享实现自身有精确路径豁免]**。列表默认两位小数 + 千分位；负金额前置 `-`。
- **数字列**：表格数字沿用 DM Sans + tabular-nums（见 Typography）；维持全表左对齐红线，数字列暂不强制右对齐
- **日期控件**：`el-date-picker` 的 `value-format` 统一 `YYYY-MM-DD`（纯日期）与 `YYYY-MM-DD HH:mm:ss`（日期时间），不新增 ISO `T` 格式 **[可门禁：`_tags("el-date-picker")` 的 `value-format` 白名单比对]**

## Component Adoption（复用与晋升）

共享能力按真实资源契约采用；分页、全量树、限量历史、游标事件与辅助详情分别处理，覆盖证据见资源账本。引用数量不能证明采用完成。

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

- 新服务端分页列表基于 `useListPage.js`；完整数组/树用 `useAsyncResource.js`，游标历史用 `useCursorResource.js` 或经验证的等价控制器，不为无分页接口制造分页 **[评审]**
- 新详情抽屉**必须**基于 `DetailDrawer.vue` **[评审]**
- 已晋升公共组件登记：`components/TableTools.vue`（2026-10-01，发票页首发后晋升，全站列表页推广）
- 已晋升公共组件登记：`components/FilterBar.vue`、`components/ListPageStatus.vue`（2026-10-01，发票/回款/内销三试点）。验证入口为 `tests/useListPage.test.mjs`、`tests/listPagePilots.test.mjs`、`tests/listPageComponents.test.mjs`；完整验收记录见 `docs/requirements/2026-10-01-list-filter-phase-one.md`。

## 规范实现与验收索引（2026-10-02）

本轮四阶段本地实现以 [最终验收](docs/requirements/2026-10-02-ui-convergence-acceptance.md) 和 [资源账本](docs/requirements/2026-10-02-list-resource-coverage.md) 为证据。主站为采用范围；PM、外部客户门户和登录展示页按各自界面纪律保留边界。

| 清单 | 实现入口 | 验证入口 |
| --- | --- | --- |
| 1–4 列表、查询、CRUD、筛选 | useListPage / useAsyncResource / useCursorResource / FilterBar / ListPageStatus | useListPage、listPagePilots、各域 *Resources / *ListAdoption 回归；逐项资源账本 |
| 5 弹窗/表单 | 三档 el-dialog、DetailDrawer、顶部标签与共享footer；专业长编辑器登记用途 | UI audit 尺寸/表单门禁；样例窄屏与实际 mounted 验证 |
| 6 状态 | StatusBadge、utils/status.js、域内字典 | status、badge及领域枚举边界回归 |
| 7 反馈/空态 | utils/feedback.js、EmptyState、ListPageStatus | feedback、组件及写成功读失败回归 |
| 8–9 金额/校验 | utils/money.js、utils/validators.js | money、validators及财务边界回归；精度/国际号码策略 |
| 10 分页/详情 | 真实P列表默认20/档位20、50、100；ResponsiveDescriptions观察容器宽度 | audit分页门禁；响应式列数、390px长详情验证 |
| 11 表格偏好 | useTableView、TableTools恢复默认，版本化持久化、列集交集、至少一列 | tableView、tablePreferences；浏览器显隐/密度/刷新/恢复默认 |
| 12 颜色/尺寸 | tokens.css、app.css、语义色映射、md按钮和36px筛选 | token对比度回归、控件尺寸门禁；精确例外登记 |
| 13 样例 | system/ComponentShowcase.vue，navigation.js注册；本地无业务API夹具 | 桌面/390px、Enter/Escape、焦点、失败恢复、减少动态验证 |

门禁位于 `scripts/audit_frontend_ui.py`，负例位于 `scripts/test_audit_frontend_ui.py`。分页档位/默认20、顶部标签、GlassButton合法尺寸与md、公共校验规则已受控；`scripts/ui_component_exceptions.json` 按路径、精确数量与业务理由登记紧凑按钮，数量变化即失败。`--write-baseline` 也禁止提高既有度量预算。旧债务只许下降；剩余 specialized/PM 计数须按最终报告解释，不能宣称全站零债务。

文件超过500行只作职责复核线索，不作为UI正确性指标，不为达行数机械拆分；本轮移除该UI债务度量。专业看板、任务树、打印/导入预览与完整选项集合保留各自布局和真实边界，明确限量及错误恢复；数据结构、业务计算和危险确认条件仍按领域约束。

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
| `.tech-btn-primary` | 主按钮：引用 `--button-primary`，亮金底深墨字，hover/active 使用同色族 |
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
| 2026-10-02 | 科技轻快按钮与操作列组件规范收口 | 主站/PM 按钮 token 对齐；link 深色语义文字、24px/触屏44px、无圆角/阴影/缩放、显式图标；新增 warning tone，静态扫描与浏览器状态验收 |
| 2026-04-29 | 统一 DESIGN.md，提取现有设计系统 | 之前设计变量分散在 App.vue 和各组件 scoped 样式中，需要集中管理 |
| 2026-04-29 | 字体 Outfit + DM Sans 已确认 | 系统已在使用，直接记录为正式方案 |
| 2026-04-29 | 语义色 Warning 复用 Gold 色系 | 系统已有实现，统一记录 |
| 2026-04-29 | 操作列按钮统一规范 | link style + `<el-icon>` 前缀图标 + 文字，无 `size` 属性；适用所有表格操作列；参考基准：CommissionBatch.vue |
| 2026-05-01 | 登录页采用 kimi 深色科技风设计 | 与内部页面差异化，营造进入平台的仪式感；Canvas 世界地图强化全球业务属性 |
| 2026-05-01 | 中性色从暖灰切换到冷灰（蓝调） | tokens.css 已落地新调色（页底 #f0f2f7、文字 #1a1a2e、表头 #fafbfe），DESIGN.md 同步对齐；列表页规范从 frontend/DESIGN.md 合并为 List Page Spec 节 |
| 2026-09-29 | 登录页地图去点阵与经纬网，改渐变光效填色 + 等高线，目标市场海岸线柔光 | 点阵与网格显碎，非目标大陆单调偏暗；目标市场要一眼可辨但不抢标题与登录卡。对比过“光墙”竖向挤出方案，因北欧碎海岸线过密、压标语而弃用 |
| 2026-07-25 | 整页 Liquid Glass 材质体系（.lg-aurora + .lg-card + --dash-glass-* 令牌） | 工作台首发，配方源自赛事大屏、色调保暖金；含命名/层叠/固定列/性能四条红线（均为当日实翻车教训）；同日推广至发票/备货/售后/物流/设计预约模块 |
| 2026-09-30 | 组件规范扩容：List Page Spec 增补筛选区/分页/三态三节，新增 Dialog & Form / Status Badge / Feedback / Format / Component Adoption 五个规范节 | 参考 Art Design Pro、vue-pure-admin、Soybean Admin、vben5、shadcn-admin 调研结论（表格之外无统一规范：筛选区 6 种写法并存、dialog 宽度 11 档、裸 ElMessage 497 处、money 格式化 4 份并存）；条目按 [门禁]/[可门禁]/[评审] 三级标注，[可门禁] 项同日扩展进 scripts/audit_frontend_ui.py（债务基线 15 项度量 + 白名单比对，新基线随本行文档一并提交后 check_conventions 门禁生效） |
| 2026-10-01 | 调研剩余四条目处置：工具栏右侧标配/列配置驱动/行密度写入「扩展增强项」试点规范；操作列溢出维持换行方案，不引入 dropdown 收敛 | 操作列换行已有 table-actions.css + tableActions.test.mjs 回归门禁，dropdown 仅放「更多」低频动作；筛选按钮组保持跟随字段末尾（与存量页面一致），不采用右对齐 |
| 2026-10-01 | 试点条款落地发票页：TableTools 四图标（刷新/列显示/密度/全屏）+ 列配置数组驱动渲染 + 密度三档入 tokens.css | TableTools 暂居 `views/invoice/components/`（晋升流程：回款单采用后升 `components/`）；列显隐与密度持久化于 localStorage 页面键；density 类挂在 list-table 上由 app.css 消费 token；全屏时取消 max-height |
| 2026-10-01 | 主操作按钮从页头迁入卡片内操作行（左按钮组 + 右 TableTools 四图标），TableTools 晋升全局 components/，列表页结构推广全站 | 用户决策：新建类按钮统一在列表上方、筛选项下方、与四图标同一行；页头只留标题描述。结构类（.table-card>.toolbar/.action-bar/.pager + filter-w 三档）全局化到 app.css |

## 登录页背景与动效（2026-09-06）

登录页延续黑金品牌，以静态暖光、低透明度水印和品牌区中部的金色光效地图组成背景。“莱莎方舟”叠在地图上，标题左侧向后散开的金色粒子形成航行尾迹；地图止于登录卡左侧。卡片使用近不透明渐变与细金边，不对动态背景实时模糊。颜色统一引用 `tokens.css` 的 `--login-*`。

- 入场只做 8px 位移与淡入，280ms，品牌正文错开 60ms；表单无延迟，不等待装饰入场。
- 标题 7 秒缓慢浮动（横向 8px、纵向 3px）；标题即飞船，尾迹由 `components/ArkWakeCanvas.vue` 单独一层 canvas 绘制（2026-09-29 起取代 DOM 粒子），`mix-blend-mode: screen` 叠加在地图上只加光不遮挡，四周羽化无硬边：①光尾（主体）——首字后方一道沿航向拉长的渐变光晕，贴近文字最亮、向后变细消散，内含一条细亮芯；尾内是发丝级细粒子（0.3–0.75px、低透明度），沿 5 条喷口轨道喷出后先快后稳、逐渐散开，只做质感不抢眼（2026-09-29 用户反馈粒子过大过抢眼后定稿）；②航迹——记录标题真实经过的位置并以航速后退，浮动会在其上留下轻微波纹；③航道——船后两条缓缓张开的弧形边线与船前虚线航向，刻度向后流动；④远处尘埃只在船后，提供视差。模拟上限 30fps、DPR 上限 2，预热后首帧即满尾迹；减少动态模式保留一帧静态尾迹，关闭浮动与运动。
- 世界地图使用静态与动态双 canvas；静态层只在尺寸变化时重绘，不画点阵与经纬线（2026-09-29 起）：陆地为左上受光的渐变填色 + 海岸内缘微光 + 4 圈向内渐隐的等高线 + 极淡颗粒，并在五个节点处晕开暖光；目标市场（北美仅美国与加拿大、欧洲、中东、澳洲）海岸线加亮金描边与向外扩散的柔光，区域由 `GLOW_REGIONS` 粗略经纬度外壳加羽化圈定，非洲与墨西哥/加勒比由 `EXCLUDED_REGIONS` 沿边界扣除。模糊一律用 canvas shadowBlur（各引擎均支持），不用 `ctx.filter`。四条航线保留固定起点、控制点与终点，按时间推进，绘制上限 30fps，DPR 上限 2。青岛为主节点：核心半径 4.5px、静态光晕半径 34px，动态核心轻微呼吸、双层光圈在 3.6 秒内向外扩散（半径 10–38px）；减少动态/窄屏保留静态光晕。
- 页面隐藏时暂停；系统切换减少动态偏好即时生效；宽度小于 1024px 使用静态地图。卸载清理帧请求、ResizeObserver 和事件监听。
- 短屏允许纵向滚动，备案信息始终位于表单下方；手机输入字号 16px，密码显隐有可访问名称、焦点轮廓与 40px 点击区域。

登录页文案按能力概括，不按模块数量或菜单逐项罗列：定位“AI 驱动的企业协同平台”；价值主张“贯通业务 · 沉淀知识 · 智能协同”；能力分类“客户经营 · 产销履约 · 业绩核算 · 创意设计 · 知识洞察”。依据当前导航与已实现功能归纳，避免绑定易过时的模块数量。

地图来源：[Natural Earth 1:110m land](https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson)，[public domain 使用条款](https://www.naturalearthdata.com/about/terms-of-use/)。本地资源 `frontend/src/assets/world-land.json` 保留陆地外环、去掉完全位于南纬 60° 以南的南极多边形，经纬度取两位小数；119 个多边形、4,427 个坐标点，65,219 字节，不依赖页面运行时网络加载。原始下载 SHA-256：`9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9`。只展示海岸线，不绘制行政区界。
