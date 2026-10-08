# 订单改单回款修正发布记录

2026-10-08 按用户“合并推送部署”授权完成。应用候选 `45e57ca874310f77460e3f59b511020af43a6403` 已合入并推送 `origin/main`，远端回读一致。办公室 SSH 转发恢复后，通过既有 `deploy/deploy.bat --revision <固定候选> --no-pull` 先 prepare-only、再完整发布，两次均退出 0。

| 核验项 | 结果 |
| --- | --- |
| 发布回执 | succeeded；release_id `d59340745c1c43cc9f49f463ae0f9309`；office-and-cloud；deferred=[] |
| 办公室、北京实际 HEAD | 均为完整应用候选 SHA；受 Git 管理的生产目录干净 |
| 两地健康 | status=ok、database=connected |
| 回款新端点 | 两地 OpenAPI 均有 GET `/api/receipts/invoice-summary/{invoice_id}` |
| 回款后端源码 | invoice_link.py、router.py、service.py 三文件在两地的规范化 SHA256 均与候选一致 |
| 公网制品 | leshine.work、leshine.cloud、pm.leshine.work 共 16 项 HTML、导航、主脚本、发票/回款资源及样式摘要匹配办公室候选 |
| 数据库 | `173_task_center`，没有新增迁移或 DDL |
| 出库调度 | 发布回执 verified；timer active/enabled，恢复原状态 |
| 邮件 Worker | inactive/disabled、MainPID=0，保持原基线 |

合并后隔离 SQLite/模拟小满的后端 202 项、前端 43 项回归通过。前端生产候选在服务器完成构建；严格增量约定及差异检查通过，独立代码审查无剩余阻断。开发验收详见[实现记录](2026-10-08-invoice-receipt-correction.md)。

本机默认 HTTP 代理造成第一次公网读取 TLS EOF，改为 curl 直连后 16 项全部通过，保留正常证书验证。发布未重复执行。本次后检仅检查版本、健康、接口注册与制品，没有修改生产订单、创建/发送真实回款或执行退款。

主目录原有 24 项未提交改动全部保留：无关文件内容一致，重叠文档以保留本次新增段落及原改动的合并结果逐项核验。备份、prepare/publish 日志、office/beijing/public/backend 验证 JSON 与恢复校验在主目录 `.deploy_state/invoice-receipt-correction-release/`；Git 巡检使用 `--no-fetch` 本地快照，不据此删除其他代理分支。

既有未纳管服务及待开通站点仍按部署目标清单列示，不属于本次订单回款发布范围。本发布记录为事后文档提交，不改变已验证应用候选。
