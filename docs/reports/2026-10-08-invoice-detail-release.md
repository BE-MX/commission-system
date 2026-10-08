# 订单发票关联详情发布记录

2026-10-08 按亮哥“合并推送部署”授权完成。功能提交 `b0f322fa` 与最新主线整合后，固定应用候选 `ddc4a5a5e21d34189b4477dc3418ed7db6c8b617` 已合入并推送 `origin/main`，远端回读一致。办公室 SSH 转发恢复后，在生产安装目录通过既有 `deploy/deploy.bat --revision <候选> --no-pull` 先 prepare-only、再正式发布，两次均退出 0。

用户刷新订单发票页面后，点击发票号即可打开订单详情、出库单详情、回款单详情。顶部回款与实际出库进度独立展示；异常发票显示红色静态荧光标识，相应导航显示黄色叹号。实际用户范围由原发票、回款、出库和检验权限分别约束，详见[实现与验收](../requirements/2026-10-08-invoice-detail-implementation.md)。

| 核验项 | 结果 |
| --- | --- |
| 发布回执 | succeeded；release_id `444e65ef05d5472084a1471ff15567b9`；office-and-cloud；deferred=[] |
| 办公室、北京实际 HEAD | 均为完整应用候选 SHA；办公室 Git 状态干净 |
| 两地健康 | status=ok、database=connected |
| 新接口 | 两地 OpenAPI 均注册四个 GET：`/api/invoice/document-anomalies`、`/api/invoice/invoices/{invoice_id}/related-detail` 及其 `/receipts`、`/outbounds` |
| 详情后端源码 | detail_access、detail_router、detail_receipts、detail_outbounds、document_anomalies、router 六文件在两地的规范化 SHA256 与候选一致 |
| 公网制品 | leshine.work、leshine.cloud、pm.leshine.work 共 20 项 HTML、导航、发票/布局/主脚本及样式 SHA256 匹配候选构建清单 |
| 数据库 | 本功能无迁移；统一发布带上主线 `174→175_receipt_recovery`，共享迁移日志 completed；实际四列、两张新表及三个索引只读核验通过 |
| 出库调度 | 发布回执 verified，timer active/enabled，恢复原状态 |
| 邮件 Worker | inactive/disabled、MainPID=0，保持原基线 |

合并候选再次通过后端 182 项隔离回归、前端详情与出库操作 8 项回归、生产构建（3409 模块）、严格增量约定与 diff 检查。详情代码完成独立资金、权限和状态审查；175 迁移另经独立审查，唯一父链、历史未知状态保护及 writer 停止/恢复规则无阻断问题，三项隔离迁移测试通过。

第一次公网检查在下载既有项目管理资源时超时；保留正常 TLS 验证，改为 IPv4/HTTP1.1、有界重试并丢弃不完整下载后，20 项全部通过。北京侧另经公开 HTTPS 独立核验发票脚本，摘要同样匹配。没有重复发布。后检只检查版本、健康、注册接口、数据库结构及制品，未通过详情入口登记真实回款或生成出库单。不同真实账号权限体验、真实租户全量关联扫描耗时未逐项实测，隔离回归覆盖相关权限与汇总口径。

主目录原有 24 项未提交改动全部保留，重叠 handoff 文档保留新增发布段落及原有改动并逐项核验。备份、prepare/publish 日志、office/beijing/public/backend/schema 验证 JSON、临时预览验证脚本及恢复校验位于 `.deploy_state/invoice-detail-release/`。Git 巡检采用 `--no-fetch` 本地快照；只清理本任务已合并且无独有改动的 worktree/分支，不处理其他代理成果。

既有未纳管服务及待开通站点继续按部署目标清单列示，不属于本次发布范围。本记录为事后文档提交，不改变已验证应用候选。
