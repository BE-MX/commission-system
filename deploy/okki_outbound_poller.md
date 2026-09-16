# OKKI 出库单自动生成 — 轮询器部署说明（singapore）

> 发票首推小满成功 → 后端落 `ark_okki_outbound_tasks` 任务行 → 本轮询器在 singapore
> 执行 `create-outbound.js <order_id> --run` → OKKI 生成「待出库」销售出库单 →
> 既有 okki-sync 镜像作业回同步，发运检验模块可见。2026-09-16 引入。

## 链路

```
方舟后端 (office/beijing)                singapore                      OKKI
sync_invoice 首推成功                                             ┌──────────────┐
  └─ INSERT ark_okki_outbound_tasks ──► okki_outbound_poller.js ─►│ 销售出库单    │
        (pending)                       └ spawn create-outbound.js│ status=1 待出库│
                                        └ UPDATE 任务行 done/failed└──────────────┘
对账 job（30min）补漏 ◄── 窗口内首推成功但无任务行的发票                ▲
                                                            okki-sync 镜像回流
                                                            okki_outbound_records
```

- 队列表 `ark_okki_outbound_tasks.order_id` 唯一约束 + 脚本台账 `logs/created-outbound.jsonl` = 幂等双保险。
- 含未建品非标合并行（通用产品）的发票落 `skipped`，不自动生成，人工在 OKKI 处理。
- 编辑重推（update）不入队；数量变化的补出库（`--remaining`）本期不自动，人工执行。
- 后端总开关 `OKKI_OUTBOUND_AUTO_ENABLED=false`：停入队、停对账，免发版止血。

## 部署步骤（singapore 主机，一次）

```bash
cd /root/.openclaw/workspace/okki-sync
# 1) 放置轮询器（本仓库 deploy/okki_outbound_poller.js 原样拷贝）
cp /path/to/repo/deploy/okki_outbound_poller.js .

# 2) 依赖：mysql2（沿用 okki-sync 的 node_modules；缺则补装）
npm ls mysql2 || npm install mysql2

# 3) .env 追加方舟业务库连接（ark_invoices 所在 schema；最小权限账号：
#    只需 ark_okki_outbound_tasks 的 SELECT/UPDATE）
#    ARK_DB_HOST=...  ARK_DB_PORT=3306  ARK_DB_USER=...  ARK_DB_PASSWORD=...  ARK_DB_NAME=...

# 4) 安装定时器（本仓库 deploy/systemd/ 下两个文件）
cp /path/to/repo/deploy/systemd/ark-okki-outbound-poller.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ark-okki-outbound-poller.timer
```

## 验证

```bash
# 干跑一单（不动任务表）：手动执行脚本 dry-run 确认参数
node create-outbound.js <order_id>          # 不带 --run，安全

# 启用 timer 前，先手动跑一次轮询器验证 DB 连通与认领 SQL（任务表为空时应输出 no claimable tasks）
node okki_outbound_poller.js

# 端到端：造一张发票首推 → 看任务表出 pending 行 → 一分钟内 poller 消费
systemctl list-timers ark-okki-outbound-poller.timer
journalctl -u ark-okki-outbound-poller.service -n 50
mysql -e "SELECT id, order_id, status, attempts, last_error FROM ark_okki_outbound_tasks ORDER BY id DESC LIMIT 10"
# OKKI 侧应出现 status=1（待出库）的销售出库单；logs/created-outbound.jsonl 有记录
```

## 运维

- 失败重试：`failed` 且 `attempts < 5` 按 (attempts+1)×5 分钟退避自动重试；超限保持 failed 待人工。
- 卡死回收：`running` 超过单订单超时+5 分钟未回写视为认领进程已死，自动回收重试（attempts 未超限才回收）。
- 人工重置：`UPDATE ark_okki_outbound_tasks SET status='pending', attempts=0 WHERE id=N;`
- 人工补单：管理员「待核对 → 绑定已有 OKKI 订单」（resolve_uncertain_bind）的发票不自动入队，需要时手工执行 `node create-outbound.js <order_id> --run`（或向任务表手工插 pending 行）。
- 上线时点口径：启用瞬间，首推成功落在近 24h 窗口内的在途订单会被对账 job 补建出库任务——这是预期行为，验收时不要把它们当误补。
- 脚本报「已生成」类重复：台账幂等命中，视脚本退出码；若因此 failed，核对后用上面 SQL 重置。
- 回滚：`systemctl disable --now ark-okki-outbound-poller.timer`；后端置 `OKKI_OUTBOUND_AUTO_ENABLED=false` 重启。
- 时间口径：任务表时间为北京墙钟字符串，与 singapore 系统时区无关（脚本内已固定 UTC+8，SQL 不用 NOW()）。
