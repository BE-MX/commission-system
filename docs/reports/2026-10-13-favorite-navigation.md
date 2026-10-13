# 常用导航实现与验收

本地分支 `codex/favorite-navigation`，基点 `c15b1d2c`。侧栏品牌下新增常用导航；管理弹窗支持搜索、勾选添加与取消勾选移除，手柄拖拽或 `Alt + ↑/↓` 排序，修改即时保存。服务端按 JWT 当前用户保存，刷新及换浏览器可恢复；内部跳转复用当前路由，外部菜单保持新标签打开。候选与显示条目沿用当前菜单权限，失去权限仅隐藏，不删除原配置。

配置独立于工作台布局，新增 `ark_navigation_preferences`，迁移 `194_navigation_preferences -> 193_wa_ai_assistant`，模型进入 Alembic metadata。保存期间禁用重复修改，切换用户同步清空旧配置且丢弃迟到响应；写失败先读取确认，读取也失败时禁用编辑并提供重试读取。

用户补充的权限限制已加严：候选同时校验菜单、分组与路由声明，避免公告管理等“菜单可见但路由无权限”的条目进入候选。PUT 新增标识按数据库实时授权校验，未知/无权新增403，旧JWT超级管理员也不能绕过；已撤权条目隐藏且保留，删除后无权重加403。禁用账号不能保存。

前端构建同步生成后端源码内 `navigation_access_manifest.json` 并记录 `navigation.js` 内容SHA256（规范化换行）。清单必须随源文件提交/交付，不手工维护。后端不依赖忽略的前端dist或独立静态站路径，清单缺失/损坏/过期返回503并拒绝新增；构建清单失败阻断构建。隔离测试已验证无dist目录仍可加载，与源文件不符则拒绝。

## 验证证据

- `npm run build`：成功；保留现有大 chunk 与 auth store 混合导入警告。
- `node --test tests/favoriteNavigation.test.mjs tests/taskCenter.test.mjs tests/navigationLayout.test.mjs tests/mainLayoutMobile.test.mjs`：24 passed，含真实导航权限边界、前后端生成清单规则一致性与现有任务中心契约。
- `node --experimental-vm-modules --test tests/favoriteNavigationRequests.test.mjs`：5 passed，覆盖迟到读取、迟到保存、保存锁定、超时后读取而不重发、读取失败锁定与恢复、无权项不发新增请求。
- 隔离 SQLite：`python -m pytest tests/test_navigation_preferences.py -q`，13 passed。覆盖真实 HTTP/JWT 用户隔离、参数校验、空配置、排序、清空、实际重复 INSERT 恢复、commit 失败回滚、非北京时间源时钟与北京时间午夜边界（创建/更新时间），以及无权/未知项拒绝、撤权旧JWT、禁用账号、缺失/坏/过期清单与无dist部署结构。第三方 jose 产生原有 UTC 弃用告警。
- `python -m alembic heads`：唯一 `194_navigation_preferences`；导入 `app.models` 后 metadata 含新表；独立审查确认 unsigned FK 类型正确。
- Edge headless 真实侧栏 + 真实配置 API + 内存 SQLite：`frontend/tests/favoriteNavigation.browser.mjs` passed。覆盖添加、移除、拖拽、刷新、页面跳转及高亮、Alice/Bob 隔离、外链目标、键盘排序、折叠点击、390px 弹窗边界、搜索与权限恢复；确认公告管理/运单上传无权候选不可见，真实构建清单下无权与未知键直接PUT均403。浏览器 pageerror 为零，所有请求只访问本机测试端口。

浏览器复跑：backend 用项目虚拟环境启动 `python -m uvicorn tests.navigation_fixture_server:app --host 127.0.0.1 --port 8347`；frontend 启动 `npm run dev -- --host 127.0.0.1 --port 3347 --strictPort`。设置 `NAV_PLAYWRIGHT_MODULE` 指向可用 Playwright 模块、`NAV_QA_OUTPUT` 指向本地证据目录，运行上述 browser 脚本。测试服务仅创建内存 SQLite，不加载生产业务实例；前端 fixture 仅配置 API 实际请求该服务，其余业务 client 为测试适配器。

本地证据位于 `tmp/favorite-navigation/`：`result.json`、`desktop.png`、`mobile-manager.png`、`build.log`。fixture 与浏览器脚本保留以便复跑。

## 审查与交付边界

独立 agent 审查发现 Alembic metadata 缺少新模型注册，已修复、实查并复审通过。浏览器首轮发现 RouterLink 被无值 href 属性覆盖，已修复为内外链接分别传有效属性并通过完整复跑。排序为高频操作，不新增拖拽动画；遵循项目 UI 色彩令牌，弹窗使用标准尺寸/按钮并在窄屏检查可达性。

权限专项独立审查发现北京后端代码目录与前端静态产物目录不同，读取仓库dist会失败或误用旧清单。已改为随Git源码交付带源哈希的后端清单，防止路径差异与版本漂移。

`python scripts/check_conventions.py` 全仓门禁仍被原有 17 项发票表格 UI 债务阻断（固定列宽与旧 deep override 基线）；本次新增弹窗尺寸、按钮和样式问题已处理，本次增量规则 0 项。`git diff --check` 通过。按项目约定执行 `python scripts/git_sweep.py --no-fetch`，只报告本地快照，不据此修改其他任务。

用户已授权提交、合并main并推送origin，交付范围仅本次常用导航改动。主目录原修改先备份、临时收起，合并后恢复核验；必要浏览器证据与Git集成回执保留于主目录 `tmp/favorite-navigation-integration/`，任务worktree在整合验证后清理。

未部署，未执行共享库或生产迁移。生产上线须通过统一发布入口审核现役代码/迁移路径，不能从开发机升级共享库。推送main不代表功能已上线。
