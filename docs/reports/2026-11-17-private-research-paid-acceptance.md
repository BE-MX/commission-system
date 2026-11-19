# 2026-11-17 北京私海背调 V2 付费验收

## 生产配置

北京 `ark-backend` 的研究工具 Worker、Maigret、Monid 已启用。后端重启后健康检查返回 `ok`，数据库已连接，OpenClaw、Maigret 扫描器与研究工具出口均为 `active`。OpenClaw 自动领单的 heartbeat 维持 `0m`。配置操作以北京当时在跑的 `d268716a` 和数据库迁移 `270_dom_fu_guided` 为基线，回滚备份位于 `/var/backups/ark-private-research-tools-20261117/backend.env.before`。

## 弱线索路径与账单

定向创建并手动领取 Brianna Barcomb（客户 `#1804`）的 `private-research-v2` 任务 `#404`，冻结路线为 `weak`。Run `#421` 通过行业门控，免费查询后仍无法直接读取 Instagram 主页。

| 调用 | 生产回执 | 实际费用 |
| --- | --- | ---: |
| Maigret `#2` | 检查 88 站，2 站连接失败（2.27%），1 条账号候选 | USD 0.000000 |
| Monid `#3` | `instagram_profile`，关联扫描 `#2`，HTTP 200，返回 1 条主页候选 | USD 0.000810 |

Monid 供应商 Run `01M7KTFDB0K59H8511MVA3E4VH` 返回 `COMPLETED`。钱包从 USD 10.735600 变为 USD 10.734790，余额差、供应商回执、方舟调用明细与客户费用汇总均为 USD 0.000810。Monid 调用数为 1，预留结算后归零。该金额仅计供应商调用。

## 同 Run 证据绑定

Maigret 候选绑定成功。两次 Monid 证据绑定均返回 HTTP 400。候选资料的 `biography` 自带换行，写入同 Run 事实时触发 `ASCII_CONTROL_CHARACTER_INVALID`，已结算的付费回执没有生成事实引用。Run `#421` 随后到达 OpenClaw CLI 的 600 秒执行上限，未提交完整报告。候选账号与当前职业身份仍需核验。

原租约自然到期后，北京 OpenClaw 重领同一任务。Run `#422` 于北京时间 12:14:36 提交了 `private_research_v2` 报告，CLI 退出码 0。公开来源在该 Run 中仍无法读取，报告记录 10 项资料缺口和 0 条已核实引用。用原客户负责人权限从背调中心和私海助理回读同一份 3,433 字符报告，复核状态为 `pending`。恢复轮的 Maigret 和 Monid 调用均为零，任务总费用仍为 USD 0.000810。

本地修复在独立工作树 `D:/MyProgram/commission-system-codex-monid-multiline-candidate` 的 `codex/monid-multiline-candidate` 分支。写入事实时将 Monid 指定简介字段里的排版空白换成空格，原始回执、标识、URL 和账单保留。回归覆盖已结算回执绑定、重复绑定幂等、拦截非法控制字符和无二次供应商请求。后端 V2 定向测试 28 项通过，增量规范检查通过。补丁尚未发布。

旧回执绑定受原 Run 和原租约约束，换 Run 后需要以新的受控调用验收付费证据入报告。运维和账务回执位于 `.deploy_state/private-research-paid-20261117/`。
