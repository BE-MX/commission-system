# 出库单打印状态筛选发布记录

2026-10-08 按亮哥“合并推送部署”授权，功能提交 `c5c03bea6556950fc768a11d810e4be6fd122ee8` 已合并到主目录 `main` 并推送 `origin/main`。办公室 SSH 转发由用户恢复后，通过办公室安装目录的 `deploy/deploy.bat --revision <上述 SHA> --no-pull` 先 prepare-only、再正式发布，两阶段退出码均为 0。

出库单打印页新增「出库单状态」「检验状态」两个可清空筛选项，支持与关键词、日期、订单 ID 组合查询。选择后点击查询生效；翻页、排序保留已提交条件，重置清除筛选。订单 ID 放入展开筛选。检验状态只筛正式出库单，不将检验栏显示“—”的待生成任务当作“未检验”。

| 核验项 | 结果 |
| --- | --- |
| 发布回执 | succeeded；release_id `0d22424007b140ac9774935ce33ef85c`；office-and-cloud；deferred=[] |
| 办公室、北京 HEAD | 均为上述应用候选 SHA；办公室 Git 状态干净 |
| 两地健康 | status=ok，database=connected |
| API 参数 | 两地 OpenAPI 均有 `outbound_state` 八种枚举、`inspection_status` 三种枚举，值域与候选一致 |
| 后端制品 | 两地 `outbound_queue_service.py`、`router.py` 规范化 SHA256 与候选一致 |
| 生产只读查询 | MySQL 会话显式只读、单条查询上限 15 秒；最近 30 天、每组最多取两行，八种出库状态及三种检验状态组合查询均成功。已生成、待同步、待核对及三种检验状态取得实际样本并匹配；其余状态当前无样本，状态映射由隔离回归覆盖 |
| 公网前端 | leshine.work、leshine.cloud、pm.leshine.work 共 11 项入口、主脚本/样式、出库页脚本/样式 SHA256 与构建清单一致；出库脚本包含两个筛选参数和对应中文文案 |
| 数据库 | 仍为 `175_receipt_recovery`，本次 schema_changed=false，无迁移 |
| 出库调度 | verified；timer active/enabled，保持原状态 |
| 邮件 Worker | inactive/disabled，MainPID=0，保持原基线 |

本地后端状态筛选、队列、排序共 71 项隔离测试，前端筛选、操作、useListPage 共 17 项测试均通过；构建通过。独立审查无阻塞项，提交后以基点 `026d2386` 运行严格约定检查通过。部署期间复用预检构建与远端暂存文件，不再重复传输。

主目录原有 24 项未提交改动均保留并核验，未夹带进提交。原始文件备份、恢复核验、prepare/publish 日志、office/beijing/public/source 核验以及生产只读查询结果保存在 `.deploy_state/outbound-status-filters-release/`。Git 巡检采用 `--no-fetch` 本地快照。浏览器连接不可用，未做真实登录态界面操作；已验证接口契约、生产查询语义、前端行为测试及线上制品。其他未纳管服务和待开通站点按既有部署清单保留，不计作本次更新。

本记录为发布后的文档提交，不改变已核验的应用候选版本。
