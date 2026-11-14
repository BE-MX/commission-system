# Rina WhatsApp 联系人名称与手机号缺失

## 结论与交付状态

用户明确授权办公室连接器发布、补全及 Rina 实际显示核验。修复 `5c6e2704040ff14e5ae704c40cbbf83fca63105a` 已经受管入口发布成功，账号恢复 connected，补全版本为 1。办公室只重启 WhatsAppConnector，未重启后端、未迁移数据库；schema 仍为 262。本轮按用户授权将修复与发布记录合入开发 `main` 并推送 `origin`；此次 Git 交付不重复部署，办公室实际发布版本仍为 `5c6e2704`。

2026-11-14 10:30 左右（UTC+8），Rina 活跃账号共有 103 个非群未关联会话，45 个缺名称、101 个缺手机号。连接器已有 318 条联系人资料（139 条 LID、139 条 PN）、266 条带名称、102 个会话有双向一致 auth 映射。该扫码账号 `registered=false` 但存在 `me.id`，服务正常运行，不能以 registered=false 判未绑定。

初步只按可找到的名称与映射统计，最多可补 21 个名称和 100 个号码；执行完整冲突隔离后，**实际内存试运行安全补回 19 个名称、94 个号码**，剩余 26 个名称、7 个号码缺失。差额来自身份冲突保护，另有一个异常会话 ID。不能据此猜测真实号码或承诺所有历史身份可恢复。

## 根因

- 原连接器仅按联系人原始 ID 查询，手机号 PN 与会话隐私 ID LID 未连接；另漏接独立映射事件和历史映射数组。
- 锁定的 Baileys `7.0.0-rc14` 在 history processor 先持久化映射，但 event buffer 重建事件时丢失 `lidPnMappings`。仅新增数组读取仍不足，必须检查同账号加密 auth store 中相互一致的 forward/reverse pair。
- 原名称投影遗漏部分 `verifiedName/username` 路径，部分联系人更新会把已有字段覆盖为空；入站消息昵称未用作空标题补充。Rina 实际入站消息中没有昵称，此次恢复名称来自已存联系人，不能把消息 fallback 说成现场主因。
- rc14 出站 companion 消息的备用地址可能是销售本人号码，不能直接用来建立客户别名。当前修复只认可必要的双向证据，排除本号，保留不确定项。

## 修复行为

统一接收明确 PN/LID 元数据；只通过受信对应关系共享名字、号码。名称优先保存名、昵称、企业名、username，再以有效入站私聊昵称补空。映射在账号内加密持久化，原 conversation/message UID 和方舟客户关联保持不变。

已有登录凭据启动时校验实时授权和租约后，仅补已有会话缺失的元数据；先完成映射冲突校验，再发布每个会话，保留所有原有非空名称和号码；新扫码跳过回填，普通扫码以 `me.id` 识别。消息只扫描一次，不逐聊天重复遍历。变更沿现有 sequence feed 下发；成功标记版本，重跑幂等。暂停/撤销优先，不复活已删除聊天，运行中到达的新映射仍可被应用。

双向映射冲突时隔离相关 alias 并记录 metadata gap，其余采集继续。批内冲突不得首次发布其中任意一人的资料；保留 PN 会话自身可确定的号码。此前已经发布的旧字段不自动清空，需另案核验；本修复没有改变后端空值保留契约。

## 验证与证据

- 新增 16 个回归场景，最初 6 项在旧实现全部失败，修复后全部通过。涵盖真实 rc14 event buffer、普通 QR 凭据形态、PN/LID 双向补全、手机号不猜测、自己的号码/群昵称排除、冲突隔离及同批原子性、暂停竞态、回填幂等、账号隔离、消息与凭据保留。
- 连接器完整测试 **77/77 通过**（`node --test --test-concurrency=1 services/whatsapp-connector/test/*.test.mjs`），串行运行避免既有 30/40 毫秒计时测试受并行 CPU 竞争干扰。并行首次运行出现一项定时测试失败，单文件通过；未弱化其断言或删除测试。`npm run check`、`git diff --check` 和增量 `check_conventions.py` 通过；无前端或数据库 schema 修改，不运行无关构建或迁移。
- 内存试运行仅以 SQLite `readOnly:true`、`query_only`、读事务读取生产账号，复制到进程内 `:memory:` 数据库，执行本次真实 Projector 源码，无第二连接器 socket、无生产写入。耗时约 1.09 秒；94 条会话投影变化，原 103 个会话身份全部不变，已有非空名称和号码均未替换，消息和加密凭据逐项不变，二次运行幂等；18 条 alias 被保守隔离。对应源码 SHA256：`ceb65b79ee946b740768a67a18968fa9f3460f260083d81abe2e954cd8f01b57`。
- 过程材料：工作区 `.deploy_state/rina-whatsapp-contact-20261114/`（只读审计脚本、内存试运行脚本和汇总结果）；测试日志在 `tmp/whatsapp-contact-metadata/`。诊断输出只含统计和布尔判据，不导出聊天正文、联系人姓名、手机号、token 或凭据。
- 独立审查发现的事件缓冲、本人地址、QR 门槛、批内冲突和暂停竞态问题均已修复并补覆盖。最后局部 PN 直接号码回归也已修复验证。Git 巡检 `--no-fetch` 已执行，为本地快照，未处理其他工作区或分支。

## 上线边界

办公室 NSSM `WhatsAppConnector` 是该账号唯一连接器，工作目录 `D:/commission-system/services/whatsapp-connector`。管理 SSH 端口 2224 本次恢复后已连通。发布前只读确认办公室 Git 为 `24d2cb6f`，服务 Running。上线必须走项目 `deploy/deploy.bat` 指定入口，需覆盖此生产发布的授权，先备份状态并保留回滚引用；部署会重启共享连接器，其他已绑定账号也会暂时重连并按同样规则补元数据。

发布后已按账号核对实际缺失数、客户关联、原消息内容及前端显示。上述 19/94 为发布前内存试运行，不等同于运行后的全部变化；最终结果见下节。未申请新的扫码、代发消息、修改授权或建立客户关联。

## 本次发布准备

用户已明确授权发布和补全并核对Rina本人显示。新增受限 `--whatsapp-connector-only` 入口，保持默认全量发布与本次范围分离。部署相关46项隔离测试通过；独立审查指出的范围、回执和提前失败回滚问题已修复，并验证备份失败与健康失败均能恢复旧连接器，不修改CommissionSystem配置或启停后端。最终上线结果如下。

## 生产发布与 Rina 实际显示验收（2026-11-14）

- 经 `deploy/deploy.bat --whatsapp-connector-only <baseline> --live-root D:/commission-system --revision <candidate> --no-pull` 完成预检和正式切换；回执 `scope=office-whatsapp-connector,status=succeeded`，基线 `24d2cb6f`，候选 `5c6e2704`。办公室 Git checkout 与服务源码 SHA256 对应已验证候选，后端代码和服务配置未更改，北京未发布。
- 停止连接器后完成 SQLite 一致性备份与 `integrity_check`，受限 ACL 备份保留在办公室 `.deploy_state/whatsapp-connector-backups/5c6e2704040ff14e5ae704c40cbbf83fca63105a/`；完整回执和备份摘要见本地 `final-release-state.json`。切换后连接器鉴权健康正常，WhatsAppConnector 与 CommissionSystem 均 Running，Rina `active/connected`、`needs_user_action=false`。
- 生产连接器、后端只读统计与 Rina 本人 Chrome 页面相互一致：103 个未关联非群会话；缺名称从 45 降至 25，缺号码从 101 降至 7，即当前 78 个有名称、96 个有号码。对照稳定 conversation_uid，共 20 个原空名称和 94 个原空号码已填入。发布前内存试运行只预计补名称 19 个，生产重连后还处理了新消息及联系人资料，因此不能把这 20 个全部归为启动回填。
- 后端 103 个原 conversation_uid 全部保留，客户关联指纹未变（原来为空）。启动回填仅补空，但恢复实时联系人同步后另有 2 个原非空名称更新；逐项确认新名称等于可靠 alias 对应联系人资料，alias 未冲突，原非空号码未变。不能声称整个发布观察期间所有已有名称均未变。
- 连接器备份对照：发布前 8,385 条原消息 ID 与解密 payload 逐项完全保留；发布后 8,386 条，正常新增 1 条消息。数据库和浏览器核验未发送消息或进行客户关联写入。
- Computer Use 使用 `gpt-6.1-terra/xhigh`，通过现有合法登录确认 Rina / 张心茹，检查真实 `https://leshine.cloud/client-desk` 的“仅我的私海 → 未关联会话”，按 100 条第一页及 3 条末页核对：25 个通用标题“WhatsApp 会话”、7 个“号码未同步”。截图位于证据目录 `ui/before.jpg`、`ui/after-top.jpg`、`ui/after-page2.jpg`，未使用模拟页面。
- 剩余缺失项缺少可安全使用的名称/号码或存在身份冲突，保持原状，不按昵称猜测归属。后续同一账号、同一会话的新消息仍沿既有客户关联归属；本次补元数据不合并独立会话，也不自动创建客户关联。
- 证据目录 `.deploy_state/rina-whatsapp-contact-20261114/` 保留 `activation.log`、`before-production.json`、`after-production.json`、`connector-after.json`、`final-release-state.json` 及 UI 截图；生产临时核验脚本已清理，备份和候选保留作为恢复材料。收尾 Git 巡检为 `--no-fetch` 本地快照。
- 本次 Git 交付包含修复提交 `5c6e2704` 与生产验收记录；保留办公室备份和发布版本，不重新执行部署。证据归档至主工作区同名 `.deploy_state/rina-whatsapp-contact-20261114/`，供任务 worktree 清理后继续核验。
