# 出库镜像专项更新

源码在 `services/okki-sync/`。初始版本取自北京实际运行文件，不复制 `auth.js`、`db.js`、`.env`、凭据或业务文件。既有每分钟 cron 保留，主应用不参与这次专项更新。

`deploy/platforms.json` 登记 `ark-okki-outbound-mirror`。运行目录是 `/root/.openclaw/workspace/okki-sync`，准备与备份目录仅限其 `.deploy-state/ark-sync/<artifact SHA>/`。`okki-index` 不调度出库；现有 `daily-sync.sh` 不调用出库。旧的 `resync-outbound-by-order.js` 引用未导出的函数，不能将其当作已验证的手动修复入口。

## 固定候选与准备

计划文件只包含 `expected_live` 和 `candidate`，两者键固定为 `inspection-contract.mjs`、`outbound-store.mjs`、`sync-outbound.js`。值为 SHA-256；线上尚不存在的 helper 在 `expected_live` 中为 `null`。计划放本工作树 `.deploy_state/`，必须根据实际核验的线上摘要和本地候选生成，不能用旧摘要绕过漂移检查。

```powershell
deploy\deploy.bat --okki-sync-only .deploy_state\okki-sync-plan.json --prepare-only
```

准备检查线上基线、制品摘要及 Node 语法，只写受限准备目录。两个阶段均使用独立远端发布锁，正式激活另取既有 `/tmp/okki-outbound.lock`，等待 cron 排空并拒绝仍在运行的手动出库同步。各级目录及文件拒绝符号链接。候选或线上原版变化须重新核验和准备。

## 正式激活

用户明确授权此生产变更后，使用同一个计划执行：

```powershell
deploy\deploy.bat --okki-sync-only .deploy_state\okki-sync-plan.json
```

不能混用主应用发布参数。保留旧文件受限备份，helpers 先替换、入口最后替换；只有运行文件摘要全部匹配才记 `verified`。替换失败恢复已改文件并移除本轮新增 helper；journal 为 `activating` 时必须先核验，不自动重试。发布完成后重复执行核验实际运行摘要，不重写已验证状态。

后检需核对实际入口/helper 摘要、下一轮 cron 结果、关键单据明细 ID 和照片分组。手动命令也必须遵守既有出库锁，不能在专项激活期间另外启动。

## 同步合同

- 按单据内 `outbound_record_id` 更新明细，保留本地 `id`；只插入新增项、删除确实消失的项。
- 列表和完整详情必须属于同一单据与同一版本；详情失败不推进镜像表头。旧版本不能覆盖新版本。
- 表头、明细、照片身份收敛、补验状态与审计在同一 MySQL 事务内。使用既有 event → inspection 锁顺序；跨库表须全为 InnoDB。
- 照片从人工核验远端身份收敛至本地身份；verified 保留远端身份，让主应用按原始镜像匹配后清除 overlay（主应用须包含 b245f534），保留业务快照、补验状态与打印授权；真实产品/数量变更则保留照片历史，撤回已提交检验并要求新证据。
- 不修复无法证明对应关系的历史照片，不改原上传审计，不把机器同步冒充人工操作。

验证命令：`node --test services/okki-sync/outbound-store.test.mjs`；`python -m pytest deploy/tests/test_okki_sync_release.py`。部署测试只用临时目录和模拟进程。生产 SQL 只读规划不能证明实际并发锁行为，正式激活后仍需运行验证。
