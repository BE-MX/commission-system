# 客户下单门户发布接入

当前为本地实现与待启用配置。客户域名、主机归属、TLS、邮件及试点客户配置尚未确认；
`platforms.json` 只列 pending，普通发布不构建或发布客户站。本文件不构成发布授权。

## 构建与现有发布入口

客户站组件名 `frontend-portal`。确认目标并评审后，才将 pending 项移入 `static_targets`，
填入实际 `host`、`domain`、`backend_owner` 和固定静态根目录
`/var/www/ark-static/customer-orders`。不得复制其他客户门户的身份/账号或复用素材门户权限。
当前预留模板适用于同主机回环后端，跨主机代理需重新验证网络和可信代理地址。

正式动作仍走 `deploy/deploy.bat`，遵守固定候选、干净工作区、迁移、单活 writer、准备和
激活规则。已登记客户站与其他站点共享制品摘要、差异传输、损坏缓存阻断和静态切换机制。
只将主站/PM产物交给办公室静态步骤，客户站走其已登记云静态目标，避免首次发布时向
不存在的办公室目录写入。未登记时不要求发布机有 pnpm。

登记后发布机需可用 Node 与 pnpm。客户站使用其已提交的 `pnpm-lock.yaml`，执行
`pnpm install --frozen-lockfile --ignore-scripts`，再 `pnpm exec vite build --outDir <candidate>`。
依赖与构建缓存、日志和临时制品位于 `.deploy_state/`。不将 `.env`、令牌、订单数据或上传
文件放入静态制品。客户前端只调用同源API，不复制生产前端环境变量到候选。

## HTTPS 与代理边界

`nginx/customer-orders.conf.template` 是未激活模板。替换域名占位符、验证实际证书路径和
回环后端端口后，仍须在目标候选环境执行 `nginx -t` 及真实探针，按受审发布流程安装。
本轮没有 Nginx 实机语法/重载验证，也没有为域名申请证书。

- HTTP 只允许证书验证路径，其余跳转HTTPS。
- 仅 `/api/portal/v1/` 进入客户路由，其余 `/api` 返回404；员工登录与管理API仍在方舟域名。
- 覆盖 `X-Real-IP` 为TCP客户端地址，清空 `X-Forwarded-For`、`X-Forwarded-Proto`、
  `Forwarded`、`Authorization`。保留 Origin/Cookie/CSRF；不增加CORS或员工Bearer登录。
- 门户依赖原始后端TCP peer：专用服务可关闭Uvicorn代理头解析；共享服务至少须确保此
  Nginx location移除上述代理头，避免Uvicorn把peer改成公网客户IP。中间代理/CDN若加入，
  需重新验证可信链，不能直接信任任意公网X-Real-IP。
- 应用后端不得直接对公网开放。当前同机模板应将实际Nginx出口地址加入
  `PORTAL_TRUSTED_PROXY_IPS`；不能填通配或仅凭浏览器传入值判断可信。
- API no-store、禁用代理缓存/缓冲，HTML no-store，点文件拒绝；普通access日志关闭，
  邀请URL/OTP/邮件信封不可进入日志。上线前同时检查应用、CDN及错误日志是否记录敏感URL。

## 受保护配置与开通顺序

`customer-orders.env.example` 的五个开关均为false，秘密和实际业务绑定全部留空。
经复核后将必要项合入受保护的后端配置，不整文件覆盖现有 `.env`。

1. 确定客户域名/员工域名、站点码、OKKI身份namespace、可信代理地址；校验来源一致。
2. 经秘密管理渠道配置独立OTP/CSRF/邮件加密密钥和版本，配置邮件发送方/SMTP；不提交密钥。
3. 核对迁移状态。172/173已在隔离增量库验证；从历史空库重放止于126切换门禁，不能据此
   宣称完整生产升级通过。不得stamp、跳过或伪造客户数据切换批准。
4. 按B01–B07在方舟配置真实客户、业务员、目录、合同价、SKU单位、起订步长及安全余量；
   库存观测列、时区、时效和单位需用真实镜像证明。无可信库存/价格时保持不可下单。
5. 在授权的测试环境完成邀请/邮箱验证、撤权、双端下单确认/PI与下载、通知失败恢复。
   再按明确试点范围逐项打开登录、邮件、下单、建票和业务通知开关，不默认一并开启。

停止接单可先关闭 `PORTAL_WRITES_ENABLED`/`PORTAL_INVOICE_ENABLED`；需全面封闭访问时
关闭 `PORTAL_ENABLED`。开关变化不替代数据回滚，不删除已成功订单或PI。邮件开关与在途
发送分别核验；遵守现有单活调度及恢复流程。

## 本轮本地证据与未完成项

发布构建/协调/源码回归53 passed；实际Uvicorn代理peer边界3 passed。实际 pnpm11.25.0
冻结安装通过（策略校验开启，未运行依赖脚本），临时制品Vite构建29模块通过，产物与
现有客户站构建一致。首次离线安装缺策略元数据，按原命令补读注册表后通过，未绕过策略。
发布回归使用模拟进程，不等同执行远端发布或Linux原子切换；Nginx模板未实机验证。

独立审查发现并修复“首次登记门户误进入办公室静态激活”的P2，并补旧live无门户目录
回归。真实域名/TLS、客户经营配置、完整迁移基线、SMTP及生产试点仍为未满足门禁。


## 开发分支1.22执行模式启动约束

后端bootstrap在scheduler/就绪前同步建立或核对outbound-worker-v1模式，独立worker/SCHED开关；首建共享锁busy时启动拒绝并保持暂停，已有模式ON/OFF重启只读核对。数据库或模式不可确认不当作legacy。锁取得/释放不确定时废弃物理连接；关闭业务开关不删除模式或恢复旧创建。此为开发实现边界，目标调度/兼容回退、真实新旧进程、完整历史迁移及供应商/SMTP/COS与B01–B07仍须独立验收，具体实际本地测试见docs/handoff.md。


## 开发分支1.23旧Node模式读取与权限

旧Node的模式准入直接读取模式表，不能把元数据中不可见当表不存在。缺表legacy仅允许已核证171 parent且同连接版本表唯一精确值；权限不足和172/173或未知版本缺表均拒绝。部署账号需能读取模式及适用的版本证据，开发测试不自动修改现场权限。实际Node/mysql2局部函数探针不证明完整进程、Node22、历史迁移或成功切换；按mode目标timer、兼容回退及finalize/resume统一凭据仍是待完成项，不能据此恢复旧调度。具体证据见docs/handoff.md。


## 开发分支1.24模式目标与发布阶段回执

C03已按实际mode决定旧timer：v1始终disabled/inactive，初始legacy保留原四种baseline。activate/verify经专用Node/MySQLfence；legacy持锁至目标核验及待释放journal，确认释放后才成功；v1只读不争合法worker锁。独立模式下限防失败重试降级，同发布completed重试保留原baseline，local绑定模式/库/发布身份/严格bool目标与释放确认。failed_paused仅确认timer暂停，不表示业务进程排空；恢复先freeze/drain。真实systemd/cgroup、Node22、新进程接管、I79回退及I80共同成功标记仍未完成，不直接运行真实prepare/publish。实际结果只见docs/handoff.md。


## 开发分支1.25发布恢复共同凭据

受管publish、migration resume及历史159/160 finalizer现共用outbound回执/候选/实际verify核验。managed timer不再按原running记录无条件start；已知v1目标暂停，初始legacy按经核验baseline。缺receipt或仅installed_paused不能finalize，历史凭据不补造，需受审协调发布。fresh mode floor不能由历史legacy降低。共同guard失败只向受信登记目标请求pause，保留active service/字节/mode/业务事实；SSH/IO/审计/状态不明固定报未确认，不宣称已排空。success摘要含最新绑定outbound，静态后再check。当前本地替身/实际函数体证据不代表生产、真实systemd/cgroup或完整协议回退；I78/I79/I80现场门禁保持，具体终态见docs/handoff.md。


## Python回退协议探针（局部接入，不能据此启用自动回退）

rollback_protocol.py由候选脚本位置导入同候选backend Settings，使用专用AUTOCOMMIT连接只读观察UUID/schema与持久mode；legacy控制连接取得共享执行锁并贯穿窗口新读，结果未知时物理socket失效，不回池。Office/北京的changed激活前观察、失败恢复窗口guard已有接入；真实服务回退和旧制品持续协议兼容尚未核证，I92/I79/C05开放。当前不能用Health200或14项控制器测试批准自动回退、正式切换或上线。配置仍由方舟Settings维护，不手工删mode或恢复旧timer。
