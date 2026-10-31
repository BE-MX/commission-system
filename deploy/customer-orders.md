# 客户下单门户发布与验收

客户确认入口 `https://shop.leshine.cloud`，北京后端承接；员工使用 `https://leshine.cloud`。`platforms.json` 仅登记发布目标，不证明站点已部署或业务已验收。最近发布与实机验收见[交接文档](../docs/handoff.md)；[10 月 10 日准备记录](../docs/requirements/2026-09-30-customer-order-portal/09-production-readiness-2026-10-10.md)是历史阶段证据。

2026-10-10 的员工登记密码登录已保留；后续增加申请审批及邮件激活，当前完整认证契约见[门户 API](../docs/requirements/2026-09-30-customer-order-portal/03-api-contract.md#当前认证契约2026-10-31-源码核对)。客户、业务员及生产流程测试由用户选择操作；代理不编造客户、合同价、库存单位或执行身份。门户边界止于方舟正式 PI，回款/出库继续使用既有模块。

## 固定版本与 HTTPS

代码在所属 codex worktree 验证。操作绑定干净候选完整 SHA；禁止 latest、stamp、开发机升级共享生产库。

```powershell
deploy\deploy.bat --customer-portal-site https --revision <full-sha> --prepare-only
deploy\deploy.bat --customer-portal-site https --revision <full-sha>
deploy\deploy.bat --customer-portal-site verify --revision <full-sha>
```

基础设施入口核对全部 DNS 地址、Nginx 归属、模板/脚本摘要及当前配置摘要。仅客户 `/api/portal/v1/` 代理到回环后端 `127.0.0.1:8001`；员工/其他 API 和点文件返回 404。清除 Authorization、X-Forwarded-For/Proto 和 Forwarded；X-Real-IP 由 TCP 客户端覆盖。API/HTML no-store，关闭原始 access 日志和代理缓存/缓冲。

远端锁、激活前原子 pending journal、受限备份和严格字节比对保护恢复。只读 verify 遇 pending 拒绝，同固定版本 https 动作才允许恢复；原配置恢复后也必须 reload。未知漂移不能覆盖。证书/SNI当前有效和自动续期链是独立验收项。

客户站随完整受管发布构建：冻结 pnpm-lock、禁用安装脚本，仅传静态制品，经摘要差异传输和受管切换到 `/var/www/ark-static/customer-orders`。不向办公室发布客户站，不传 .env/密码/业务数据。

## 首次 182→183 迁移专项（历史基线）

本节保存首次密码认证迁移的演练和保护条件，不是后续每次发布的固定目标。当前 schema 已高于 183 时不得照抄 182→183 演练或回滚；一般升级走[统一部署入口](README.md)对实际 schema 与候选链的预检。

新增 `183_portal_password_login` 的父 revision 为 `182_announcement_reads`。只给账号表增 nullable `password_hash VARCHAR(255)`；不设默认密码、不激活历史账号、不删除业务行。downgrade 拒绝丢弃密码哈希。有权员工明确设置密码并恢复账号时，当前授权内 invited membership 转 active，disabled membership 不自动恢复。

本轮期间生产已发布182，未发布的181密码迁移因此重新编号183。旧180→181隔离演练虽通过，不能用于182→183门禁；需重新备份实际182并恢复/升级/恢复182/重放183。候选必须包含当前双后端已发布代码。

维护窗还必须覆盖实查的额外写入者：北京 `/etc/cron.d/ark-agent-sync` 的 sync-outbound.js，以及源库小时事件 `evt_update_shipment_tracking_dingtalk_user`（原定义者root@%，global event_scheduler=ON）。在办公室受保护 `.deploy_state/credentials/event-maintenance.env` 提供仅含 COMMISSION_DB_USER、COMMISSION_DB_PASSWORD 的独立事件管理身份；它需能保留原definer并读取Performance Schema线程。migration.env与应用.env保持原配置，密码不写入文档或聊天。

预检在停服务前验证凭据、目标UUID、原事件各字段摘要、P_S线程可见/注册/无lost线程，以及已核cron原始摘要。维护持有原 `/tmp/okki-outbound.lock`，不改cron；等待在途与手工同步排空，临时DISABLE事件并核原definer/原始摘要，所有登记服务停止后再完整备份/DDL。人工同步在整个维护窗须遵守同一锁；每次复核发现额外手工进程即阻断。全部制品和worker验证后恢复原事件及cron锁，再完成journal。DDL前失败恢复原运行状态；DDL后失败保留围栏与停写，先检查恢复材料，不能直接重启旧代码。

空库全链仍要求 126 的真实客户切换合同，缺失时失败必须保留，不能绕过/stamp。精简 fixture 的176/177/183 DDL不证明生产基线升级。

先在办公室已安装服务的受管候选生成完整逻辑备份：

```powershell
# 候选须位于 D:\commission-system\.deploy_state\sources\<SHA>，已安全传入该机 Git。
deploy\deploy.bat --customer-portal-db-backup --live-root D:\commission-system --revision <full-sha> --no-pull
```

受保护独立 DBA 配置位于 `.deploy_state/credentials/migration.env`；受审工具清单位于 `.deploy_state/tools/mysql-8.4.6/manifest.json`。备份目录仅办公室用户/SYSTEM可读；唯一客户端配置、禁用login paths及显式核定TCP目标保护连接，临时凭据finally删除。受管DB锁阻断并发DDL，InnoDB单事务备份不暂停正常业务写入。备份时间、UUID、revision、字节和摘要是备份证据，不等于恢复成功。

备份账号需在 commission_db 上有 SELECT、SHOW VIEW、EVENT、TRIGGER，及全局 SHOW_ROUTINE 定义可见性；迁移的读写/DDL 权限不能代替完整备份权限。先重新连接读 `CURRENT_USER()` / `SHOW GRANTS`，由有授权权限的实例管理员补齐实际匹配的 user@host，不能把 host 改成 `%` 或自动授予全局数据读取。动态 SHOW_ROUTINE 允许读取例程定义，见[MySQL 权限说明](https://dev.mysql.com/doc/refman/8.0/en/privileges-provided.html#priv_show-routine)。预检遇部分撤权拒绝；不能仅汇总 GRANT 忽略 REVOKE。账号不能给自己授权。Grant 后无需编辑/替换受保护密码文件。

新目录、独占回环 MySQL、随机凭据、受限 ACL、关闭 event_scheduler 的隔离库恢复真实182备份。数据库名称保留 commission_db 以恢复限定名称的存储对象，连接仍只能使用新进程的随机回环端口/随机密码，不复用生产目标。在源库完整定义可见性已核验的只读事务中，使用 `storage_snapshot.schema_snapshot` 记录真实建库字符集/排序规则、`storage_snapshot.stored_objects_snapshot` 获取视图/例程/事件/触发器的 SHOW CREATE 字段摘要；不输出 SQL 正文，记录实际 UUID/revision，另存摘要 manifest。

仅在无 backend/.env 的隔离工作树，单独运行恢复规格（路径均须替换为已核实的绝对路径）：

```powershell
# 在 backend 下，运行已验证 Python；backup/receipt 在同一受限目录。
python -m pytest --confcutdir=tests/portal_mysql tests/portal_mysql/test_mysql_production_upgrade.py --portal-mysqld <owned-mysqld.exe> --portal-mysql-workspace <new-private-directory> --portal-production-backup <protected-commission_db.sql> --portal-production-objects <source-object-hashes.json> --portal-restore-ssh <verified-ssh.exe> --portal-restore-host ubuntu@154.8.205.162 --portal-restore-client /home/ubuntu/commission-system/.deploy_state/tools/portal-restore-client-8.4.6/extracted/usr/bin/mysql --portal-restore-sha256 c0d0308027906c5116bd4ff6f86923cca04ff969b9cc6c4897aad1ec0da8b618 -q
```

恢复通道使用固定摘要 Linux mysql8.4.6、`--binary-mode`、禁用login paths，经SSH仅回环反向转发到测试独占进程；传SQL之前及每次恢复前核对实际listener、进程UUID/端口、scheduler OFF。远端只保存受限短期测试密码，原始备份通过SSH流式发送，finally删除两端凭据并关闭隧道。Windows客户端会在batch_readline移除行尾CR，即使binary-mode也会改变原定义；禁止用它恢复此备份或通过归一摘要掩盖差异，见[官方实现](https://raw.githubusercontent.com/mysql/mysql-server/mysql-8.4.6/client/readline.cc)。源schema实际为utf8mb4/utf8mb4_unicode_ci，不能默认建为0900。

由原Alembic升级183，核对全部原业务行/FK/唯一键与源库存储定义摘要，再恢复182并重放183；禁止stamp/伪造基线。事件定义恢复时调度器保持OFF。成功proof含真实schema、固定Linux通道/客户端摘要、scheduler持续OFF、源定义核验与恢复后的原始字节定义不变标志，放入办公室 `.deploy_state/customer-portal-upgrade-proof.json`；未带源定义摘要的旧proof不能进入生产183门禁。

完整应用发布仍走办公室候选 `deploy.bat --live-root ... --revision ... --no-pull --prepare-only`；准备通过后同固定参数去掉 prepare-only。实际唯一182→183链、独立DBA和全部writer预检通过后，维护窗口停止登记writer，再取新的完整备份后一次升级。包含183的其他未演练链拒绝，不让更长pending绕过门禁。DDL后失败保留停写/journal，不能自动重启旧代码或强改revision。生产恢复只能使用维护窗口备份，核对备份后是否有新交易；新数据先保全，不把旧演练快照覆盖生产。只恢复原运行writer，不启动原本停用的服务。生产恢复也须使用上述固定Linux客户端的保字节通道，在受保护配置中由独立DBA核对恢复目标UUID、维护备份摘要/源schema、全部writer停写及事件调度策略后操作；不要把测试用root密码或owned反向端口用于生产，也不要在开发机发出生产恢复SQL。恢复后复核原始存储定义、行数/约束、revision以及应用版本，证据齐全才恢复原运行服务。RDS控制台恢复实例与保留策略未核实前不能宣称该路径已验收。

## 受保护配置及分阶段开放

逐键合并实际 .env，保留其他配置、权限和受限备份。源码默认开关为 false，不表示生产实际值。`prepare` 仅适用于尚未开启门户；当前 `customer_portal_config_remote.py` 的 `enable-access` 仍严格要求 schema 等于 `183_portal_password_login`。高于 183 的环境不能照抄首次开放命令，更不能 stamp/downgrade 绕过；后续首次开放需先修正并验证该入口的版本条件。`enable-orders`、`stop-orders`、`close` 按各自实际前提执行，不因这项限制一概退役。

```powershell
deploy\deploy.bat --customer-portal-config prepare --revision <full-sha>
# 固定应用与183已实际激活后，开账号管理/登录，交易与通知仍关闭。
deploy\deploy.bat --customer-portal-config enable-access --revision <full-sha>
# 员工已建启用站点且后端有reportlab后，只开下单与PI；邮件/通知/出库保持原值，失败自动恢复原配置。
deploy\deploy.bat --customer-portal-config enable-orders --revision <full-sha>
# 停止订单写入/建票，保留其他独立能力。
deploy\deploy.bat --customer-portal-config stop-orders --revision <full-sha>
# 全面封闭门户。
deploy\deploy.bat --customer-portal-config close --revision <full-sha>
```

实际 origin/site code、leshine-okki身份来源、回环可信代理、独立CSRF/AUTH密钥在服务器合并，秘密不输出。密码登录不依赖SMTP。AUTH_SECRET参与耐久创建回执摘要，当前没有摘要keyring，不能随意轮换；轮换前须专门实现和验收旧摘要保留。配置修改经受管重启刷新缓存，重启前后大小写无关核对实际进程覆盖与生效配置；非规范/重复dotenv键在生成密钥前拒绝。进程覆盖或非规范配置导致前检拒绝时，不能宣称已停单，需先处理其受保护来源。停单/关闭后检失败保留关闭配置并暂停后端，绝不自动恢复接单；已停服务可再次关闭配置且保持停服，回执closed_paused不证明重新启动后的生效配置。

| 开关 | 能力及开放前提 |
| --- | --- |
| PORTAL_ENABLED | 管理站点/真实客户/采购密码和授权目录；还需用户创建有效站点与真实授权 |
| PORTAL_WRITES_ENABLED + 客户can_order | 报价、提交及客户确认；合同价/库存单位/刷新语义、失效与幂等/隔离验收 |
| PORTAL_INVOICE_ENABLED | 正式PI及下载；完整提案、唯一建票、金额/PDF/存储及恢复验收 |
| PORTAL_MAIL_ENABLED | 总开关同时启用时投递邀请/验证码；邮件激活须验收实际送达，密码登录不依赖 SMTP |
| PORTAL_MAIL_ENABLED + PORTAL_NOTIFICATION_ENABLED | 业务邮件通知；SMTP、批准真实收件范围、送达及失败恢复，与认证邮件分开验收 |
| PORTAL_OUTBOUND_WORKER_ENABLED | 独立出库执行器，本轮false；门户打开不接管出库或启用自动回款/小满推送 |

验收顺序：员工授权与账号→密码登录、撤权/跨客户隔离→商品/合同价→库存及价格失效→下单/重复提交/丢ACK恢复→员工完整提案/客户接受→唯一PI/下载→通知及失败恢复。写测试仅隔离库，真实发信和生产交易由用户在其批准范围操作。尚未完成验收的能力不得标为正式开放。

暂停单个客户授权立即撤销会话；停止接单先关WRITES/INVOICE；全面封闭可关站点status或PORTAL_ENABLED。保留历史订单、PI、审计和持久出库模式。构建、配置写入和健康检查均不能代替业务上线验收。
