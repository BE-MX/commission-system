# 办公室公网入口：北京主通道与新加坡回退

2026-11-13 用户授权迁移。主域 `https://leshine.cloud` 指向北京154.8.205.162；`.work`保留在新加坡119.28.107.92，不将两个地址作为根域轮询负载均衡。生产版本和未完成终端事项见 `docs/handoff.md`。

## 业务归属

- 北京8001：普通业务API、内贸COS文件、通用平台 `/mcp/`。原 `/mcp/social-customer/` 等独立服务规则保持优先级。
- 北京127.0.0.1:8002经SSH直达办公室127.0.0.1:8001：回款、WhatsApp、设计图片及验货模块；验货出库列表和打印资料的北京8001例外保留。
- 办公室仍拥有原业务处理和文件同步职责。共享数据库、COS对象、Scheduler单活不迁移；接口仍执行原鉴权。Nginx禁止将业务写请求自动重试到回退通道。
- 新加坡frpc/frps与`.work`主站继续运行，PM/hair/video/outreach等独立站点不迁移或停机。销售Agent已有配置核验为cloud。

## 新通道与凭据

办公室NSSM服务`ArkOfficeBeijingTunnel`以LocalSystem自动启动，Windows OpenSSH使用独立密钥和固定北京ED25519主机密钥。文件位于`D:/commission-system/.deploy_state/office-beijing-tunnel`，每次操作核验非链接，ACL只允许SYSTEM/Administrators，拒绝权限继承；私钥不传开发机、不进Git和日志。

北京专用用户`ark-office-tunnel`，主目录`/var/lib/ark-office-tunnel`；配置`/etc/ssh/sshd_config.d/90-ark-office-tunnel.conf`。仅允许远端转发至127.0.0.1:8002监听；禁止shell/session、PTY、本地/Unix-socket转发、agent、X11、隧道设备和user rc。`sshd -t`及`sshd -T -C user=...`核验，安装前后ubuntu运维用户的有效配置必须相同。

连接包含BatchMode、IdentitiesOnly、StrictHostKeyChecking、ExitOnForwardFailure及15秒保活；NSSM重启间隔5秒。健康判据是北京实际读到办公室`/health`数据库connected，不能只看Windows服务running。

## 入口与操作顺序

从运维机该任务的已提交worktree调用统一入口；这组一次性安装命令使用本次已核验的`office-prod` SSH别名、端口2224和原固定HostKeyAlias `[127.0.0.1]:2223`。该管理通道与新业务隧道独立。部署控制源必须逐字匹配Git固定提交；不能在其他主机照抄本次管理端口。

```powershell
$env:DEPLOY_NO_PAUSE='1'
deploy/deploy.bat --office-beijing-ingress prepare
deploy/deploy.bat --office-beijing-ingress key
deploy/deploy.bat --office-beijing-ingress server
deploy/deploy.bat --office-beijing-ingress client
deploy/deploy.bat --office-beijing-ingress verify
deploy/deploy.bat --office-beijing-ingress reconnect
deploy/deploy.bat --office-beijing-ingress routes-prepare
deploy/deploy.bat --office-beijing-ingress routes-activate
deploy/deploy.bat --office-beijing-ingress receipt-config
```

`reconnect`只终止本服务唯一SSH子进程，验证NSSM自动恢复；业务切流前执行。路由激活绑定准备摘要，只改4组受管办公室路由（两server共14个上游）及新增通用MCP块。Nginx语法检查/重载失败立即恢复本次原件；并发漂移则保留备份并拒绝覆盖。半途结果先读回，不重复盲发。

`receipt-config`只将北京现有`RECEIPT_STORAGE_PROXY_URL`从work改cloud，必须新路由已激活且摘要一致。保存受限备份并标记`saved-restart-pending`；统一应用发布加载新Settings后再验证。两端receipt-proofs当前均由COS托管，该参数是非COS回退来源；办公室参数保持空，防循环保护不变。

控制回执在运维机worktree `.deploy_state/office-beijing-ingress/`；北京路由/环境备份及回执在`/home/ubuntu/commission-system/.deploy_state/office-beijing-ingress/`，目录700、环境备份600。文档/日志仅记录摘要，不输出环境内容。

## 回退与后续配置变更

```powershell
deploy/deploy.bat --office-beijing-ingress rollback
```

此命令从本任务最新已提交控制工作区执行；生产应用 e868f077 自带的旧控制器尚不识别下面的发布重排。当前Nginx必须匹配本次激活摘要，或严格等于已验证候选中两处原样 COLORWORK/MCP 块交换顺序的结果，才恢复北京原新加坡上游配置并重载。该精确重排由后续正常色块发布造成，其他字节变化仍阻断。原SG通道必须先确认健康；回退后验证实际业务路径，再视需要停新隧道，不删除密钥或业务文件。新客户端仍使用cloud，通过旧SG链路承接；无需再次迁移数据。回退失败但恢复了新配置时，状态保持activated，可在核查失败原因后重试。

后续合法Nginx变更会使该精确回退拒绝覆盖。应审查新差异后准备新的有限回退方案，不直接复制旧整份配置。receipt-config改为cloud不会形成循环：办公室仍为空，cloud在回退后按SG路由到办公室。

`receipt-cloud.conf`、`shipping-video-cloud.conf`、`whatsapp-cloud.conf`已同步新上游；设计图片规则存为`design-image-cloud.conf`并由本次迁移控制器纳管。桌面检查保留SG隧道探针并新增BJ隧道及NSSM检查。新模块仍由现有平台注册流程登记。

## 客户端验收边界

主站MCP、外部发票API、AI网关展示地址及发票审核链接改为cloud；小程序源码生产入口和PDA1.0.6默认地址同样改为cloud。旧客户端继续可用work。

用户已确认微信request/uploadFile/downloadFile合法域名包含cloud，开发者工具登录后已对本任务工作区生成预览包（442694字节）。手机扫码登录/接口、审核和正式发布仍未完成；服务器发布不替代这些步骤。PDA已有保存地址和待确认报工不自动改写，APK必须在设备端覆盖安装并按既有待确认保护处理。真实微信登录、实体PDA扫码和真实业务上传/发货没有被只读HTTP验收替代。
