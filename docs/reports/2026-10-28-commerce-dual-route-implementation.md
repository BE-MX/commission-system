# 方舟交易双路线：开发与隔离验收报告

日期：2026-10-28。工作区：`codex/commerce-transition`，基于main `e6b919c4`整合原本地候选的工作区快照。此报告是本次开发证据；原2026-10-04候选报告保留为历史，不替代本报告。未提交、推送、合并、部署或切换生产。

## 实现结果

实现“一份合同、两个入口、唯一正式办理路线、独立核对结果”。统一订单页复用main编辑器与权限屏障；方舟独立出库、资金应收、目录库存生产及承接使用本地领域服务。不能把小满出库创建成功当作实物发货；资金放行后仍须当前版本检验才能正式发货。小满客户维护和同步契约保留。

- 持久phase为legacy_only/transition/local_only，初始legacy_only；启动、HTTP和后台发送都核实当前phase/writer及对象办理权。生效合同固化route/epoch，普通改线只面向无事实草稿。
- 每次旧正式POST先在同一锁序中提交不可变sending claim和原业务意图；持久提交后才HTTP。未知结果、过期租约和镜像空白不会授权第二次发送。原响应及GET证据独立保存，再按当前权限、scope、epoch、nonce决定是否推进业务。
- 银行主体/真实账户域/渠道/流水与原付款双向唯一。弱身份旧款、跨路线本金、退款流水再当本金均拒绝；未确认作废保留原审计后可纠正。货款附加费与实际银行费分别守恒。
- SKU/仓库、物料和生产使用实物范围。缺可信远端仓库映射时，已映射本地试点SKU整体排除旧出库；存在试点时未知映射也拒绝。旧出库unknown或物料pending不会被“已审核”标记覆盖为新本地范围。
- 原单承接复用原Invoice、ReceiptBatch/Receipt及银行身份，核验完整付款/生产责任闭包；prepare冻结、真实七部分期初、原子activation、原epoch回传和结清依据均落地。共享P的A600+B400不能只迁移A。
- 经营统计按唯一正式身份去重，独立核对零贡献；小满水位、本地投影及未完交接共同决定完整性。来源不完整或范围滞后时阻止最终榜单/色块发布。
- 独立核对保存accepted/rejected/unknown观察及outbox；原回滚后的拒绝另记非经济诊断。导出仅含原始输入与核验映射，候选进程清除源环境、禁止HTTP、使用独立账本及执行身份。预期结果不进入候选幂等表。真实调用合同、收款、核销、批次领域服务后再导入候选回执。
- 旧订单、回款和出库原始输入有完整映射时可重放；旧出库创建/更新只重放create/ready，不伪造检验或ship。缺原代次、原header、SKU/账户/仓库/汇率/共享闭包时明确incomplete。来源原SendingClaim.id是发送代次，候选commerce_version独立，晚到旧claim不能替代新合同。
- 草稿删除归档保留合同、行、幂等与审计，避免办理权RESTRICT外键导致丢证据；旧删除/恢复与本地取消分开。客户端缓存、下载和命令按类型/route/epoch隔离；晚到响应及切页后的文件操作不会覆盖当前任务。

## 迁移与数据边界

唯一新链为207→208–225→226，原未发布174–191已重编号；main同号历史迁移不被覆盖。226为冻结DDL，安装默认不伪造writer、物理范围或银行核验。138历史迁移内容保持main，MySQL单例隐式自增的兼容修复位于Alembic局部DDL适配。完整空库链按原bootstrap、126冻结证据和Alembic执行，没有stamp/create_all冒充迁移。

MySQL使用本任务自有127.0.0.1:33079及随机schema/测试writer；各fixture结束DROP后查询确认。浏览器库使用独立SQLite模型fixture和真实router/领域服务，登录使用合成员工真实JWT及数据库角色；没有运行生产bootstrap、连接真实银行或调用小满交易。两类证据分别报告。

## 本轮验证

各行存在重叠，不将通过数简单相加。日志位于本工作区tmp，可供后续交接核对。

| 验证范围 | 本轮结果与证据 |
| --- | --- |
| 最终原生领域组合 | 433 passed、35 warnings、无skip，185.27s；`native-final-aggregate-v3.log`，41文件清单为`transition-final-backend-cases.txt`。修复实时权限/候选范围，测试前置保留原金额与一次办理断言 |
| 旧订单、队列、出库同步与删除审查 | 231 passed；`transition-legacy-final-regression-v2.log`，真实current executor/claim/不可变事实/实时授权，并发旧nonce POST0 |
| 草稿归档、级联删除与定价 | 101 passed；`transition-cascade-final.log`；后续持久删除claim专项3 passed、基础门禁/独立删除组合33 passed |
| 回款管理、恢复及协议 | 151 passed；`receipt-live-sender-legacy-regression.log`；后台原actor禁用、撤权或范围失效阻止新发送 |
| 物料、试点与期初门禁 | 88 passed；`material-pilot-review-final.log`；包含实际pending字段、未知旧出库和精确幂等重读 |
| 完整迁移、MySQL RR与隔离保护组合 | 19 passed，183.50s；`transition-final-mysql.log`。原合同/明细/媒体/付款身份、预售尾款、共享责任与并发启用均在完整链实际验证 |
| 独立核对领域/隔离进程 | 全域39 passed；最终旧路线13、权限14、observer关闭/启用1、最新标准收款/真实更新/共享付款3均passed。`shadow-original-generation-final.log`、`shadow-live-and-candidate-permissions-final.log`、`shadow-observer-off-on-original-claim-v3.log`、`shadow-original-claim-positive-final.log`；组间有重叠 |
| 前端新增/相关行为 | 41 passed，`transition-final-frontend-tests.log`；实际控制器权限、route、资金identity、请求隔离和同数值不同类型ID |
| 前端全量基线比较 | 正确VM参数、正式源码目录运行1739项：1636 passed、103 failed。103项与固定main既有失败集合完全一致，新增失败0；`frontend-canonical-delivery-vm-tests.log`及`frontend-delivery-failure-comparison.json`。未宣称全量前端全绿 |
| 前端生产构建 | 135条导航，`frontend-artifact-final-build.log`。使用自有依赖快照，不替换原node_modules链接；最终源文件与快照SHA核对 |
| Edge浏览器真实API闭环 | 7条通过，1440px与390px；相关API错误0、脚本错误0；资金ready、登记25、财务确认、取消批次共4次写入均为local接口，无旧删除/恢复POST。`transition-browser-results.json`与截图 |
| 核对回执前端拒绝 | 错run、null、损坏JSON三例，shadow POST0。`transition-browser-transport-results.json`。仅为选择任务而mock列表行，未冒称真实回执导入；服务端导入另由真实API专项验证 |
| 发布协议 | 43 passed；`transition-release-protocol-final.log`。模拟完整五阶段发布，独立模式不查询旧镜像，模式冲突先拒绝且不启timer；不表示实际安装或服务变更 |
| 编译、约定及Git | compileall、严格约定、差异空白检查通过，Alembic唯一head为226；`git_sweep.py --no-fetch`已执行。本地引用快照，不代表远端或部署状态 |

## 设计T01–T18对照

| 场景 | 已验证的实现证据与实际边界 |
| --- | --- |
| T01 唯一正式办理 | 核心route/epoch、原发送claim及资金/发货领域；错路线拒绝，原始身份复用；并发使用真实MySQL验证 |
| T02 重复/故障隔离 | 正式事务/outbox、独立进程重复执行、同键结果和候选本金1；核对滞后不改变正式结果 |
| T03 原外发未知/移交竞争 | sending claim当前读、原响应独立持久、unknown不重发、旧nonce POST0；第三方旧二进制仍须现场撤权 |
| T04 实物隔离 | 旧SKU精确映射与local/frozen拒绝、新范围前查原在途/物料pending；首期排他，不开放跨路线共同用库存 |
| T05 银行身份完整 | 弱旧款冻结账户域、真实账户别名、原本金和流水唯一、退款引用拒绝重复本金 |
| T06 资金并发与守恒 | 本地核销/冲回/退款及原跨线责任拒绝，MySQL财务并发和共享款原ID承接；不开放拆分共享本金 |
| T07 预售续接 | 完整链合同1000、首款300已抵100、历史6件、新1+3、尾批只抵200、运费按批独立且总收1041 |
| T08 独立执行/版本/拒绝 | 非经济拒绝观察、typed依赖、原claim代次/乱序、真实新增行、expected不seed候选、关闭观察时child不伪造代次 |
| T09 来源不足 | 双水位与缺来源阻止最终发布，未观察小满手工变更为覆盖不足，不能自行推断一致 |
| T10 范围与公开读取 | 库存/退货/生产本地门禁、公开库存和MCP按范围与映射去重；无真实桶映射不暴露第二份可售 |
| T11 责任闭包 | A600+B400、共享原付款/生产、prepare冻结与原子activation、晚到证据；实际第三方凭据撤权仍需现场回执 |
| T12 正式统计 | 镜像/本地同一正式订单一次计入、别名排除、对比零贡献，退款/提成关联原事件 |
| T13 实时授权 | 原/本地HTTP、后台新claim、目录、资金、质检、对比范围及撤权反例；照片/媒体与main权限保留 |
| T14 客户身份 | 本地已核验客户独立交易、当前客户范围、历史快照/旧别名保留，重复或缺命名空间映射拒绝猜测 |
| T15 页面闭环 | 统一编辑API/幂等与前端控制器，Edge实际本地出库/收款/确认/取消及移动列表；实物设备、真实期初与真实用户操作验收单独进行 |
| T16 迁移链 | 207→226唯一链、空库原bootstrap及126完整门禁、原事实保留、非法目标/未知状态拒绝 |
| T17 时间与汇率 | 北京时间零点/非东八区主机测试、原缩放650与实际6.5及历史原币保留，不用今天汇率重写旧账 |
| T18 操作与缓存 | 同数值ID类型隔离、旧入口不能发本地删除、当前验货必需、KeepAlive撤销/原请求身份及回执错run拒绝 |

该表证明实现中的机制和隔离场景，不把生产停写、现场银行/库存盘点、打印扫码硬件或真实第三方覆盖称为已验收。

## 对抗审查

独立审查及红绿证据详见[交接、出库与回款报告](2026-10-28-commerce-handover-adversarial-verification.md)。已闭合的具体缺陷包括：RR陈旧出库关联、冲回旧款误结清、原统计范围漏冻结交接、旧出库越过本地SKU、未知旧请求/物料被审核字典覆盖、新回款使用已撤权原操作人、原删除晚到证据丢失/越权推进、claim后旧nonce继续发送。

| 实现审查发现 | 修复及复核证据 |
| --- | --- |
| P1 旧出库删除仍信JWT，级联流程token延续旧scope | 每次新claim核验live角色/归属；原proof独立提交后重验epoch；3个独立删除反例绿，包含转归属和冻结后不推进tombstone |
| P1 实际旧出库update载荷没有currency/warehouse，候选可能KeyError影响正式收尾 | 原pre-read header冻结输入，缺证据转incomplete；真实plan.build载荷经独立CLI cancel/create/ready，未伪造ship |
| P2 共享旧ReceiptBatch无typed原本金来源，完整A+B仍incomplete | 原batch来源与完整闭包明确；缺一单候选本金0，完整闭包重复执行本金1 |
| P2 新增InvoiceItem被误判映射缺失 | 只认原不可变before/after与source new行，候选amend生成新ID，已有行缺ref拒绝 |
| P1 候选直接调domain未验证HTTP动作权限 | action权限清单对齐正式HTTP；14个参数验证，确认不足时不产生可用款 |
| P2 普通旧单没有统一version，晚到观察可能被当新合同 | 原order claim.id作为来源发送代次；child继承不可变accepted原代次，未观察来源为None+unavailable；off/on及晚到原请求回归 |
| P2 独立模式部署仍探测旧镜像 | 持久模式先核验，只有旧config+旧持久凭证才查镜像；原ModeFence/暂停/安装门禁保留，43个模拟发布回归与独立复核 |
| P1 产品级别名可误代替未知SKU，绕开实物排他 | 写入口仅使用精确租户+产品+SKU身份；产品级别名不能证明库存桶排他，新反例先红后绿；纯旧无试点不改变 |

另一审查者复核了旧删除实时scope、epoch变更后只保留proof、真实出库更新原header、共享原本金来源、新增行身份、原claim代次、独立候选权限，以及新Workbench文件导入与发布/目录门禁。均有实现与新增反例复核；不只引用设计级审查或旧39项测试。最终原生组合补闭合目录和提成管理实时权限，以及生产供货候选的当前客户范围；实际红绿和433项完整组合见[原生回归报告](2026-10-28-commerce-native-regression-verification.md)。

发布探测的最后修复保留原ModeFence、永久floor和五阶段校验，仅让受保护独立模式不依赖旧交易镜像；43项是模拟远端执行协议，未运行任何真实systemctl。

提成归属配置沿用既有管理权限合同：`customer:write`用于编辑归属配置，`commission:write`用于管理提成批次；管理集合不按当前CustomerAssignment缩小。它与本次订单、资金和生产候选的当前客户范围是不同权限边界。本次补实时撤权，没有擅自重定义管理范围。

## 交付与运行

源码、迁移、导航、API说明、数据库说明、运行手册和handoff留在当前任务分支的未提交修改中。对比默认关闭，正式策略安装为legacy_only；没有给生产写入、迁移或发布授权。

后续按[运行手册](../runbook.md)核实真实writer/银行/资源证据，通过既有部署入口发布后做业务验收。无法约束旧writer、小满手工交易或共享实物时，只开放隔离核对，不开启真实试点。缺映射的历史非标/预售对比输入保留incomplete，正式预售/历史承接则已有独立领域和完整链验证；不能把provider创建响应当作物理发货凭证。

## 最终检查记录

当前工作区最终版本已完成开发与专项验证，独立审查无未关闭的实质P1/P2。433项原生组合、231项旧路线、19项完整链/MySQL及隔离保护、浏览器7路径与回执拒绝3例、发布协议43项和相关前端41项均有上述实际结果；各组存在重叠。前端全量103项既有失败如上保留，未伪称全绿。

`transition-final-compile.log`为空错误日志，严格约定日志末行通过；工作区及暂存区空白检查使用Windows CRLF口径均exit0（`transition-final-diff-check.log`），冲突索引为空，Alembic唯一head226。Git巡检已完成no-fetch本地快照，未自动处理其他分支、stash或主目录改动。1357个前端文件与自有构建快照SHA一致，导航manifest为135项。

浏览器fixture进程已停止，合成access-token文件已移除；保留测试脚本、构建依赖快照、失败定位及最终通过日志、原候选不可变备份用于复核/恢复。未启用生产对比worker、修改真实phase、执行真实systemctl或运行生产迁移。
