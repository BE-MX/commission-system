# Memory

> Chronological action log. Hooks and AI append to this file automatically.
> Old sessions are consolidated by the daemon weekly.

| HH:MM | description | file(s) | outcome | ~tokens |
|-------|-------------|---------|---------|---------|
| 11:01 | 完成生产进度报工系统全量开发 | backend/app/production/*, alembic/027 | 后端 import 通过，前端 build 成功 | ~45k |
| 11:15 | 完成收尾：工序绑定+微信ID+进度看板+打印卡 | UserManagement.vue, ProductionOrderManage.vue | 前端 build 通过 | ~18k |

## Session: 2026-06-03 JimuReport → Stimulsoft 迁移

| Time | Action | File(s) | Outcome | ~Tokens |
|------|--------|---------|---------|--------|
| 00:00 | 复制 Stimulsoft 静态资源 | frontend/public/vendor/stimulsoft/reports-js/ | 4个.pack.js + zh-CHS.xml 就位 | ~200 |
| 00:05 | 创建 028 迁移 + ReportTemplate ORM | alembic/028_add_report_template.py, app/report/models.py | ark_report_templates 表 | ~800 |
| 00:10 | 创建后端报表领域模块 | app/report/{router,schemas,data_service}.py | 6 个端点 + 数据组装 | ~3000 |
| 00:15 | 注册路由替换 JimuReport | app/routers.py | jmreport_router → report_center_router | ~100 |
| 00:20 | 创建前端 Stimulsoft 集成 | composables/useStimulsoft.js, components/StimulsoftViewer.vue | 动态加载 + Viewer 组件 | ~2000 |
| 00:25 | 替换生产订单打印入口 | ProductionOrderManage.vue | iframe → StimulsoftViewer 组件 | ~300 |
| 00:30 | 清理 JimuReport | 删除 jmreport.js/stores/jmreport.js/views/jmreport/api/jmreport.py + config.py JMREPORT_* | 无残留引用 | ~200 |
| 00:35 | 更新导航和报表中心页 | navigation.js, views/report/{ReportCenter,ReportView}.vue | 报表中心+查看页 | ~1500 |
| 00:40 | 更新 CLAUDE.md | 积木报表→Stimulsoft 架构文档 | 端口/项目结构/API路由/文档全量替换 | ~1000 |
| 00:45 | 后端 import 验证 + 前端 vite build | 全量 | 后端通过，前端 build 成功 | ~500 |

## Session: 2026-06-03 neat-freak 知识库整理

| Time | Action | File(s) | Outcome | ~Tokens |
|------|--------|---------|---------|--------|

## Earlier Sessions (consolidated summaries)

- **2026-06-02**: 颜色排序修复（双层 REGEXP_REPLACE），Stimulsoft 迁移计划+执行（028/029 迁移，report 领域模块，前端 Designer/Viewer 组件），JMREPORT 环境变量清理
- **2026-06-01**: 生产报工模块全量开发（027 迁移，6 表，28 端点），scheduler.py import 修复，UserManagement 工序绑定，ProductionOrderManage 进度看板+打印卡
- **2026-05-29**: JimuReport Java 微服务搭建（pom.xml + application.yml + SSO），前端 JmReportView + stores/jmreport，部署脚本
- **2026-05-28**: 备货管理性能优化（overview/safety SQL 化分页），Asset lazy=noload + selectinload 优化，文件夹上传 update_duplicates 开关
- **2026-05-27**: 安全库存设置列表增强（排序/筛选/备货状态），列表表头排序统一改造（28 个表格 + useTableSort composable）
- **2026-05-26**: 生产订单管理模块开发（025/026 迁移，购物车/批量下单/双维管理/入库/加急），移动端登录闭环，文件上传合并逻辑优化
- **2026-05-25**: 移动端素材库 bug 修复（v-if 配对/Vue CDN prop/竞态条件），下载双模式认证（JWT+签名 token），标签筛选性能优化
- **2026-05-23**: 文件夹上传支持视频/文档类型
- **2026-05-22**: ark_asset_tags 复合主键修复（023 迁移）
- **2026-05-21**: 发色数字化模块 P0-P3（022 迁移），移动端素材库标签搜索+联动筛选
- **2026-05-20**: 阶段二后端治理（五域 facade+子模块），情报采集库+行业速览（021 迁移），素材文件夹批量上传，标签维度图片
- **2026-05-19**: 素材管理模块 Phase 1-3（020 迁移），AI 打标签/版本迭代/收藏分享/统计报表/移动端
| 07:17 | Created C:/Users/windb/.claude/projects/D--MyProgram-commission-system/memory/project_stimulsoft_module.md | — | ~724 |
| 13:35 | Edited frontend/src/views/report/ReportCenter.vue | added optional chaining | ~302 |
| 13:36 | Edited frontend/src/views/report/ReportCenter.vue | reduced (-25 lines) | ~79 |
| 13:37 | Edited frontend/src/composables/useStimulsoft.js | added 1 condition(s) | ~421 |
| 13:48 | Edited frontend/src/composables/useStimulsoft.js | modified if() | ~277 |
| 13:55 | Edited frontend/src/composables/useStimulsoft.js | expanded (+6 lines) | ~145 |
| 13:57 | Edited frontend/src/composables/useStimulsoft.js | modified for() | ~333 |
| 14:07 | Edited C:/Users/windb/.claude/projects/D--MyProgram-commission-system/memory/project_stimulsoft_module.md | expanded (+17 lines) | ~301 |
| 14:08 | Edited CLAUDE.md | 7→10 lines | ~115 |
| 14:08 | Edited CLAUDE.md | 2→3 lines | ~46 |
| 14:10 | Edited CLAUDE.md | 3→5 lines | ~119 |

## Session: 2026-06-03 14:12

| Time | Action | File(s) | Outcome | ~Tokens |
|------|--------|---------|---------|--------|
| 14:40 | Edited backend/app/report/data_service.py | 2→1 lines | ~10 |
| 14:41 | Session end: 1 writes across 1 files (data_service.py) | 8 reads | ~9570 tok |
| 14:43 | Edited frontend/src/components/StimulsoftViewer.vue | CSS: ready | ~429 |
| 14:44 | Session end: 2 writes across 2 files (data_service.py, StimulsoftViewer.vue) | 8 reads | ~10113 tok |

## Session: 2026-06-03 14:55 — Stimulsoft 打印弹框卡死修复 + neat-freak 同步

| Time | Action | File(s) | Outcome | ~Tokens |
|------|--------|---------|---------|--------|
| 15:07-15:28 | 修复 StimulsoftViewer 三重 bug | StimulsoftViewer.vue, useStimulsoft.js, ReportCenter.vue | ensureLoaded 替代 watch 死锁；renderHtml/report 顺序修正；响应解包修正 | ~20k |
| 15:48-15:50 | neat-freak 知识库同步 | cerebrum.md, buglog.json, README.md, project_stimulsoft_module.md | 4 文件更新 | ~5k |
| 15:53 | Session end: 13 writes across 5 files (useStimulsoft.js, StimulsoftViewer.vue, ReportCenter.vue, README.md, project_stimulsoft_module.md) | 14 reads | ~22639 tok |

## Session: 2026-06-03 15:57

| Time | Action | File(s) | Outcome | ~Tokens |
|------|--------|---------|---------|--------|
| 16:07 | Edited frontend/src/views/report/ReportCenter.vue | CSS: order_no | ~100 |
| 16:08 | Edited frontend/src/composables/useStimulsoft.js | added error handling | ~406 |
| 16:08 | Edited backend/app/report/data_service.py | 5→6 lines | ~85 |
| 16:09 | Session end: 3 writes across 3 files (ReportCenter.vue, useStimulsoft.js, data_service.py) | 5 reads | ~8548 tok |
| 16:28 | Edited backend/app/report/data_service.py | expanded (+7 lines) | ~134 |
| 16:28 | Session end: 4 writes across 3 files (ReportCenter.vue, useStimulsoft.js, data_service.py) | 5 reads | ~8682 tok |
| 17:07 | Edited backend/app/report/data_service.py | modified get_process_card_print_data() | ~338 |
| 17:08 | Edited backend/app/report/data_service.py | expanded (+11 lines) | ~286 |
| 17:08 | Edited frontend/src/views/stock/ProductionOrderManage.vue | printOrder() → handlePrintCommand() | ~134 |
| 17:09 | Edited frontend/src/views/stock/ProductionOrderManage.vue | CSS: StimulsoftViewer | ~79 |
| 17:10 | Edited frontend/src/views/stock/ProductionOrderManage.vue | printOrder() → handlePrintCommand() | ~151 |
| 17:11 | Session end: 9 writes across 4 files (ReportCenter.vue, useStimulsoft.js, data_service.py, ProductionOrderManage.vue) | 6 reads | ~19155 tok |
| 17:20 | Edited backend/app/report/data_service.py | modified get_process_card_print_data() | ~351 |
| 17:20 | Edited backend/app/report/data_service.py | 6→7 lines | ~72 |
| 17:21 | Session end: 11 writes across 4 files (ReportCenter.vue, useStimulsoft.js, data_service.py, ProductionOrderManage.vue) | 7 reads | ~22790 tok |
| 17:28 | Edited backend/app/report/data_service.py | 12→12 lines | ~102 |
| 17:30 | Session end: 12 writes across 4 files (ReportCenter.vue, useStimulsoft.js, data_service.py, ProductionOrderManage.vue) | 7 reads | ~22892 tok |
| 17:37 | Session end: 12 writes across 4 files (ReportCenter.vue, useStimulsoft.js, data_service.py, ProductionOrderManage.vue) | 7 reads | ~22892 tok |
| 17:39 | Edited backend/app/production/report_service.py | modified get_qrcode() | ~99 |
| 17:39 | Edited backend/app/report/data_service.py | 3→3 lines | ~29 |
| 17:40 | Session end: 14 writes across 5 files (ReportCenter.vue, useStimulsoft.js, data_service.py, ProductionOrderManage.vue, report_service.py) | 7 reads | ~23020 tok |

## Session: 2026-06-03 17:46

| Time | Action | File(s) | Outcome | ~Tokens |
|------|--------|---------|---------|--------|
| 17:53 | Edited backend/app/production/router.py | added 3 import(s) | ~132 |
| 17:55 | Edited backend/app/production/router.py | 16→13 lines | ~114 |
| 17:58 | Session end: 2 writes across 1 files (router.py) | 9 reads | ~13666 tok |
| 18:02 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:08 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:09 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:10 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:13 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:16 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:18 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:24 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:25 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:31 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:41 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:42 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:43 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:45 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:47 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:48 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |
| 18:49 | Session end: 2 writes across 1 files (router.py) | 10 reads | ~13795 tok |

## Session: 2026-06-03 18:52

| Time | Action | File(s) | Outcome | ~Tokens |
|------|--------|---------|---------|--------|
| 18:56 | Edited CLAUDE.md | inline fix | ~16 |
| 18:56 | Edited backend/app/production/router.py | 3→3 lines | ~45 |
| 18:57 | Edited project_production_reporting_module.md | 2→2 lines | ~31 |
| 18:58 | Edited cerebrum.md, buglog.json, anatomy.md | neat-freak 同步：报工鉴权移除 + JimuReport 残留清理 | ~3000 |
| 19:04 | Session end: 3 writes across 3 files (CLAUDE.md, router.py, project_production_reporting_module.md) | 5 reads | ~14083 tok |
| 19:17 | Session end: 3 writes across 3 files (CLAUDE.md, router.py, project_production_reporting_module.md) | 5 reads | ~14083 tok |
| 19:30 | Session end: 3 writes across 3 files (CLAUDE.md, router.py, project_production_reporting_module.md) | 6 reads | ~17303 tok |
| 19:33 | Session end: 3 writes across 3 files (CLAUDE.md, router.py, project_production_reporting_module.md) | 6 reads | ~17303 tok |
| 19:36 | Edited backend/app/production/report_service.py | modified except() | ~300 |
| 19:36 | Session end: 4 writes across 4 files (CLAUDE.md, router.py, project_production_reporting_module.md, report_service.py) | 6 reads | ~17603 tok |
| 19:44 | Session end: 4 writes across 4 files (CLAUDE.md, router.py, project_production_reporting_module.md, report_service.py) | 6 reads | ~17603 tok |
| 19:46 | Edited backend/app/production/report_service.py | modified _bj_now() | ~44 |
| 19:46 | Edited backend/app/production/report_service.py | inline fix | ~11 |
| 19:46 | Edited backend/app/production/report_service.py | inline fix | ~10 |
| 19:46 | Edited backend/app/production/report_service.py | inline fix | ~17 |
| 19:47 | Session end: 8 writes across 4 files (CLAUDE.md, router.py, project_production_reporting_module.md, report_service.py) | 6 reads | ~17685 tok |
| 20:01 | Session end: 8 writes across 4 files (CLAUDE.md, router.py, project_production_reporting_module.md, report_service.py) | 6 reads | ~17685 tok |

## Session: 2026-06-04 08:36

| Time | Action | File(s) | Outcome | ~Tokens |
|------|--------|---------|---------|--------|
