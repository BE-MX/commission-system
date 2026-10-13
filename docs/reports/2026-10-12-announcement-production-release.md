# 公告推送选项生产发布记录

2026-10-12，用户在公告开关改动合并推送后明确要求部署。办公室及北京应用发布成功，真实版本均为 `c797c45e6198d8a5de761342076d757ed5efb13d`；公告修订的 `push_dingtalk` 已进入生产数据库。原发布身份 `b68389384a5e4e8b8f69bf4223f0ee8e` 全程保留。

## 版本与数据保护

- 发布开始时 main 为 `9afa3cb5`，线上为包含门户密码登录的 `9e16a4e1`。候选合并两者，保留线上门户、经营门禁及 shop 静态目标；控制程序的后续恢复提交不改变业务候选。
- 共享库由 `183_portal_password_login` 执行 184、185、186，最终单 head 为 `186_portal_announcement_merge`。原183及184/185父节点保留，不回退或 stamp。
- 办公室、北京原有三张未跟踪头像先验证 SHA256 与已提交素材一致，再保留原件备份；未覆盖未知业务素材。
- 本次固定候选之后，其他任务向 main 合并了 `9cae79df` / `b2a4db10` 内贸交付改动。本次未部署该新提交，其 `186_domestic_delivery` 与已部署186merge形成迁移分叉。下次集成须新增明确的汇合迁移，不重写任何已部署 revision。

## 实际验收

| 对象 | 读回证据 |
| --- | --- |
| 办公室 / 北京后端 | Git HEAD 均为 c797c45e；服务 running / active；真实 health 为 ok、database connected |
| 共享数据库 | 单一186merge；push_dingtalk为非空tinyint、默认1；NULL记录0 |
| 主站 / PM / 媒体 / 门户 | 已登记五个静态目标均完成；最终恢复预检核对当前artifact与完整候选manifest |
| 公网 | leshine.work、leshine.cloud健康200；两地主站、pm.leshine.work、shop.leshine.cloud首页200；两地主站首页SHA256与办公室候选文件相等 |
| 色卡 / WhatsApp / 物流 | 色卡真实health为ok；两地业务后端、WhatsApp运行；shipment-tracking-mcp为online |
| 出库调度 | 原身份、原五工件摘要；模式legacy；verified回执；原active/enabled均true的基线已恢复，真实timer active/enabled |
| 邮件 | 同候选部署与verify回执；保留原未运行、未启用状态，不启用发信 |
| 最终日志 | publish-current / publish-success成功；schema-writers completed；恢复phase completed |

静态资源保留策略：办公室、leshine.work、leshine.cloud均完成，最终succeeded；本次控制入口退出码0，临时任务已结束。回滚制品及事故/业务头像原件备份保留。

## 中断与接续

首次办公室新进程在权限初始化时超过原约30秒健康窗口，部署器保持writer停止，未回退旧代码。受管控制候选将固定现场恢复的健康等待限为300秒，办公室真实健康后继续北京；北京切换遇未跟踪头像阻挡，完成哈希验证及备份后，从已验收的办公室检查点接续。

两地应用和五站部署完成后，出库activate成功但verify无法确认模式控制。现场正向读回为failed_paused、timer暂停、service MainPID0、库锁无owner；仅数据库控制连接的ready/check/release实测成功，原legacy模式与数据库fingerprint保持一致。代码及独立复现揭示timer刚派发批次可占用同一GET_LOCK(0)，使核验连接未发ready便失败。

修复核验顺序为：确认原调度目标 → 暂停timer并最多180秒等待在途批次自然结束 → 同一数据库fence内复验模式/身份并恢复原目标调度 → 持久回执 → 确认释放。未杀在途提交、未补发测试业务、未改变baseline。固定最终检查点只接续出库及后台恢复，不重跑DDL、seed、应用或站点切换；三次恢复均保留独立事故归档。

本轮相关部署回归及checkpoint测试共161项通过；独立风险审查通过。全仓约定检查仍有17项既有发票表格UI问题，本次未改这些表格，git diff --check通过。Git巡检使用 --no-fetch，只代表本地快照；已记录并发186分叉，不自动处理无关分支。

本地运行证据：主目录 `.deploy_state/announcement-release-20261012/`，包括最终读回、公网SHA、预检和执行回执。服务器保留 `.deploy_state/release-latest-20261012/`、原迁移/恢复归档及头像备份。报告不包含凭据。公告真实群消息投递未在本轮测试发送。

业务候选c797c45e及恢复控制提交97250c02、34c0408e、4d386006保留在 `codex/latest-release-integration`。本次没有额外向origin推送这些生产集成/恢复提交；主目录其他未提交修改完整保留，只追加本次发布报告与交接记录。
