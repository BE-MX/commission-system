# 方舟预售主单推送小满：自动化与当前租户实测

日期：2026-09-28。范围只覆盖方舟创建预售主单、调用小满订单推送接口、小满接收并回读；不把分批出库、独立运费、回款外发或按钮开放计入本次验收。生产 `PRESALE_SETTLEMENT_ENABLED` 仍关闭，测试仅在隔离 SQLite 进程中解除本地建单门禁，未修改生产配置或共享数据库。

## 自动化回归

- `backend/tests/test_invoice_okki_push.py` 新增方舟 `create_invoice` 到 `xiaoman_service.sync_invoice` 的预售用例：携带定金资料和凭证，核对客户、币种、订单名、商品数量/单价、OKKI 类型字段、订单与行 ID 回写、同步状态，以及不生成整单自动出库任务。
- 同一预售样本覆盖小满明确拒绝、请求结果未知、响应缺订单 ID、响应缺商品行；未知结果禁止自动重发，已返回订单 ID 的缺行结果保留远端身份。
- 小满网络写入在普通测试中被 monkeypatch；`python -m pytest tests/test_presale_live_push.py tests/test_invoice_okki_push.py -q --disable-warnings --maxfail=1`：41 passed，1 skipped（真实探针默认跳过）。增量 `python scripts/check_conventions.py` 和 `git diff --check` 通过。

## 当前租户真实接口探针

使用 `backend/tests/test_presale_live_push.py` 的显式开关，在隔离 SQLite 方舟数据中创建预售单，由真实 `xiaoman_service.sync_invoice` 调用当前 OKKI 订单推送接口。专用客户、订单均带 `ARK-PRESALE-ARKPUSH-20260928-1830` 标识；只传一件 USD 0.01 的测试商品，凭证是隔离库内生成的测试图片，没有实际银行转账或实物出库。每次远端写入前有一次性意图文件，结果保存在该任务 worktree 的忽略目录 `tmp/presale-live-push-20260928-1830/`。

| 检查 | 结果 |
| --- | --- |
| 专用客户 | OKKI ID `105817287041109`，创建后按 ID 回读名称一致 |
| 方舟预售主单 | 由方舟服务创建、同步；OKKI 返回订单 ID `105817287159140`，方舟状态为 `synced` |
| 小满订单详情 | 按订单 ID 回读：客户、订单名、USD 币种、USD 0.01 总额、商品 ID/SKU/数量一致；远端商品行 ID `105817287162130` 与方舟回写一致 |
| 自动出库 | 方舟未设置整单自动出库请求；本次无出库单写入 |
| 清理 | 测试订单按精确 ID 删除，活动列表确认不存在；测试客户从公海删除，详情返回 404。清理后再次只读核验订单不活动、客户详情 404 |

命令在显式设置 `ARK_PRESALE_LIVE_PROBE=1`、`ARK_PRESALE_LIVE_ENV_FILE`、`ARK_PRESALE_LIVE_RECORD_DIR` 和唯一 `ARK_PRESALE_LIVE_MARKER` 后执行：`python -m pytest tests/test_presale_live_push.py -q -s --disable-warnings --maxfail=1`，结果 1 passed。普通测试不设置开关时自动跳过真实写入。凭据只从本机既有 `.env` 加载，未写入代码或回执。

若客户或订单 POST 结果未知，探针停止自动清理关联对象；需先用本次 marker 和已知客户 ID 在小满查回，再按精确 ID 清理，不能重发创建请求。本次写入均取得明确 ID，未进入该恢复分支。

结论：在此次测试商品、客户和 API 归属条件下，方舟创建的预售主单可被当前小满接口接收并按 ID 回读一致。本结果不证明分批出库和运费外发能力，也不改变预售入口的关闭状态。小满业务镜像异步同步，远端删除后的历史镜像残留另按只读镜像规则处理。
