# OKKI 出库单轮询器（新加坡）

发票首推成功 → `ark_okki_outbound_tasks` → `okki_outbound_poller.js` →
受管 `okki_outbound_creator.mjs` → OKKI 待出库单（status=1，不扣库存）。出库单号 serial_id 默认取对应方舟发票 invoice_no，缺少发票号则阻止创建。提交前按 serial_id 全局实时查重（不受订单创建日期窗口限制）；其他订单已占用时改用 `invoice_no [order_id]` 并再次查重，两者均被占用则阻止提交。只有该精确查询返回 `HTTP 200 / code 404 / Not Found Resource` 才证明单号空闲，其他错误不得当成不存在。
出库备注 `remark` 取同一任务关联方舟发票的 `remark`，保留换行与空格，空值写空串；不取 OKKI 订单备注。创建后回读备注，不一致进入 `uncertain` 待人工核对，不重复提交。已有单据仍跳过，不自动补填或覆盖备注。
原独立 `create-outbound.js` 保留，轮询器不再调用它。

## 部署

普通 `deploy.bat`（含 `--cloud-only`）已纳入本服务：从同一候选 revision 准备脚本，应用切换前暂停并排空，在应用/schema就绪后替换并校验，恢复原启用/运行状态，最后将出库版本校验计入整体发布成功判据。`--prepare-only` 不暂停服务。完整顺序和失败恢复见 [统一发布说明](README.md#okki-出库轮询器专项)。

单独维修入口仍保留；以下命令只更新本服务，不发布其他应用或执行数据库迁移，激活时显式启用调度：

```powershell
deploy\deploy.bat --okki-outbound-only --prepare-only
deploy\deploy.bat --okki-outbound-only
```

目标 `/root/.openclaw/workspace/okki-sync`；Node 使用已核验的
`/root/.nvm/versions/node/v22.22.1/bin/node`。运行依赖沿用该目录 mysql2、auth.js、
OKKI 配置。方舟数据库参数单独存远端 `.ark-outbound.env`（root:root / 600），
包含 ARK_DB_HOST/PORT/USER/PASSWORD/NAME、ARK_BUSINESS_DB_NAME、OUTBOUND_SCRIPT_DIR。
应用账户需要任务表 SELECT/UPDATE 及业务出库明细 SELECT；不授予镜像写权限。
不得把凭据文件纳入代码制品或日志。

预检校验 SHA-256、Node 语法、systemd 配置、数据库 SELECT 与 EXPLAIN UPDATE 权限；
制品在目标 `.deploy-state/ark-outbound/<digest>`，旧文件备份保留在该目录 backup。
启用前停 timer 并检查 service 空闲，避免运行途中换代码；timer 每分钟触发，
同一 MySQL named lock 限制一个受管轮询器，逐笔认领，回写校验 attempts 版本。
启用后的真实单据结果须再查任务表与 OKKI，不以 timer active 代替业务验证。

## 已有单与防重

1. 用镜像查关联出库 ID，再实时读取 OKKI 详情核对 order_id。
2. 未命中时，按销售订单 create_time 当天零点起查询全部出库更新时间列表，逐页、逐单核对详情关联。
   不只检查“已出库数量”：实测人工待出库单存在时，订单的 to_outbound_count 与 task_outbound_count 仍可能是 0。
3. 任一关联出库单存在即 `skipped`，包括人工创建、待出库、已出库和部分出库；不自动补差额。
4. 提交前用独占文件持久化 `logs/ark-outbound-intents/<order_id>.json`；成功后核验关联并记
   `logs/created-outbound.jsonl`。已有意图却查不到实时关联时，不自动再次提交。
5. 明确的 `HTTP=200 / code=404 / Operation Failed. 序号为[N]可用库存数量不足` 拒绝进入 `waiting_stock`，每15分钟复查，不受5次上限限制。其余业务错误仍按结果不确定处理。
6. 查询失败不创建。提交超时、响应丢失、结果缺字段、验证失败、子进程被杀进入 `uncertain`，不自动重试。
   明确的提交前错误进入 `failed`，最多尝试5次，按 (attempts+1)×5分钟退避。

官方列表接口不支持 order_id 筛选；count 是总数、start_index 是页码、time_type=1 是更新时间：
[OKKI 销售出库单列表](https://open.xiaoman.cn/api-3484729)。

限制：OKKI 未提供此流程可用的跨客户端原子幂等键，人工或旧脚本在查询与提交的短窗口同时建单，
仍可能形成外部竞态。受管轮询器的锁与意图文件只约束本服务。
长时间积压使扫描超过120秒时也可能进入 uncertain，即使尚未提交；应核对后处理，不能盲目重置。

## 运维

```bash
systemctl list-timers ark-okki-outbound-poller.timer
journalctl -u ark-okki-outbound-poller.service -n 80 --no-pager
```

任务表 `reason` 记录 created/existing 与单号，`last_error` 记录错误。
`skipped` 也包括后端识别的未建品非标合并行；此类不进入执行器。
`uncertain` 要先读 OKKI 实际关联和提交意图，确认后人工完成状态处理；不得直接删除意图或 force 重发。
暂停自动执行使用 `systemctl stop ark-okki-outbound-poller.timer`；需要跨重启暂停用 disable --now。
不要停止执行中的 service，以免制造不确定提交。后端总开关只控制入队与对账，不会暂停已经入队的任务。

验证：`node --test deploy/tests/test_okki_outbound.mjs`，覆盖人工/部分已有单、查询失败、
响应丢失、意图防重、真实结果验证、分页、并发认领和旧 worker 回写。

## 等待库存恢复

等待任务每15分钟认领一次，按最久未处理优先，不限制等待次数。每轮先实时核对已有出库单，再按 SKU 合并需求量，查询 `/v1/product/inventory-list`，只使用目标仓库 `8193514242746` 的启用库存 `enable_count`。其他仓库库存、实物库存 `real_count` 和订单详情库存字段不作替代；列表不完整、字段异常或查询失败时不提交。库存足够才提交整单，若检查后库存又被占用，明确的库存拒绝会重新等待。

提交意图不删除：明确拒绝时持久记录 `stock_rejected` 与错误，下一次真正提交使用 `.retry-N` 独占意图文件，保留每次拒绝证据。响应丢失或超时仍为 `uncertain`，不得凭库存补足自动解锁。等待期间人工已建单则 `skipped`，不补差额。已有 `uncertain` 历史任务不自动转等待，因为旧日志可能缺少明确拒绝证据。

历史明确库存拒绝任务恢复：在同一轮询锁下重新核对无关联出库单，读取远端人工恢复审计中的明确拒绝证据；把对应最后一次意图标为 `stock_rejected`，把任务改为 `waiting_stock`。保留原始文件备份和恢复审计，生产状态转换须有授权，不能仅按 `code=404` 批量解锁。

## 数据库迁移保护

此服务是 commission_db 任务表 writer，已登记在 platforms.json 的迁移 writer 清单。
迁移控制器支持停止 timer 并排空在途 oneshot，不强杀提交中的服务。普通应用发布还会先保存
本服务原始调度状态并冻结，待应用与出库脚本共同就绪后恢复；数据库迁移模块看到的已暂停
状态不能覆盖发布模块保存的原基线。writer 清单仍须现场核实，不能因代码已支持而跳过核对。

## 2026-09-20 重名单号混单修复

实证：`outbound/push` 即使不传 outbound_invoice_id，同 serial_id 仍可能编辑旧单并追加明细。
创建前的订单关联检查不能代替全局单号检查。已有关联混入其他订单时进入 uncertain，不能当 existing 成功跳过。
创建后按出库 ID、单号、客户、待出库状态以及全部明细的订单/订单行/产品/SKU/数量/单价逐项回读；任何额外行、缺行或差异进入 uncertain，不写成功 ledger，不自动重复提交。
外部人工在查重与提交之间并发使用同一单号仍存在竞态；回读负责发现并隔离，不能声称上游提供了原子新建保护。
验证：`node --test deploy/tests/test_okki_outbound.mjs deploy/tests/test_okki_outbound_isolation.mjs`。

提交意图保存实际 payload；异常恢复发现已有关联单时，有本服务意图的单据须按最后一次提交快照重新核验，错误数量等不能在重试时绕过检查。旧意图缺快照时按当前订单保守核验，人工部分单无意图则继续防重跳过。

## 订单生命周期冻结（161）

poller 仅认领关联发票 sync_status=synced 且 status 不为 cancel_pending/cancelled、没有 linked_sync_id 的任务。后端漏建对账改按 outbound_auto_requested 登记，移除 OKKI_OUTBOUND_RECONCILE_WINDOW_HOURS；不再受24小时窗口限制，也不追建未登记历史订单。普通完整发布现在自动协调暂停poller、迁移161及应用更新、出库脚本更新与恢复，不再要求另跑专项发布；outbound-only 入口不能代替数据库迁移及后端发布。
