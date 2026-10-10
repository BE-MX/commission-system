# 客户下单门户发布与验收

客户确认入口 `https://shop.leshine.cloud`，北京后端承接；员工使用 `https://leshine.cloud`。`platforms.json` 仅登记发布目标，不证明站点已部署或业务已验收。实机结果见 `docs/requirements/2026-09-30-customer-order-portal/09-production-readiness-2026-10-10.md`。

2026-10-10 用户确认：方舟员工登记采购邮箱、联系人和密码，客户直接密码登录，不走邀请或邮箱验证码。客户、业务员及生产流程测试由用户选择操作；代理不编造客户、合同价、库存单位或执行身份。门户边界止于方舟正式 PI，回款/出库继续使用既有模块。

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

## 180→181、备份与恢复

新增 `181_portal_password_login` 的父 revision 为 `180_settlement_funding_amendment`。只给账号表增 nullable `password_hash VARCHAR(255)`；不设默认密码、不激活历史账号、不删除业务行。downgrade 拒绝丢弃密码哈希。有权员工明确设置密码并恢复账号时，当前授权内 invited membership 转 active，disabled membership 不自动恢复。

空库全链仍要求 126 的真实客户切换合同，缺失时失败必须保留，不能绕过/stamp。精简 fixture 的176/177/181 DDL不证明生产基线升级。

先在办公室已安装服务的受管候选生成完整逻辑备份：

```powershell
# 候选须位于 D:\commission-system\.deploy_state\sources\<SHA>，已安全传入该机 Git。
deploy\deploy.bat --customer-portal-db-backup --live-root D:\commission-system --revision <full-sha> --no-pull
```

受保护独立 DBA 配置位于 `.deploy_state/credentials/migration.env`；受审工具清单位于 `.deploy_state/tools/mysql-8.4.6/manifest.json`。备份目录仅办公室用户/SYSTEM可读；唯一客户端配置、禁用login paths及显式核定TCP目标保护连接，临时凭据finally删除。受管DB锁阻断并发DDL，InnoDB单事务备份不暂停正常业务写入。备份时间、UUID、revision、字节和摘要是备份证据，不等于恢复成功。

新目录、独占回环 MySQL、随机凭据、受限 ACL、关闭 event_scheduler 的隔离库恢复真实180备份。单独运行 `test_mysql_production_upgrade.py`，由原Alembic升级181，核对全部原业务行/FK/唯一键不变，再恢复180并重放181；禁止stamp/伪造基线。成功proof放入办公室 `.deploy_state/customer-portal-upgrade-proof.json`。

完整应用发布仍走办公室候选 `deploy.bat --live-root ... --revision ... --no-pull --prepare-only`；准备通过后同固定参数去掉 prepare-only。实际唯一180→181链、独立DBA和全部writer预检通过后，维护窗口停止登记writer，再取新的完整备份后一次升级。包含181的其他未演练链拒绝，不让更长pending绕过门禁。DDL后失败保留停写/journal，不能自动重启旧代码或强改revision。生产恢复只能使用维护窗口备份，核对备份后是否有新交易；新数据先保全，不把旧演练快照覆盖生产。只恢复原运行writer，不启动原本停用的服务。

## 受保护配置及分阶段开放

逐键合并实际 .env，保留其他配置、权限和受限备份。默认开关仍false，不绕过require_enabled。

```powershell
deploy\deploy.bat --customer-portal-config prepare --revision <full-sha>
# 固定应用与181已实际激活后，开账号管理/登录，交易与通知仍关闭。
deploy\deploy.bat --customer-portal-config enable-access --revision <full-sha>
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
| PORTAL_MAIL_ENABLED + PORTAL_NOTIFICATION_ENABLED | 业务通知；SMTP、批准真实收件范围、送达及失败恢复；不参与登录 |
| PORTAL_OUTBOUND_WORKER_ENABLED | 独立出库执行器，本轮false；门户打开不接管出库或启用自动回款/小满推送 |

验收顺序：员工授权与账号→密码登录、撤权/跨客户隔离→商品/合同价→库存及价格失效→下单/重复提交/丢ACK恢复→员工完整提案/客户接受→唯一PI/下载→通知及失败恢复。写测试仅隔离库，真实发信和生产交易由用户在其批准范围操作。尚未完成验收的能力不得标为正式开放。

暂停单个客户授权立即撤销会话；停止接单先关WRITES/INVOICE；全面封闭可关站点status或PORTAL_ENABLED。保留历史订单、PI、审计和持久出库模式。构建、配置写入和健康检查均不能代替业务上线验收。
