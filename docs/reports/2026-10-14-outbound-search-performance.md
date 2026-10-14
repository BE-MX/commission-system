# 出库单打印页查询性能优化

## 问题与变更

用户在 `leshine.cloud/shipping/outbound` 查询「翟 #261023」时观察到接近 5 秒等待。本次在 `codex/outbound-search-performance` 隔离修改，没有发布或修改生产业务数据。

后端镜像归属过滤原先对每个出库单执行同客户订单的相关 `EXISTS`。MySQL 诊断计划显示外层扫描约 6,487 行，订单归属子查询为 dependent，按 company_id 重复探测。改为 `r.company_id IN (SELECT company_id FROM okki_orders WHERE user_id=:scope_okki_user_id)`，让数据库一次构造用户可见客户集合。方舟首推订单的精确订单、客户、成功创建记录及有效绑定规则不变，所有共享调用者继续使用同一过滤函数。

另一个重复开销是列表窗口计数遇到空行时，无论页码都重新执行一次合并队列 COUNT。现在第一页无结果即总数为 0；后续越界空页仍补查总数。

没有修改应用接口、前端搜索交互、模糊匹配、排序、打印规则、数量、库存或数据库结构。用户补充请求截图后，又针对实际转发链路增加了下文的列表、打印与 Word 候选路由。

## 截图后的链路定位与路由候选

截图中的请求是 `https://www.leshine.cloud/api/shipping-inspection/outbound-records?page=1&page_size=20&keyword=%E7%BF%9F+%23261023`，远程地址为本地 `127.0.0.1:7078`。该端口只读定位为 `MonoCloud_Mix.bin` 代理，地址本身不是方舟业务服务器；没有修改代理配置。

读取北京 live Nginx 配置后确认，整个 shipping 模块都被转到 `https://119.28.107.92`，由新加坡再经隧道访问办公室后端。因此当前真实路径是：浏览器（含本地代理）→ 北京 Nginx → 新加坡 HTTPS → 办公室后端。前述/下述北京处理函数测量**没有覆盖实际线上请求链路**。

使用相同 URL、不携带登录信息执行只读 HTTP 探针，全部立即返回预期 403，以隔离网络成本（不读取业务数据）：

| 探针位置与路径 | 三次耗时 | 返回 |
|---|---|---|
| 北京直接请求本机 8001 | 5.2 / 4.7 / 4.2ms | 403 |
| 北京请求办公室链路 `leshine.work` | 1809.2 / 2248.6 / 783.6ms | 403 |
| 当前电脑直连 `www.leshine.cloud` | 1398.8 / 1833.4 / 1300.1ms | 403 |
| 当前电脑经截图同端口代理访问 `www.leshine.cloud` | 3164.6 / 3271.4 / 2288.6ms | 403 |

这证明跨区域转发与代理已经占用数秒；结合带登录查询耗时，可以解释用户等待明显大于 SQL 耗时的原因，但未鉴权 403 **不能代替带登录 200 的完整 5 秒复现或上线验收**。Windows curl 经代理出现 TLS 失败后改用已有 httpx（保留证书校验）完成上表三次对比，没有关闭安全校验或反复重试不确定写操作。

已修改 `deploy/nginx/shipping-video-cloud.conf`：exact `/api/shipping-inspection/outbound-records` 列表，以及严格正则 `/api/shipping-inspection/outbound-records/[^/]+/(print-data|word)$`，指向北京本机 8001。这三个 URL 当前只有 GET 处理器，不读取本地媒体或扫码会话。列表仅查共享数据库；打印与 Word 另外读取小满、生成签名二维码，并保留原有共享数据库状态行锁和 token 懒刷新提交。Nginx 规则保留原 URI、query 和 Bearer，禁用缓存及失败重试；其余出库子路径（同步、删除、恢复）、station、上传与媒体仍用办公室。

两端独立只读配置检查确认数据库实例/schema 身份摘要一致、JWT key/algorithm 配置摘要一致，鉴权、列表路由与两份查询服务的规范化源文件摘要一致。没有输出凭据，亦未签发临时 token。这些是配置和源码读回，不冒充对运行进程全部环境或同账号 HTTP 的验证。

从 live 配置读取到的两处受管 shipping 块已在本地成功渲染候选，重复渲染幂等；候选和 diff 位于 `.deploy_state/outbound-search-performance/`。没有调用远端 prepare、修改 live 配置、reload Nginx 或发布应用。实际 `nginx -t` 由获授权后的受管 prepare 执行；上线还需同一登录身份核对目标搜索、空结果与权限排除，并确认真实请求和媒体路径。

**交付必须包含两个动作**：后端应用查询优化发布，以及经 `deploy.bat --shipping-video-routing-only` 的专项路由发布（先 `--prepare-only`）。普通应用发布不会自动改变专项路由。两者均尚未执行。

## 打印与 Word 配置及运行核验

用户进一步要求先核验二维码和小满调用配置，再把打印与 Word 也改到北京。新增只读探针保留在 `.deploy_state/outbound-search-performance/check_print_readiness.py`，结果为同目录 `print-cloud-readiness.json`、`print-office-readiness.json`。没有输出密钥、token、完整出库详情或二维码签名内容。

- 北京探针继承运行中 `ark-backend` 进程的环境；办公室探针读取 NSSM 注册的环境覆盖及后端 `.env`。两端相关源文件和配置均早于当前后端进程启动；北京使用带小数的启动时基核对，避免 `/proc/stat` 整秒截断造成同秒文件误判。
- 两端数据库实例/schema、JWT 配置、当前和旧版 `QR_SIGN_SECRET`、小满 API base/client id/client secret 及共享 token 摘要全部一致，打印相关源文件规范化摘要一致。两端为同一不存在的诊断记录生成的二维码挑战摘要相同，且各自验签成功，支持北京生成二维码由办公室同密钥扫码校验。
- 两端用现有共享 token 对「翟 #261023」的精确小满出库身份执行 GET `/v1/invoices/outbound/info`，均 HTTP 200，出库身份及负责人摘要一致（最新样本北京 854.1ms、办公室 903.5ms）。没有 OAuth POST、token 刷新、业务 POST 或数据库写入；这不冒充真实 token 换新验证。
- 两端实际运行 venv 均能在内存生成 Word、用 python-docx 读回并确认含 1 张二维码图片，确认 qrcode/python-docx 依赖可用。文档只使用合成诊断内容，没有落盘业务文档。

路由切换不改应用打印逻辑：`ensure_printable` 仍对共享状态行执行 `FOR UPDATE`；实时小满负责人查询仍可能惰性刷新共享 token 并提交，失败 rollback + 502。不能把打印与 Word 描述为严格无数据库写入；这套行为迁到北京后保持原语义。带登录的真实打印/Word HTTP 与办公室扫码验签仍需在获授权的部署后验收。

## 北京云端只读对比

诊断时远端生产 checkout 为 `4b8118741`，`ark-backend` 为 active。在该主机的独立 Python 进程中导入现有查询处理函数；候选函数仅在该诊断进程内临时替换，未写入服务器文件、未重启运行服务。数据库使用 `START TRANSACTION READ ONLY`，语句守卫仅允许读取/会话设置，单 SQL 最长 12 秒，结束 rollback。

同一事务快照中执行原实现与候选实现，每组各 3 次，比较列表路由处理函数的完整响应 JSON SHA256。归属用户由目标镜像客户对应的真实有效 OKKI 绑定解析，不签发 token、不修改账号权限。首次列内省在计时前完成。

| 场景 | 原实现中位耗时 | 候选中位耗时 | 原/候选 SQL 次数 | 结果 |
|---|---:|---:|---:|---|
| 管理员查询「翟 #261023」 | 125.1ms | 107.6ms | 16 / 16 | 1 行，总数 1 |
| 带归属权限查询「翟 #261023」 | 539.7ms | 134.1ms | 17 / 17 | 1 行，总数 1 |
| 带归属权限查询「261023」 | 550.4ms | 135.2ms | 17 / 17 | 1 行，总数 1 |
| 带归属权限查询不存在的单号 | 929.9ms | 42.2ms | 4 / 3 | 0 行，总数 0 |
| 带归属权限首次列表 | 707.8ms | 151.1ms | 14 / 14 | 20 行，总数 642 |
| 目标查询第 99 页 | 978.7ms | 107.4ms | 9 / 9 | 0 行，总数仍为 1 |

六组原/候选完整响应 SHA256 全部一致。目标带归属查询降约 75%，首次列表降约 79%。越界页原实现三次耗时为 978.7/6207.1/921.7ms，存在波动；不以该异常样本作为目标单号查询近 5 秒的复现证据。

本地恢复材料保留于本 worktree 的 `tmp/compare_outbound_search.py`（固定两段候选函数的只读诊断脚本）和 `tmp/outbound-cloud-comparison.jsonl`（计时、查询次数及响应摘要）。未保存完整客户业务响应。

这些数字不包含 HTTP 鉴权中间件、浏览器网络往返或渲染，不能解释为用户页面已降至 134ms。当前电脑经默认代理访问该域名出现 TLS 失败，禁用代理的只读 `/health` 请求为 200、约 186ms；无已登录浏览器会话，因此没有完整复现用户页面近 5 秒的端到端等待。

## 回归与审查

- `python -m pytest tests/test_shipping_search_performance.py tests/test_shipping_outbound_queue.py tests/test_shipping_local_order_scope.py tests/test_shipping_inspection_scope.py tests/test_shipping_outbound_status_filters.py tests/test_shipping_table_sorting.py tests/test_shipping_record_filters.py tests/test_outbound_collation.py -q`：**105 passed**，全部使用内存 SQLite。
- 新增性能测试用 500 张出库记录与同客户 500 张订单验证归属过滤的工作量，按 SQLite VM 步数计量，避免机器速度影响。进程内恢复原函数时测试失败，记录 1,255,000 步；候选要求少于 50,000 步并通过，且可见记录一致。
- 新增首页空结果测试在原实现失败；既有越界页测试和云端第 99 页对比证明真实总数保持正确。
- 独立 agent 检查 NULL、客户 ID、跨库比较、首推订单权限及共享调用者，无阻断问题；补充验证 130 passed（与上述集合部分重叠，不合并计数）。
- `python scripts/check_conventions.py --strict` 与 `git diff --check` 通过。
- 新增路由边界回归在原模板失败；最新候选 `python -m pytest deploy/tests/test_voucher_routing.py -q` **43 passed**，独立 agent 复审通过。覆盖带 query 的列表/打印/Word、原 URI/Bearer、禁缓存/重试、真实同步/删除恢复及媒体子路径归属、受管块替换/幂等/回滚，以及三个 URL 当前只有 GET 处理器。
- `python -m pytest tests/test_shipping_print_owner.py tests/test_shipping_print_spec.py tests/test_shipping_print_order.py tests/test_shipping_customer_grade.py tests/test_shipping_selective_recheck.py tests/test_outbound_invoice_sync.py -q`：**170 passed**。初跑为 168 passed、2 failed，两个既有打印测试替身缺少 `outbound_record_id` 和 `sync_event` 关键字支持；只补齐真实契约，原负责人/HTML/Word 断言保留后全部通过。独立 agent 另验证负责人测试 11 passed。
- `python scripts/git_sweep.py --no-fetch` 完成，检查为本地快照；仓库其他 worktree/历史 stash 未清理或改动。

后端验证复用主目录的 `backend/.venv/Scripts/python.exe`。本次没有前端变更，无需前端构建。用户已授权本次提交、合并 main 并推送 origin；最终 Git 交付结果以 origin/main 回读为准。本次不部署，后端应用与专项路由仍需另行发布。
