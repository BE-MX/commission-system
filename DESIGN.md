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
- **Gold Soft:** #FDF4DC — 极浅金底色（表格 header 等）
- **Danger:** #DC3545 / #C0392B (dark variant)
- **Success:** #2D9F6F / #1E7D50 (text)
- **Warning:** 使用 Gold 色系替代 — rgba(245,203,92,0.15) 背景 + #8B6914 文字
- **Neutrals (warm):**
  - Text primary: #1A1816
  - Text secondary: #6B6560
  - Text muted: #9C9590
  - Border: #E8E2DC
  - Page background: #FAF8F6
  - Card background: #FFFFFF
  - Toolbar hover: #F5F2EE
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
- **Data table:** striped rows, hover 高亮（gold light 背景），header 用 #F5F2EE 底色 + uppercase 小字
- **Status tags:** 自定义 Element Plus tag 颜色，语义明确（info/primary/success/danger/warning）
- **Action buttons:** link style 为主，图标 + 文字，按状态条件显示
- **Metric card:** 大数字 + 状态圆点 + 操作链接，hover 上浮
- **Dialog:** 16px 圆角，header 带 bottom border

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-29 | 统一 DESIGN.md，提取现有设计系统 | 之前设计变量分散在 App.vue 和各组件 scoped 样式中，需要集中管理 |
| 2026-04-29 | 字体 Outfit + DM Sans 已确认 | 系统已在使用，直接记录为正式方案 |
| 2026-04-29 | 语义色 Warning 复用 Gold 色系 | 系统已有实现，统一记录 |
| 2026-04-29 | 操作列按钮统一规范 | link style + `<el-icon>` 前缀图标 + 文字，无 `size` 属性；适用所有表格操作列；参考基准：CommissionBatch.vue |
