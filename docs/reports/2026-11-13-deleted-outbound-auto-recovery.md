# 小满旧出库删除后的发票自动恢复

## 状态与范围

- 用户要求：今后在小满删除旧出库单后，重新同步发票能自动核对并按最新版重建，不再手工修改数据。
- 独立工作区：`D:/MyProgram/commission-system-codex-deleted-outbound-auto-recovery`；分支 `codex/deleted-outbound-auto-recovery`，基点 `c4e89879`。实现阶段无新的生产业务写入。亮哥后续明确授权合并推送、拉取最新 Git 并全局部署；实际交付与发布以随后核验记录为准。
- 此前「翟1133」已在独立授权下定点恢复并回读验证；现场处理不等于本功能已发布。

## 实现

- `deleted_outbound_recovery.before_sync` 接普通同步和保存并同步；普通编辑与读取不触发恢复。复用共享出库执行锁，外部 GET 期间不持有业务事务，取证后重新锁定并比较完整快照。
- 只选择唯一未隐藏、待出库、全部明细关联当前订单、客户一致的原镜像，要求原自动任务已完成。预售、分批、多订单、已出库和明确失败的旧删除审计保留原流程。
- 精确 ID 缺失，或保留的软删除详情及有效列表证明缺失；校验软删除详情的状态、客户、每条关联，再查当前订单完整有效关联，最后复读旧单。不能把列表异常、权限错误、一般 HTTP 404 或空值当作删除。
- 已接受但回读未完成的出库更新链必须租约结束、所有发送事实明确接受、成功凭证身份一致。原事实和 claim 不改写，追加 FINISH 与删除核验记录；原状态、镜像隐藏审计和任务 `skipped/deleted:<ID>` 同事务提交。
- 最新订单推送成功后，原 follow-up 才重新排队。重建沿用原查重、仓库库存、冻结请求、发送账本及回读验证。库存不足仍等待，未知结果不重发。
- 重建比较成功 `create/update` 日志，排除普通成功审计；记录删除前最后成功日志 ID，处理 MySQL DATETIME 同秒精度。Python worker 核对本地镜像 ID 与小满 ID 的映射，不再要求两者相等。
- 原回款、验货和照片不修改；新单依原检验流程办理。没有新增表、迁移、权限或前端界面。

## 验证

- 隔离 SQLite：`pytest tests/test_deleted_outbound_recovery.py tests/test_invoice_linked_sync.py tests/test_invoice_outbound_tasks.py tests/test_outbound_invoice_sync.py tests/test_outbound_delete.py -q --tb=short`，273 项通过；最终补充历史删除失败及真实排队链路后，专项 `test_deleted_outbound_recovery.py` 30 项通过。累计 274 个不同相关用例。测试使用供应商替身，不调用真实小满写接口。
- Node：`node --test deploy/tests/test_okki_outbound_order_guard.mjs` 28 项；`node --test deploy/tests/test_okki_outbound.mjs deploy/tests/test_okki_outbound_isolation.mjs deploy/tests/test_okki_outbound_mode.mjs deploy/tests/test_okki_outbound_remarks.mjs deploy/tests/test_okki_outbound_stock.mjs` 129 项，合计 157 项通过。
- 独立审查发现的软删除详情、关联返回类型、历史删除失败误拦问题均已修复并复核；最终无阻断项。覆盖过期版本、权限撤回、发送租约、重复请求、期间数据变化、提交回滚、同秒新代次、真实排队及 worker 读取。
- `python scripts/check_conventions.py --strict` 和 `git diff --check` 通过。`python scripts/git_sweep.py --no-fetch` 完成，仅本地快照；其他工作区欠账未动。无前端改动，不做无关构建或浏览器验收。
- MySQL 8.0.46 独占回环临时进程已启动验证；`test_mysql_order_push_execution.py` 首个创建用例返回 500。打开测试 ASGI 异常后确定为旧合成夹具缺少 `ark_commerce_sending_claims`，错误发生在原发送 `begin_send`。在未修改 `c4e89879` 临时 worktree 上运行同一用例得到相同缺表错误（1 failed），并非本次新增路径；未修改旧夹具，不能宣称 MySQL 集成通过，也未继续执行 worker 用例。基线日志在本任务 `backend/tmp/mysql-baseline.log`，运行元数据及 MySQL 日志在 `backend/tmp/mysql-recovery-*`。测试进程均已关闭；清理合成数据库 data/temp 的命令被自动审批以 `blocked by policy` 拒绝，未改用其他工具绕过，目录暂留。
- 保留既有 jose `utcnow()` 弃用警告。本轮未验证正式 MySQL 并发或真实供应商端到端流程。

## Git 与生产发布结果

- 实现 `c090e6d2c8ac1075687fc1610e641e04ce89dd90` 已在主目录合并并推送，远端完整 SHA 核验一致；后续恢复控制提交为 `514a51937cf5f3bc08a452d8f075bf303c343908`。主目录其他任务的改动保留，发布回执与本文后续文档提交不代表应用版本再次变化。
- 办公室 SSH 采用用户更正的 2224，并匹配原已固定主机密钥。办公室 Git 代理失效、直连重置，采用本机已核验 Git bundle 传入同一固定候选，再走 `deploy/deploy.bat`，未更改主机密钥校验或覆盖生产配置。
- 发布 ID `2214cf999d394ecf85506c62aad1be20`，两地运行版本均为 `c090e6d2`；统一入口完成 `259_outbound_link_proof → 260_client_desk_board → 261_followup_insights → 262_invoice_customer_sync_log`。三张新表和四个私海状态列已独立读回；客户归属同步所需 `ark_app@%` 的 UPDATE(owner_user_ids) 与四列 INSERT 最小授权已核验，其他授权保持原状。办公室现有数据库账号为 root，北京为 ark_app，本轮没有更换账号。
- 办公室后端/连接器、北京后端/色块、两处色块路由和五个云端静态目标均完成。原出库模式 legacy，实际工件摘要 `6c851e91c90b4d596db31adecaeebd6d20a6cb69edd8908d1c36acabfa6253fc`，回执 verified，timer active/enabled；邮件 Worker 版本核验通过，保留 inactive/disabled。迁移 writer 记录 completed，原关联服务恢复。未纳管侧车及小程序不计作本次发布。
- 切换前临时冻结三处 AI 入口，实际两地线程均无正在运行的 AI 调用；一组 7 月遗留 generating 行未伪造清零。发布后 Nginx/Caddy 回到原配置摘要，办公室直连 8001 和 AI 路由已恢复。

## 发布中断及受控接续

首次激活已完成迁移及两地应用，随后新加坡色块健康探测因 `leshine.work` 多地址 DNS 选择北京而 TLS 重置。原发布停在 `office / beijing-backend / colorwork-routing:cloud`，出库保持暂停，没有反复运行全量部署。

补充的恢复入口绑定原 revision、release ID、失败发布及迁移回执原始 SHA256，并验证实际源码、健康、schema、工件、writer 与邮件原基线。通过统一 deploy.bat 的 prepare-only 后接续路由、种子、静态、出库和关联服务，未重复 DDL 或应用重启。每阶段记意图与完成，失败不能直接重入；成功回执 status/recovery 均为 succeeded。回执保留首次失败的 error_type 作为历史字段，不代表恢复失败。

色块健康探测改为固定注册 IP，仍保留域名/SNI/证书校验，禁用代理且不跟随重定向。102 项部署定向回归通过，含完整恢复编排、半途失败留证和再次执行前阻断；独立审查无阻断项。候选两份生成导航文件内容逐字节等同 HEAD，恢复检出换行格式后通过源码清洁检查。

## 现场验收与保留事项

- 两地新恢复函数可导入，schema262、三张新表、私海列及目标列级授权读回通过。翟1133发票仍 synced，原重建任务1435仍 done；未为验收再删单或发送生产同步请求。新增自动删除重建功能的真实供应商端到端验收仍未执行，不将代码与健康验收冒充真实业务写入验收。
- 部署工具的 26/26 项必需检查通过。后续未固定地址的 `leshine.work` 首页回读仍因 DNS 选址重置失败，不能报所有公网检查无异常；固定三处正确目标后，办公室内网及两公网主站均加载 `/assets/main-Cp9FhEou.js`。
- 固定正确目标时 `leshine.cloud → 154.8.205.162`、`leshine.work → 119.28.107.92` 的 HTTPS health 均为200/ok/connected。公网 DNSPod 同时为 `leshine.work` 返回两条 A（119.28.107.92、154.8.205.162）；后一地址的该域名 TLS 握手实测失败。未改 DNS，普通访问可能因选址出现间歇失败，此项独立于本次应用发布完成状态。
- 静态/候选历史制品清理按部署器约定 deferred，保留回滚与恢复材料。此前 MySQL 合成 data/temp 清理被自动审批拒绝，未绕过；本任务工作区暂留，所有临时 MySQL 进程已关闭。
- 本机证据目录：主目录 `.deploy_state/deleted-outbound-release-20261113/`，包含 prepare/recovery/verification 日志、原失败回执、最小授权回执、各地只读功能验收与公网定向健康结果。
