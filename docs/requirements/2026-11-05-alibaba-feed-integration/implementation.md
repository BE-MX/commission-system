# 阿里 Feed P1 接收层实现与验收

2026-11-05。本地工作区 `D:/MyProgram/commission-system-codex-alibaba-feed-p1`，分支 `codex/alibaba-feed-p1`，实现基点 `6cacc6fa`。实现验收后亮哥明确授权本批提交、整合最新 main 并推送 origin/main；Git 交付不包含部署、生产迁移或凭据发放。私海助理及 feed 开关继续默认关闭，未连接生产数据库。设计全文中的 P2、v1.1、人工关联、员工映射和业务查询不属于本次接收层交付。

## 已实现范围

当前 `ark_alibaba_feed_v1` JSON 可原样作为 HTTP 正文上传。原始解压字节、语义 hash、批次与队列身份在同一事务提交，成功后返回 202。后台仅在本地校验、保存快照和选择当前版本，不调用旧 Alibaba 客户投影、客户建档、私海分析、模型或消息发送。

原始包保存在私有写库的 `MEDIUMBLOB`，与批次一起备份恢复，不落公开上传目录、不提供原文下载接口。原始字节 hash 与语义 hash 分开记录；对象键排序、空白和 Unicode 转义形式变化不产生新任务，数组顺序保留。本阶段没有自动删除历史快照的任务，保留期和撤销后的资料清理需在后续上线运维方案中确定。

来源由管理员把一个 feed 专用 Integration App 绑定到不可改的 `source_account_uid`，调用方不能通过正文选择来源。feed scope 与 `invoice:write` 互斥，原发票 App 创建默认值保留。来源默认为禁用且未授权，P1 管理接口不能打开 CRM、AI 外发或私海接入。

## 接口和配置

接口均使用 `{code,message,data}` 信封、`Cache-Control: no-store`，响应带服务端生成的 `X-Request-ID`。

| 方法与路径 | 权限及结果 |
| --- | --- |
| `POST /api/alibaba-feed/v1/batches` | feed token 的 `alibaba_feed:write`；JSON 原文正文；必需 `Idempotency-Key=run.run_id`；首次耐久接收 202，相同内容重放 200 且 `replayed=true` |
| `GET /api/alibaba-feed/v1/runs/{run_id}` | 同来源 feed token 的 `alibaba_feed:read`，用于发送结果未知时查询 |
| `GET /api/alibaba-feed/v1/batches/{batch_id}` | 同来源 feed token 的 `alibaba_feed:read`，使用 POST 返回的 `status_url` |
| `POST /api/alibaba-feed/sources` | 用户 JWT，实时 `alibaba_feed:admin` 或 super_admin，新建来源绑定 |
| `PATCH /api/alibaba-feed/sources/{source_uid}` | 同上，必需 `expected_version`，版本冲突 409 |

GET 支持 `issue_offset>=0`、`issue_limit=1..100`，响应字段为 `issues_offset/issues_limit/issues_total`。机器凭据不能管理来源，发票凭据不能上传或查回执。跨来源查询与不存在对象同样返回 404，不泄漏其他来源的存在性。

来源创建字段：`source_account_uid`、`integration_app_id`、`name`，可选 `ingest_enabled=false`、`consent_state=pending`。PATCH 仅接受 `expected_version`、`name`、`ingest_enabled`、`consent_state`，不能换绑 App 或改来源 ID。撤销或待授权自动关闭接收；授权状态变更递增 `consent_version`，任意成功修改递增 `version`。启用时复核 App 与拥有者当前权限。

错误只含静态代码、字段路径和请求 ID，不回显未知字段名、字段值、消息正文或 SQL 参数。来源管理也使用安全错误信封。

`ALIBABA_FEED_ENABLED=false`、`ALIBABA_FEED_WORKER_ENABLED=false` 默认关闭，与 `CLIENT_DESK_ENABLED=false` 独立。两个 feed 开关都打开且既有单活 scheduler 启用时，才每 15 秒执行一次 `alibaba_feed_worker`，每轮最多处理 10 批。只开接收不开 worker 时保留 queued，排队满后返回 429。

| 配置 | 默认 |
| --- | --- |
| `ALIBABA_FEED_MAX_BODY_BYTES` | 10 MiB |
| `ALIBABA_FEED_MAX_COMPRESSED_BYTES` | 2 MiB |
| `ALIBABA_FEED_MAX_RATIO` | 100 |
| `ALIBABA_FEED_MAX_RECORDS` | 1,000 |
| `ALIBABA_FEED_MAX_MESSAGES` | 50,000 |
| `ALIBABA_FEED_MAX_MESSAGES_PER_RECORD` | 5,000 |
| `ALIBABA_FEED_MAX_MESSAGE_BYTES` | 65,536，固化于批次供恢复使用 |
| `ALIBABA_FEED_SOURCE_PENDING_LIMIT` | 2 |
| `ALIBABA_FEED_SOURCE_REQUESTS_PER_MINUTE` | 10 个新耐久批次 |
| `ALIBABA_FEED_LEASE_SECONDS` | 120 |

仅接受 `application/json`、UTF-8 和可选单 gzip 成员。流读取限制压缩/解压大小，完整流验证压缩比、校验和及结束标记，拒绝 gzip 拼接、尾随字节和不完整上传。

## 幂等、版本与恢复

- 唯一键 `(source_account_uid,run_id)`。同键不同语义内容返回 409 `IDEMPOTENCY_PAYLOAD_MISMATCH`，换窗口也属于内容变化；token 轮换不改变来源命名空间。
- 来源锁串行查重、配额核算和插入。同包重放优先返回回执，不占新处理名额。MySQL 使用 `utf8mb4_0900_bin` 精确 ID 比较，保留大小写和尾部空格差异；因此需要 MySQL 8，worker 的 SKIP LOCKED 同样要求该版本能力。
- 预检后释放事务再读上传正文，接收事务重新锁验原凭据、App、员工有效性、实时角色权限、来源授权和采集代次。慢上传期间撤销或轮换的旧凭据不能继续写入。
- worker 用 `FOR UPDATE SKIP LOCKED` 领取 queued 或过期 running 批次。逐条事务先锁 batch、验证 token/租约，再锁 source；拿锁后及提交前复核时钟，过期 worker 的 item/current/计数全部回滚。
- 每条记录独立提交，恢复跳过同批次已提交索引，保留 batch_id。前两次内部异常等原租约过期后恢复，第三次在有效租约内标 `processing_failed`，仅保存安全错误码。不自动对外重投。
- 同近似观察时刻出现异体时隔离该版本、撤下当前指针，尽可能恢复更早完整无冲突版本。之后旧回执和同包重放会反映冲突，原 `completed` 可展示为 `completed_with_issues`；outcomes 是当时处理动作，不能当作实时当前版本清单。

v1 以 `reply_status_snapshot_at` 为近似观察版本。旧包晚到只留历史；同窗新 run 新建批次，不删除未出现记录。partial 或详情不完整不清空旧完整正文。`failed` 空包形成 `recorded_source_failure`，不能解释为没有商机。

同观察时刻的完整/不完整快照双向到达均优先保留合格完整版本。不完整、重复键、窗外等无效快照不参与完整版本冲突仲裁或最新版本屏障，不能污染完整当前指针；两个完整合格快照的同版本异体才隔离冲突。

迁移 `251_alibaba_feed` 接 `250_client_desk`，新增三张接收表，冻结结构独立于运行模型。MySQL DDL 中断后，只在已有列、类型、空值性、默认值、PK/unique/FK、排序规则与索引通过核验后续建；不符则明确阻断，不 stamp 或猜修。DATETIME(6) 保留近似观察版本微秒。

## 质量和回执

整包 schema、枚举、身份或结构错误拒收；严格 UTF-8、重复 JSON 键、浮点数、NaN/Infinity、深度>32、单独 Unicode 代理项均拒绝。单记录日期/消息时间错误、窗外、重复业务键或消息 ref、正文超限进入隔离，其余有效记录继续；不截正文。日期精度按一天区间判断，不能写成精确午夜。

回执只返回身份、状态、服务器计数、质量和错误位置，不返回客户名、负责人名、原消息或外部错误原文。`owner_unmapped` 表示本阶段没有身份映射；`private_linked/ai_eligible/rule_eligible` 始终为 0。缺稳定买家/消息 ID，故 `buyer_count_verifiable=false`、`message_identity_stable=false`。

`processed_records` 为已耐久完成的 item 数，`unprocessed_records=received_records-processed_records`。正常完成或采集空失败时四种 outcomes 合计等于 received_records；处理中及部分进度的 processing_failed 只合计已处理项，不能把未处理算成功或隔离。`provisional` 表示排队/执行中；processing_failed 虽为终态，仍须检查未处理数。

状态：queued → running → completed / completed_with_issues / recorded_source_failure / processing_failed。202 仅代表耐久接收，查询终态后才能报告处理结果。超时先按原 run_id 查询；404 仅表示查询当时尚无耐久回执，原 POST 仍可能在途。

## 后续对接顺序

生产发布、迁移和开关放行仍需本次具体授权，由既有部署入口执行；私海助理保持关闭。为指定有效员工分配 feed 读写权限，经 `integration:admin` 创建只含 feed scope 的 App，由 `alibaba_feed:admin` 绑定并确认来源授权，再配置 feed 接收与 worker。开发测试不能用生产 token。

App 创建沿用 POST `/api/integration/apps`，请求示例：

```json
{"name":"Accio feed","owner_user_id":123,"scopes":["alibaba_feed:read","alibaba_feed:write"]}
```

来源创建示例：

```json
{"source_account_uid":"ali-shop-example","integration_app_id":456,"name":"Accio shop"}
```

保管一次性返回的 token，再 PATCH 来源 `{"expected_version":1,"consent_state":"authorized","ingest_enabled":true}`。上传以原文件为正文，不加 payload 包装；查询返回的 status_url，429 按 Retry-After 退避。

## 验证证据

使用隔离 SQLite 与独立回环 MySQL 8.4.13，不使用工作区 `.env`。HTTP/JSON/gzip 边界、跨来源隔离、来源管理、幂等、版本、时区、租约与恢复有回归，共享发票 Integration App 行为一并验证。

MySQL 实际执行新增迁移，生产一致 `autoflush=False`：6 个同键并发请求仅 1 批次；大小写 run_id 分开归档；5 个新 key 并发接收 2 个，其余 3 个 429。

当前真实附件仅在隔离 MySQL 经过 HTTP 鉴权、上传、worker、GET 和重放：49 记录、1,520 消息，49 条保存为当前快照，30 条日期精度不确定、0 条窗外，终态 completed_with_issues，私海和 AI 资格均 0。原附件未作为 Git fixture 提交。

独立审查已修复生产 autoflush=False 的冲突恢复、极端日期单项隔离、等锁/flush 跨租约到期，以及旧回执新增冲突的展示一致性。最终复审无阻断。

### 最终收尾结果

- `pytest tests/test_alibaba_feed_{core,auth,http,migration}.py -q`（实际按四个文件显式列参）：65 passed。涵盖正式路由注册、scheduler 开关独立性，以及完整/不完整快照双向到达。
- 扩大到 `test_integration_admin/api/models/native.py` 和 `test_client_desk_routing.py`：185 passed、1 deselected。排除项 `test_two_real_sessions_racing_same_app_order_create_one_invoice` 在未排除运行中失败，因其旧夹具缺 `ark_commerce_transition_policy`；加载基点 `6cacc6fa` 的原 integration/service.py 重跑同项仍失败，非本次引入。扩大套件之后新增的 4 个快照边界回归已包含于最终 65 项。
- `alembic heads`：仅 `251_alibaba_feed` 一个 head。实际 MySQL 验证仅运行新增迁移与必需基表，没有伪装为全历史空库迁移验证。
- 真实 MySQL 验证：半完成 DDL 续建、完整重复核验、结构漂移拒绝、精确 ID、微秒观察值、并发幂等/额度、行锁等待跨到期拒写和同批恢复均通过。结果保留在本工作区 `tmp/mysql-validation-result.json`；脚本 `tmp/validate_mysql.py`、`tmp/validate_mysql_fences.py` 不包含真实 token。
- `check_conventions.py --strict`：红0/黄5；黄项为静态检查器未识别专用机器鉴权与实时 JWT 管理依赖，已通过源码说明、真实 HTTP 权限和撤权回归人工确认；未修改检查器白名单。`git diff --check` 与暂存差异检查通过。
- `git_sweep.py --no-fetch` 完成，仅为本地远端引用快照，未获取最新远端，不代表远端实时状态。没有前端改动，未运行无关前端构建。
- 测试显式使用 DB host `127.0.0.1`、port `1` 的哨兵配置；MySQL 验证脚本只连接独立回环端口33175。全路由测试缺失的既有依赖 reportlab 按 requirements 安装在本任务 `tmp/test-deps`，通过 PYTHONPATH 加载，未改共享 venv。
- 两个任务测试库均已删除，MySQL 已正常关闭，进程33412及端口33175均不存在。工具策略拒绝临时 `tmp/mysql-data` 的递归清理，未给出更具体原因；目录保留，没有绕过策略或改动其他工作区的 MySQL 文件。

完整生产发布、Accio 定时任务真实推送、生产凭据发放和业务试点未执行。
