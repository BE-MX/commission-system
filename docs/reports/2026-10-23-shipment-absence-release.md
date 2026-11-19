# 预售原出库任务恢复流程发布

2026-10-23，按“合并推送拉取最新代码部署”的授权，已将原任务恢复修复与当时最新 `origin/main` 集成，推送并完成办公室及云端完整受管发布。

- 发布提交：`8a9d76400aadfed5d3c8bc6e06db5f6693916588`，包含最新主线 `31989dec`；原修复提交 `7d346989`。
- 发布 ID：`e5dc379959314ab6aac255cfc2d155fd`；`publish-current` 为 `succeeded`，`publish-success` 的 revision/schema 与现场一致。
- 受管完成目标11项，`deferred=[]`。保留原调度及邮件工作器运行基线；未启用未纳管服务。
- 数据库仍为 `202_presale_order_revision`，无待执行迁移，本次没有执行DDL。
- 办公室 `CommissionSystem` 为 RUNNING，北京 `ark-backend` 为 active；两端 `/health` 均为 HTTP 200、数据库 connected，运行 checkout 均为本次提交且无 tracked 改动。
- 两端实际 OpenAPI 均注册 `POST /api/shipments/{identity}/recover-outbound`，恢复模块的换行归一化 SHA256 为 `8f41b15813bec24fe33d1fee63d616517c9d03a59d2f917897a0f481bb88c357`。
- 公网 `www.leshine.cloud`、`leshine.work` 均读取到相同新入口摘要 `16c780fde1b4d27fb7f68ee20ff7705dc6b8a272ccbe2e18fdb6852a6f42e340`，入口 `main-DrGr9ozV.js` 引用的 `InvoiceManage-5rg7-RCz.js` 包含恢复入口。该验证是资源与接口上线证据，不代替实际员工登录后的业务验收。

## 字体预检阻断与修正

首轮 prepare 在任何生产切换前被新主线的 ReportLab 字体检查阻断：北京原 `PDF_CJK_FONT_PATH` 指向 Noto CJK 的 CFF 集合，Pillow 可读取但 ReportLab 无法嵌入。没有跳过该检查。

依照主线已有[字体修复说明](2026-10-23-portal-pi-font-repair.md)，安装已暂存、校验的文泉驿字体及其版权文件，先以真实 Pillow/ReportLab 验证，再只替换北京 `backend/.env` 的 `PDF_CJK_FONT_PATH` 完整行。配置其余字节、UID/GID及权限位验证不变，旧配置保存在服务器权限受限的 `.deploy_state/shipment-font-config-8a9d7640/backend.env.before`，未复制到开发机或Git。

新字体位于 `.deploy_state/fonts/wqy-zenhei-0.9.45-8/wqy-zenhei.ttc`，SHA256 为 `79c18ebe7b811951e8311bad7103ebeae8c337ed9988ea69e8a78a66cfe029b9`。修正后重新完整 prepare，通过后由同一候选 `deploy/deploy.bat --live-root D:/commission-system --revision <完整SHA> --no-pull` 激活。没有手工启动服务或修改业务数据。已验证部署后的字体及配置摘要，未以此声称真实客户PI下载已验收。

## 集成验证与保护

- 集成后受影响后端71项通过；前端76项通过、1项既有失败：`invoiceMerchandiser.test.mjs:40` 仍按旧“库存”文案做静态匹配。该测试文件及其直接匹配的产品表源码与集成前最新主线的Git blob完全一致，未弱化断言。
- 主站生产构建、覆盖提交差异的约定检查及独立集成复核通过。此前修复还通过新增SQLite 28项、隔离真实MySQL 20项及浏览器7场景；详见[实现报告](2026-10-23-shipment-absence-recovery.md)。
- 主目录原有80个改动/未跟踪文件先保存原HEAD、index、二进制补丁、文件副本和SHA256。除本任务对API文档追加及对交接记录前置外，其余保护文件摘要不变；两文档保留原始字节。未把原有修改提交或推送。
- 发布器按默认协议将静态与候选制品保留清理登记为后续维护；这不属于延后发布目标，本次未另行执行生产制品删除。
- 本任务worktree已由应用保存可恢复快照并归档，非忽略的临时UI夹具包含在快照中；必要验证证据已先复制到主目录保护文件夹。确认原分支已合入main后，仅删除本任务本地分支。最终Git巡检 `--no-fetch` 退出0，index及冲突路径为空；主目录原有改动和本次发布记录保留为未提交内容。

## 操作与边界

刷新页面后，由具备当前权限的管理员进入“订单分批出库 → 出库结算记录 → 原待核对批次 → 核实未生成并恢复”。需核实小满原请求已经终止、未生成且不会随后生成，提供记录引用并主动确认。当前404不能单独证明终态；已有原单应使用“核对出库单”绑定。

本次只交付并发布流程，没有对 Veronika 第二批提交终态声明、恢复任务或重发出库，也未变更其价格、运费、回款及资金分配。

本地保护和验证证据：`tmp/shipment-recovery-integration-20261023-2220/`；办公室发布日志和进程回执：`.deploy_state/shipment-absence-release-font-8a9d7640/`。这些证据及原始恢复材料保留，发布记录不包含生产凭据或客户付款凭证。
