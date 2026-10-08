# 按变更明细补验发布与核验

2026-10-08，按亮哥「部署」授权发布本轮出库补验修复。主应用固定候选 `c41307e0b63e22602baef293e588b042fcba9bd5`，没有将随后合并的内贸决策台迁移及其他功能带入本轮发布。

## 发布证据

- 办公室通过 `deploy/deploy.bat --revision <candidate> --no-pull` 完成 prepare-only 和正式发布，两次退出0。release_id=`da3968c8611742418006534e0ec6e2e0`，scope=`office-and-cloud`，status=`succeeded`，deferred=[]。
- 办公室、北京实际 HEAD 均为候选，health=ok/database=connected。数据库保持 `173_task_center`，无DDL；出库轮询timer恢复active/enabled，邮件Worker保持inactive/disabled/MainPID0。
- 主站两域、PM域15项公网入口及相关JS摘要与候选构建一致，包含出库页面和共用验货手机代码。开发机Python公网验证最初遇到TLS EOF，改用直接连接且保留证书验证的curl完成核验。
- 北京镜像另通过同一入口的 `--okki-sync-only`，按实际旧摘要准备后激活。三文件组合制品SHA-256=`257937668134ac6f725dcefd630394d7c8575f393efe21384d28762e14c6cf3e`，journal=verified，实际运行文件摘要全部匹配；既有每分钟cron及锁配置保持原值，激活后的下一轮完成且失败0。
- 合并前305项后端、137项前端/同步/出库测试与前端构建通过，独立补验契约和镜像路径审查通过。本次上线后验证使用实际安装源码，并在只读事务中回读业务资料。

## 翟 #261006 实际扫码结果

办公室与北京均回读镜像 `93127` / 检验 `447`：仍为draft、edit_version=2，共12张照片。审计 `5774` 证明仅 `#P2/8` 从24寸改22寸。

- #1B、Cookies Cream、#5ATP5A/1006 的六张旧照片 `[4059,4061,4071,4073,4078,4079]` 恢复有效。
- 仅旧整单及旧P2照片 `[4057,4081,4082]` 失效。当前要求为整单与本地明细 `341639`，已补传整单 `4149`、P2 `4152,4153` 完整覆盖，outbound_sync_pending=false。
- `Other Items` 的 `requires_recheck_photo=false`，不要求为费用项补拍。验货资料已经齐备；用户刷新后仍需执行提交验货，提交成功才解除待补验并保存恢复审计。本次核验未替用户提交或改写历史业务证据。

原始发布日志、基线、固定镜像计划、两地扫码证明及公网摘要保存在主工作目录 `.deploy_state/shipping-selective-recheck-release/`；集成回归与无关工作保护证据在 `.deploy_state/shipping-selective-recheck-integration/round2/`。不提交业务照片、凭据或完整业务行。
