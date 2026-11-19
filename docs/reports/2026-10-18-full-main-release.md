# 2026-10-18 最新 main 全量部署

已通过受管入口 `deploy/deploy.bat` 完成办公室与云端全量部署，固定版本 `993d5a138646ab8ac971a321af80c6438d8d3158`。办公室回执记录北京时间 **00:11:01—00:14:46**，部署器耗时 **224.768 秒（约 3 分 45 秒）**。计时不含脚本传递、候选创建及人工等待。

## 验证结果

- 用户回传的办公室 JSON：publish/timing 均 succeeded，11 项发布目标完成，所有计时步骤成功；任务 Ready、退出码及 LastTaskResult 均 0，发布锁释放。
- 办公室 HEAD 为目标版本，工作区干净；CommissionSystem、WhatsAppConnector、ArkOfficeHttps 均运行，health 为 ok、数据库 connected，主站和 PM 本地入口均 200。
- schema 保持 `196_domestic_commission`，本次没有新增迁移。D 盘剩余 120.47 GiB。
- 独立云端 SSH 检查：北京后端 active、数据库连接正常，准备回执指向目标版本；backend/config 内容无差异，因此按既有机制保留运行 HEAD `1eef7a2e7472588553ed8f7fb011105b9a7b3d32`，changed=false。
- 独立验证 leshine.work、leshine.cloud、pm.leshine.work、shop.leshine.cloud 均为 HTTP 200；PM 的 Python TLS 探测出现 EOF，Windows curl 再核验为 200。两地主站制品一致。这些结果确认技术发布和访问状态，不代替业务流程验收。
- 办公室最终状态来自用户控制台回执；办公室 SSH 仍握手超时，没有宣称已通过 SSH 独立读回。

## 耗时与清理

较上次 254.624 秒，本次少用 29.86 秒（11.7%）。本次仅变化 Git 门禁、脚本测试和文档，前端制品未变化；这不是同负载性能基准，也没有验证新 npm 缓存的线上收益。

主要阶段：北京准备 53.67 秒、激活 20.04 秒；静态资源保留 38.09 秒；办公室准备 19.52 秒；云静态准备父阶段 16.48 秒。并行子阶段不与父阶段重复相加。

候选清理成功，删除 0 项、保留 3 个受管候选。单次计划任务 `ArkFullMain20261018` 已 Ready/0，没有循环触发器；因 SSH 不通暂留远端任务及回执用于恢复核验。没有重复部署。

## 本地交付

已 fetch 并固定远端 main，本地 main 与 origin/main 为目标版本；本次无需合并或推送。Git 门禁测试在 PYTHONUTF8=1 下 18 项通过；保留其他代理的未提交工作。发布记录和 handoff 保留为本地未提交文档。

证据目录：`.deploy_state/full-main-release-20261018/`，包含 `office-readback-user.json`、`live-checks.json`、`curl-readback.json`、`comparison.json`、`delivery.json` 与启动/读取脚本。
