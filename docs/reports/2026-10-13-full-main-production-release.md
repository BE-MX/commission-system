# 最新 main 完整生产发布

发布依据：用户授权根据远端所有最新合并代码进行生产部署。固定远端基点为 origin/main 77622edf；候选保留当前生产 f5269d9d 的门户密码登录、原迁移和部署恢复保护，再汇入全部最新 main。主目录原有27处修改不纳入候选。本文件先记录准备与验证，实际发布结果以本轮受管回执及服务读回为准。

## 准备与迁移

- 新增195_main_portal_merge，父节点为186_portal_announcement_merge和194_navigation_preferences；保留原revision，不stamp、不downgrade。从生产仅执行186_domestic_delivery、192_wa_sync_fencing、193_wa_ai_assistant、194_navigation_preferences和195。186变更原请求类型CHECK，统一入口冻结登记writer后执行一次DDL。
- 只读现场：办公室和北京f5269d9d、共享库186_portal_announcement_merge、MySQL8.0.30；原CHECK存在，用户ID unsigned，账号及数据库collation均utf8mb4_unicode_ci。独立数据库事件不涉及本次内贸、WhatsApp、导航DDL域；镜像cron与无关服务保持原配置。
- Connector Node24.15.0；旧账号error1/revoked3、消息0。补齐受保护外部加密key与Ark地址，保留原NSSM环境备份，未重绑账号、未注销旧设备。首次环境数组拼接读回异常已核查后复用同一密钥修正，没有轮换或重发业务请求。密钥与SQLite/业务备份分开保管，不进入代码或回执。
- 新增准备阶段实际候选启动预检，使用NSSM Node及真实环境优先级，临时SQLite、随机端口、禁止账户恢复。缺配置在停机和DDL前阻断。实际切换仍按deploy/deploy.bat入口执行，不手动启动应用。

## 验证

- 受影响后端：898 passed、2 skipped，覆盖生产门户、内贸交付、预售信用批、WhatsApp同步/助手及导航。首次缺reportlab已使用本地隔离target依赖修正，不改主Python环境。
- 部署全套：805 passed、18 skipped、1失败。失败为storage-routing的mock StopIteration，未修改main相同测试也失败；本次不执行该专项、不改测试掩盖。最终迁移/依赖/环境优先级专项28 passed。
- 真实隔离MySQL8.4.6：生产186路径原DDL升级1 passed，保留合成密码、原消息、历史账号旧provider/待授权、非QR payload和原收款请求；重复upgrade不重跑。此为合成历史锚点，不是生产数据恢复演练。
- 前端逻辑52 passed；Connector41 passed；真实入口准备预检4 passed。严格约定仍为原17项发票UI基线问题。独立复审确认195唯一head、门户保留和DDL后拒绝自动降级；环境优先级意见已修正并测试。

## 发布范围与边界

统一入口处理办公室/北京后端、办公室Connector、两地主站、PM、素材、采购门户、北京出库轮询器及邮件Worker；保留既有邮件禁用状态和出库单活状态。独立研究Agent的MCP/Skill更新需同一发布目标下核验专用入口，heartbeat保持0m，不自动消耗业务队列。

发布证据目录：主目录及办公室 `.deploy_state/full-main-release-20261013/`，含固定候选、准备/切换日志、版本/schema/服务读回和恢复资料。健康/API只读验收不代表已替用户重绑WhatsApp、执行付费模型研究或真实单据写入。

## 实际应用发布与读回

生产固定版本a7d39aaaffff6a9d5337ecaac60edb4f3c86fcb2，包含origin/main77622edf和原生产f5269d9d；发布身份7cc7f57a7c204e73890ad461429891bc。首次准备被快进祖先门禁拒绝，未停服务；补齐真实Git第二父后候选文件树逐字不变，重新准备成功。失败记录保留在初始目录，最终执行与证据位于full-main-release-20261013-r2。

- 办公室和北京实际HEAD均a7d39aaa，后端及Connector运行。共享库实际195_main_portal_merge，schema-writers状态completed，八张新增业务表已读回存在。没有stamp/downgrade或覆盖原密码/资金事实。
- 三个健康入口（办公室回环、leshine.work、leshine.cloud）均200/connected。真实登录身份只读读取navigation-preferences和WhatsApp账户均200；助手options无account_uid正确返回422，证明路由和输入验证，不代表已有授权账号能分析。OpenAPI已含信用批ship_first、三条内贸交付路径、五条助手路径及research_gap_v1。没有实际创建订单/出库/回款、外发聊天或付费模型调用。
- 两地主站artifact均013a00d94eadce3c240faa275d88e04ba118a952d17b470958ad7bbca8452b3a；229文件变化，各首次传输2277922字节。PM、素材及采购门户制品未变。Nginx真实HTTPS index摘要由统一入口核验。
- Baileys受保护/health实际200。四个历史账号仍旧provider/pending，消息仍0；旧认证目录保留，没有自动转账号或扫码。持有人后续需重新绑定并明确正文/AI外发授权。
- 出库release_confirmed=true、legacy和原active/enabled timer保持；邮件服务仍inactive/disabled，没有为发布开启发送。publish-current/success均绑定本轮revision，deferred=[]。统一入口最终exit_code=0；静态资源保留status=succeeded，办公室及两主站均completed，保留当前及两份回滚备份与七日资源；最终退出及保留回执已归档。

## 独立销售研究Agent追加更新（已完成）

独立Agent已通过统一专用入口更新至3c7448cc，实际active/enabled、原MiMo/key不变、RPC及真实MCP只读契约通过、heartbeat0m。task251已按research_gap_v1完成，旧Run267取消保留、新Run268完成、正式档案/事实不变。主平台发布时曾因该任务running状态阻挡；用户随后明确授权核验收尾后，才完成此追加更新。详见[追加更新记录](2026-10-13-sales-agent-upgrade.md)。

上述生产部署阶段没有另行推送origin，当时主线为77622edf。用户随后明确授权将本次保留的迁移历史和Agent部署修复合并回main并推送；主线交付收录183/186门户历史、195双父合并节点及已验证的部署修复，保留主目录已有修改。不得用194代码直接覆盖195数据库。本次Git交付不再次部署，生产主平台仍为a7d39aaa，专用Agent仍为3c7448cc。
