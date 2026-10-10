# 2026-10-10 客户下单门户生产准备记录

本记录区分服务器观测、隔离验证和真实经营验收。用户确认 `shop.leshine.cloud` 由北京承接，员工在方舟登记采购邮箱/密码；真实客户、业务员、商品、合同价和生产流程验收由用户自行选择。代理未代建真实账号、客户、订单或发送客户邮件。

## 实机核对与已完成准备

| 项目 | 实际观测 / 证据边界 |
| --- | --- |
| 办公室后端 | `D:/commission-system`，NSSM CommissionSystem Running；末次只读核对 HEAD `1227af7b5328c51b2c007a689d1e967545931b18` |
| 北京后端 | `/home/ubuntu/commission-system`，ark-backend active，127.0.0.1:8001；末次同为 `1227af7b5328c51b2c007a689d1e967545931b18` |
| 数据库 | 共享 commission_db，UUID `0c03e207-631c-11f1-b388-b8cef6741ade`，8.0.30-cynos-3.1.19.002；末次唯一 revision `182_announcement_reads`，本任务未执行生产DDL |
| 候选归属 | 独立 `codex/customer-portal-readiness`，已整合当前实机1227af7b；未发布密码迁移从181调整为183，父182，单head。本任务代码尚未激活；旧180→181 proof不能用于新路径 |
| 配置加载 | 两后端各自 backend/.env；实际进程未见 PORTAL 环境覆盖。北京逐键合并受保护配置，.env0600归实际systemd ubuntu用户；以服务UID/GID核验可读，不输出秘密 |
| 门户开关 | 北京prepare已完成，独立CSRF/AUTH密钥已生成并在重复prepare保留；ENABLED/WRITES/INVOICE/MAIL/NOTIFICATION/OUTBOUND均false，actor0；尚未执行enable-access |
| 客户站 | frontend-portal 已登记北京目标 `/var/www/ark-static/customer-orders`；末次实查 index.html 不存在，静态应用未发布 |
| DNS / HTTPS | shop A=154.8.205.162；已安装受管Nginx与可信证书，实际证书有效期2026-10-10 06:12:52 UTC至2027-01-08 06:12:51 UTC |
| API边界 | 公网HTTPS实测客户session503（功能关闭），员工门户admin、auth/me、health与.env均404；仅客户API回环代理，身份/转发头按受管模板处理 |
| 续期 | 之前CA第二验证点超时；用户放通TCP80后重新执行certbot renew --cert-name shop.leshine.cloud --dry-run --non-interactive，实际exit0、simulated renewal success。公网挑战200、timer/deploy hook均已核验；非交互随机延时372.8秒不等于失败 |
| 邮件 | 原门户SMTP为空；Agent外联链路不是门户SMTP。新密码登录不依赖邮件；业务通知SMTP/批准收件范围/送达未验收，保持关闭 |

这是各项末次观测，不将初检e26版本或仓库配置登记冒充服务器当前状态。生产切换前须再次核验两台HEAD、DB revision、部署锁/journal。

## 客户与经营来源

24个门户表已安装；初检及复核 site/access/account/membership/catalog授权/outbox/订单/PI等为0，仅authority barrier1和审计21。生产没有可据此宣称已授权的客户或采购账号。

实际强身份来源 okki/leshine-okki2462条、public_web/global91条。leshine-okki只是现有namespace，不构成客户授权。media.leshine.cloud用于素材门户，不复用其权限。

镜像 okki_inventory915条，unit NULL712条、Piece203条；初检 synced_at 在2026-10-10 14:00:00–14:06:16。导入器每轮是否刷新未变化的活跃行、时间时区、逐SKU交易单位、可售量含义、跨仓重复语义均未证明。不能把Piece自动映射为所有SKU，不能开启空单位商品下单。真实商品可见性、合同价和客户can_order由用户选定后验收。

## 备份、迁移和恢复进展

- 完整备份第一次执行在事件导出失败，留下767,035,809字节未完成SQL；确认mysqldump已结束后已删除该无效部分，保留受限failed.json/dump.stderr。它不是可恢复备份，未用于迁移或恢复。
- 实际独立账号为 `ark_migrator@112.255.254.200`。用户补权限后重新连接实查：commission_db 的原读写/DDL及新增 SHOW VIEW/EVENT/TRIGGER、全局 SHOW_ROUTINE 均存在，无GRANT OPTION。受保护migration.env没有被替换或输出。
- 实际完整可见性下，源库views0、routines0、events1、triggers0；只读采集该事件SHOW CREATE各字段摘要，没有输出定义正文。源摘要绑定UUID及180。
- 新完整备份已通过办公室固定候选8660e58b成功生成：2026-10-10 07:48:02至07:57:03 UTC，767,327,823字节，SHA256 `650f6a174366c36bcce1c9b7898700d71de4a19b47aa7604b685867673a5d660`；受限目录 `.deploy_state/customer-portal-backups/f7d897f41f364ba6b7dd9f9bacabfd2b`。未停服务、未执行DDL。
- GameViewer办公室SSH转发恢复后安全传输完成；本机受限解压文件字节/摘要与办公室回执一致。初次恢复发现源schema utf8mb4_unicode_ci与fixture硬编码0900不一致，且Windows mysql即使binary-mode仍去除事件正文26处CR；原备份保留CR。已修真实schema manifest，改用固定SHA Linux mysql8.4.6经SSH回环连接owned MySQL，保留原始摘要校验。实际180→181→恢复180→重放181已通过，1952.09秒；392张原业务表、2,483,347行、全部原列值/FK/唯一键及源事件原始字段摘要不变，clone scheduler持续OFF。完整proof保留在受限目录mysql-production-180-181-20261010-r4，仅作为历史路径证据。
- 完成旧路径后复核发现其他发布已将双后端更新1227af7b、库升级唯一182；只读核验实际revision，未绕过旧180断言。已整合已发布代码并将未发布密码迁移调整183/父182，须重新生成实际182备份及完整182→183恢复proof，不能沿用旧proof。
- 备份工具8.4.6按SHA清单核验，客户端临时凭据在受限目录且finally删除。Windows独立pnpm12.6.0/NSSM真实可执行路径与已安装Python已就绪，不等同于应用发布。
- 发布预检在停writer之前检查完整权限、新恢复proof及独立事件管理凭据；只接受单182→183。实查额外写入者为北京sync-outbound.js cron和源库小时事件（root@%定义，scheduler ON）；现有migration身份不能保留原定义者暂停事件。事件管理文件尚未提供，生产停写/发布因此阻断，尚未冻结cron或改源库事件。
- 维护实现先持有原cron独占锁、核已批准原始cron摘要并排空定时/手工同步，暂停事件且核原definer/rawhash、P_S可见性/注册/lost0/活动线程排空，然后停止登记服务、新备份及DDL。所有制品与worker后检通过后恢复原事件和cron锁。DDL前失败恢复原运行状态；DDL后失败保留围栏/journal。实际生产冻结/恢复未验收。
- RDS控制台备份保留/恢复实例尚未实核；生产恢复须核对备份之后的新交易并先保全，不用旧演练快照覆盖生产。

## 代码及隔离验证

- 员工创建/重置邮箱密码账号，密码哈希、现行客户授权二次核验、会话撤销、锁外哈希、持久限流、幂等创建/未知结果重试已实现。183仅加nullable哈希，没有默认密码或自动激活。
- 已移除客户端邀请/OTP HTTP入口；历史invited成员需员工明确恢复，disabled成员不自动恢复。AUTH_SECRET参与耐久回执，没有摘要keyring，不能随意轮换。
- 门户启用与出库持久模式/worker分离，不因启用门户打开小满推送、自动回款或出库执行器；既有OKKI_OUTBOUND_AUTO_ENABLED=true属原业务配置，本轮保留。
- SQLite门户747 passed/2默认浏览器skip；密码/管理/HTTP专项69 passed。浏览器已另行显式执行，实际HTTPS登录10场景与交易9场景共2 passed，包含Cookie/CSRF、跨源/代理、撤权、客户交易至PI/PDF且无ReceiptIntent。使用合成数据/隔离SQLite，无生产写入或真实邮件。
- 客户Node130项及客户/员工授权联合135项通过，员工账号命令契约10项通过；客户/员工站构建成功，既有大chunk提示保留。组别有重叠，不汇总成一个总数。
- 独占MySQL首次55通过/4 fixture失败已修复；复跑63 passed/10未选择opt-in skip。覆盖真实DDL、交易、模式选择、认证限流及部署隔离，不是生产备份恢复证明。
- 空库全历史链在126真实客户切换合同门禁失败，停在125；没有stamp或绕过。不能把精简fixture的DDL覆盖当作生产基线。
- 部署6文件专项96通过；后续受保护配置/HTTPS/DBA专项39通过，最新完整权限/新proof专项38通过（另SSH监听边界5通过）（含partial revoke拒绝）。组别重叠。
- 独立agent已审查密码/权限/出库/HTTPS/配置恢复/备份与owned clone边界；已修复历史成员恢复、昂贵哈希前鉴权、服务读取身份、临时.env权限窗口及partial revoke误判。恢复通道独立审查要求清理互不跳过、proof核真实schema/通道/客户端摘要/scheduler以及实际SSH监听回环；均已收口，未以归一SQL摘要放行。
- 维护专项真实owned MySQL 2 passed/15.87秒：暂停/恢复保留原始定义（含CRLF、definer、属性），真实活动event worker在INSTRUMENTED=NO时仍可见并排空。部署受影响7文件87 passed；扩展部署全组728 passed/17 skips/1既有storage_routing mock耗尽失败（本任务未改该实现/测试）。独立审查另要求拒绝未持锁cron伪装及READY后新手工同步，已补原始批准摘要/每次进程复核及回归。

## 当前可开放范围与剩余验收

当前生产功能仍关闭，**没有能力可标记为正式开放**。新182→183 proof、事件管理权限及固定候选发布完成后，先开员工管理/授权密码登录供用户设置真实业务；下单、PI和通知分别通过验收后再开。

| 能力 | 对应开关 | 尚缺证据 |
| --- | --- | --- |
| 账号管理/授权登录 | PORTAL_ENABLED + 有效站点/客户/采购成员 | 候选/183实际发布、静态站、真实客户账号和撤权/跨客户隔离验收 |
| 商品/合同价查看 | 上述开关 + 显式目录授权 | 用户选定的实际商品/合同价可见性 |
| 报价/下单/确认 | PORTAL_WRITES_ENABLED + 客户can_order | 库存单位/刷新语义/金额、价格库存失效、重复提交和失败恢复 |
| PI/下载 | PORTAL_INVOICE_ENABLED | 员工提案/客户接受/唯一建票、PDF资产/存储及下载撤权 |
| 业务通知 | PORTAL_MAIL_ENABLED + PORTAL_NOTIFICATION_ENABLED | 独立SMTP、批准收件范围、实际送达及失败恢复 |
| 出库执行器/小满推送/自动回款 | 不随门户启用开放 | 本轮无新增开放范围，保持既有业务边界 |

完整操作及故障步骤见[客户门户发布与验收](../../../deploy/customer-orders.md)。顺序为固定候选→HTTPS/disabled配置→实际182完整备份/隔离恢复proof→事件DBA/全部writer预检→办公室prepare→维护围栏/停写/新备份/一次183→双后端及客户静态切换→全部后检/恢复原事件与cron→enable-access→用户登记站点、真实客户/商品/采购密码→分阶段经营验收。

停接单用受管 `customer-portal-config stop-orders`（WRITES/INVOICE关闭）；单客撤权在方舟暂停授权，全面封闭用站点status或受管close。停单/关闭后检失败保留关闭配置并暂停后端，不恢复接单。保留历史订单、PI、审计、备份和必要恢复材料。配置/构建/健康检查均不能代替经营上线。
