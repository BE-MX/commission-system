# 2026-11-03 最新远端 main 生产发布

用户授权“拉取最新代码并进行生产部署”。已拉取并固定远端 main，使用办公室受管候选的 `deploy/deploy.bat --live-root D:/commission-system --revision <完整 SHA> --no-pull`，先 prepare-only、后正式激活。

## 发布结果

- 固定版本：`cc2112e7ff3571934846afc350c737844a3bd6d1`。
- 原生产应用：`b817650a69a6865886c9f4d7a0c61bc1ec9ec807`。
- 发布 ID：`1d6adf8542f84accbc1698e45cb2c288`；范围 `office-and-cloud`。
- 准备退出码 0，耗时 423.94 秒；正式激活退出码 0，耗时 208.03 秒。耗时包含校验、传输和切换，不是停服时长。
- 办公室与北京实际 Git HEAD 均已独立读回为固定版本；`publish-current.json` 为 `succeeded`，必需目标无 deferred。
- 数据库保持 `247_sales_return_freight`，没有新增迁移，本轮不执行 DDL。

## 本次上线内容

- 发票页顶部 GMV、平均订单金额排除手续费；“应付合计”前显示不含手续费的“订单金额”，两列隐藏 USD 前缀。
- 客户素材批次的确认后一键清空，以及上传弹窗重开时重置标签选择和锁定状态。
- 工资工作台按钮布局、钉钉考勤取数与未知假期类型保护修复。
- 出库发布门禁诊断和有界锁竞争重试改进。

## 验证与运行状态

- 本次部署相关隔离回归：59 passed；主站生产候选构建通过。未变化的 PM/门户按部署器规则复用。
- 独立后检 26 项必需检查全部通过：办公室服务/数据库、北京服务/数据库、新加坡至办公室隧道、公网鉴权及全部已登记静态站。
- `leshine.work`、`leshine.cloud`、`pm.leshine.work`、`media.leshine.cloud`、`shop.leshine.cloud` 均 HTTPS 200，证书校验通过；发布器已核验对应静态制品。
- 北京出库轮询器为 legacy，发布回执 verified、release_confirmed=true，调度 active/enabled，符合原基线。
- 邮件 Worker 保持原 inactive/disabled；新加坡旧 okki-sync 保持 inactive/masked。未纳管或无探针的独立服务不计入更新成功范围。
- 没有执行真实订单、退款、素材删除或考勤同步写入验收；健康与版本验证不等同于这些业务操作成功。

## 已知数据限制与保留范围

- `宋皓月浅色库存 0939` 的 USD 44.17 已被用户确认是运费，但方舟仍误填手续费字段。本次只部署代码，未另行更正该生产记录；因此发票页仍会按现存字段少计这一笔，正确净额应为 477.67。详见 [GMV 口径核查](2026-11-02-gmv-fee-basis-audit.md)。
- 本地 main 的 7 个未推送提交保留，不作为本次发布源，也未推送 origin；主目录原有 119 个改动/未跟踪文件在发布后逐文件哈希一致。
- 本报告与 `docs/handoff.md` 的新增记录保留为本地未提交文档，不夹带其他人的修改。
- 静态与候选历史制品维护按部署器约定 deferred，保留待维护回执；本次不额外清理服务器历史制品或业务数据。

## 证据

本机：`.deploy_state/full-main-release-20261103-cc2112e7/`。

关键文件：`release-request.json`、`preflight.json`、`candidate.log`、`prepare-readback.json`、`activate-readback.json`、`postcheck.json`、`deploy-checks.log`、`local-preservation.json`、`local-preservation-final.json`、`git-sweep.log`。

办公室同名目录保存 prepare/activate 原始日志、退出码及后台进程记录。生产回执与维护记录位于安装目录 `.deploy_state/`。Git 巡检使用 `--no-fetch`，作为本地引用快照，不自动处置其他分支。
