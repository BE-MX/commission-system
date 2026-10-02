# 操作列与按钮设计契约

更新日期：2026-10-02。当前规范以 [DESIGN.md](../../DESIGN.md)、主站 `tokens.css` 和共享组件实现为准。本文件明确科技轻快配色下的接口与验收规则。

## 目标与范围

同一语义的操作在不同页面、GlassButton、Element Plus 和 PM 原生按钮上，颜色、图文尺寸、反馈保持一致。主站全部操作/处理列及复用导出菜单遵守此契约；展开卡片打印也使用轻量 link。业务数据链接、备注、操作记录描述不作为操作列批量改造。

## 颜色与接口

| 语义 | 场景 | GlassButton | Element Plus | 默认文字 / hover / active | hover 背景 |
|---|---|---|---|---|---|
| primary | 查看、编辑、打印、普通操作 | `variant="link"`，省略 tone 或 `link-tone="primary"` | `link`，省略 type 或 `type="primary"` | #8F6508 / #775407 / #634606 | #FDF6DD |
| success | 通过、启用、恢复、确认 | `link-tone="success"` | `type="success"` | #0B6E63 / #095B52 / #074C44 | #E4F7F3 |
| warning | 暂停、禁用、取消发布、提醒 | `link-tone="warning"` | `type="warning"` | #9A4E08 / #824107 / #6B3506 | #FEF0DE |
| danger | 删除、拒绝、终止、破坏性撤销 | `link-tone="danger"` | `type="danger"` | #C62A30 / #AC2228 / #921C22 | #FDEBEC |

动态启停按钮随动作切换 tone：如 `row.is_active ? 'warning' : 'success'`。不能把 `type` 传给 GlassButton 代替 `link-tone`。`info` 实心保持现有 primary 别名；信息状态标签仍用电光蓝。

实心主按钮保持亮金 #E0A50B / #C9930A / #A87C08，文字 #211903；危险 #D5363C、成功 #0F8479、警告 #B75B09 均用白字。与先前亮阶相比，危险/成功/警告实心底和主按钮墨色做小幅加深，使各交互状态达到 4.5:1。链接文字也在白底、工作区底、PM 纸面及同族 hover 背景上达到 4.5:1。标签独立维护 `--tag-*`，不借用实心按钮底色作为小字颜色。

主站与 PM 的 `--button-*` token 必须完全一致，由 `sharedUi.test.mjs` 核验；PM 保留自己的纸面、排版与卡片体系。按钮不得写内联 color 或覆盖 `--el-color-danger` 作为自己的语义色。

## 尺寸、图标与布局

- 桌面：最小高度 24px，padding 4px 8px，13px/500，line-height 16px，图标 13px，图文间距 4px。
- 触屏/粗指针：最小高度 44px；长文字仍可增高。颜色相同，hover 不产生位移。
- link：透明底、0 边框、0 圆角、无阴影、无缩放。GlassButton 的 link 忽略 shadow；不能通过 size 调整操作列密度。
- 图标 + 可读文字。动态恢复/暂停使用 SwitchButton；打印 Printer、编辑 Edit、查看 Document、删除 Delete、确认 Check、更多 MoreFilled。已存在的纯删除图标保留其业务紧凑场景，不增加未知文案。
- 操作列加 `class-name="table-action-column"`；按钮保持原顺序，4px 8px gap、自然换行；长文字不裁切。禁止省略 tooltip、固定行高与 nowrap。
- 768px 以下表格容器取消左右 sticky，以横向滚动访问；工具栏实心按钮仍为 md/36px，不套用 link 高度。

## 状态与交互

hover 使用同族浅底和深色文字；active 进一步加深文字。鼠标点击后不因普通 `:focus` 残留强调底色；键盘 `:focus-visible` 保留 2px 品牌金轮廓，offset 3px。颜色过渡 160ms，减少动态模式关闭过渡；高频行操作不做缩放或位移。

disabled 使用 #9CA3AF，link 保持透明底、不响应 hover/active。loading 保留语义色、文字和旋转图标，opacity 0.7，阻止重复提交；显式 disabled 优先。事件、权限、条件显示、行数据与确认流程必须保留。

## 修复对照

| 之前 | 之后 |
|---|---|
| GlassButton 亮金字、EP 深金/灰字、PM 另一套红色 | 四种深色语义文字，默认 link 同为 primary |
| link 高度 21/23/26.8px、12/13px 字号、12/3px 圆角 | 桌面最小24px，13px文字，0圆角；触屏最小44px |
| GlassButton link 带默认阴影和按压缩放 | link 无阴影、无缩放；保留键盘轮廓 |
| warning tone 未实现、删除内联颜色 | 支持 warning；删除 danger 覆盖所有状态 |
| 64处缺图标、3处操作列实心/描边 | 显式语义图标、统一 link；展开卡片打印同样收口 |
| 主站与 PM 设计文档仍描述蓝色按钮 | 设计规范、两个 token 文件与组件接口一致 |

## 验收

1. `node --test frontend/tests/tableActions.test.mjs frontend/tests/sharedUi.test.mjs`：全量操作列布局/图标/link/内联色检查、复用导出菜单、token 对比度和 PM 一致性、点击/禁用/加载行为。
2. 主站和 PM 分别 `npm run build`；仓库 `python scripts/check_conventions.py`、`python scripts/git_sweep.py --no-fetch`。
3. `python frontend/tests/actionButtons.browser.py --url http://localhost:3000/tests/fixtures/table-actions/`：核对四语义及默认、hover/active/focus/disabled/loading、单个加载图标及非 link 变体的对比度。另用实际组件与样式渲染从全量模板提取的按钮案例；宽屏与触屏检查尺寸、长文案、固定列和下拉交互，不对生产业务发起写请求。
4. 校验修改前后事件、权限、条件与脚本不变。实际验证结果记录在 [修复验收报告](../reports/2026-10-02-action-button-consistency.md)，本地验收不代表生产已发布。
