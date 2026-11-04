# Kubai 立体动态图标

侧边栏一级分组、顶级入口（工作台 / AI Agent 任务中心 / 公告管理）和顶栏账号菜单使用的图标。风格来自 [kubai-icons](https://github.com/kubai087/kubai-icons) skill v1.0.1：后片 + 内容 + 前片分层、外描边、全部颜色由一个主色推导、悬停时做物体本身的动作。方舟统一用品牌金（读 `tokens.css` 的 `--color-primary`）。

## 文件

| 文件 | 作用 |
|---|---|
| `engine.js` | 上游引擎原样复制，只在末尾追加 ES module `export`。不要改引擎本体 |
| `icons.js` | 方舟用到的 28 个图标：25 个上游范例 + 3 个按同一规则新画的（货车、色卡、机器人），条目保持上游格式 |
| `runtime.js` | 品牌金色板、实例 id 前缀、悬停开关 |
| `KubaiIcon.vue` | 组件：`<KubaiIcon name="货车" />`，整行（菜单项 / 下拉项）鼠标悬停时播放动效 |
| `LICENSE` | Kubai Icons License，文件头版权声明必须保留 |

导航映射在 `views/layout/kubaiNavIcons.js`：每个分组同时记录「kubai 图标」和「它替换的 Element Plus 源图标」。导航管理里的图标名、目录 JSON 和已保存配置都不变；管理员给某个分组换了图标后，该分组显示管理员选的线性图标（改选回同名源图标视为默认，仍显示立体图标）。被挪进其他分组的内置分组按二级处理，显示线性图标；常用导航与快捷导航沿用线性图标。新增一级分组时 `tests/kubaiNavIcons.test.mjs` 会提示补映射。

## 行为约定

- 只响应鼠标悬停；触屏和键盘焦点不播放动效。系统开启「减少动态效果」时直接停在终点，不做过渡。
- 侧边栏图标 24px；金色选中底上的图标放在白色小底板上，避免金色图标发虚。
- 二级菜单仍用 Element Plus 线性图标，保持主次层级。

## 新增或修改图标

1. 安装 kubai-icons skill，按它的 `SKILL.md` / `PROMPT.md` 在 skill 工作台里画，并用 `scripts/check.mjs --accent <品牌金>` 自检（静止、悬停过程、24px）。
2. 把条目原样追加到本目录 `icons.js` 的 `ICONS` 里，再到 `kubaiNavIcons.js` 登记映射。
3. 用 `tests/fixtures/kubai-icons/index.html`（vite dev 下打开）在深色侧栏和浅色背景上核对，跑 `npm run test:kubai-icons`。
