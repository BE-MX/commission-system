# 附件路由审计与内贸充值修复

## 当前结论

2026-10-10 现场核对：内贸充值凭证已保存到共享 COS，`.cloud` 仍使用本地文件时期的 `.work → 办公室` 转发。此次候选取消这两个内贸 API 的跨地域中转，关闭两站请求和响应缓冲，保持原有鉴权、幂等和审核逻辑。代码、隔离回归与两站准备预检完成，**尚未激活生产路由**。应急缓存清理及匿名上传通路恢复见[故障记录](2026-10-10-domestic-recharge-disk-incident.md)。

其他附件域发现两类同源候选遗留：回款、设计生图仍将整个模块转到办公室，虽然文件服务已支持共享 COS。出货则仍有原件落盘与本实例异步上传的真实依赖，不能直接撤去转发。下表区分对象存储和 API 执行归属，不将所有办公室 API 认定为遗留。

## 检查范围与结果

核对北京、新加坡实际启用 Nginx location、upstream、请求限制和 buffering；与仓库上传服务、队列、签名、COS 和专项配置逐项比对。主站两个 server、北京平板 IP、客户素材独立域、PM、hair/video 及公开文件规则均纳入。简化快照保存在本任务 `.deploy_state/attachment-routing-audit/{cloud,work}-locations.json`；没有把完整配置或凭据写入报告。

| 功能 / 路径 | 现场路由 | 判断与处理 |
| --- | --- | --- |
| 内贸充值提交、私有凭证读取 | cloud → 新加坡 → 办公室；work → 办公室 | 已确认遗留。本次候选 cloud 直接北京 `8001`，work 保持办公室 `8002`；共同读取 COS。 |
| 回款 `/api/receipts` 整模块 | cloud → 新加坡 → 办公室 | 有解除文件归属限制的基础。`attachments.py` 同步写 COS；北京现场 `storage_proxy.origin()` 为禁用。整模块还含财务控制与小满发送，需验证两地版本、schema、租户和财务配置、历史凭证及签名/权限。办公室 Scheduler 保持单活；本次保留路由。 |
| 设计生图 `/api/design-image` 整模块 | cloud → 新加坡 → 办公室 | 原件、缩略图已经同步 COS；生成队列持久化到共享 DB，不要求 API 与 worker 同机。但参考文档解析会在 API 实例启动子进程，需验证北京转换依赖、全部历史原件/缩略图、签名与缓存。现场有 `ARK DESIGN IMAGE ROUTING` 块，仓库未找到独立受管模板/部署入口；后续应纳管后切换。 |
| 出货检验照片、视频、工位及模块 API | cloud → 新加坡 → 办公室 | 仍有真实依赖：原件先 fsync，业务事务登记 transfer，由 `source_instance` 对应 worker 上传。其他实例读取未 ready 原件可能 503。未来直北京需验证实例 ID、原件盘、容量、worker、QR 密钥与待同步跨入口访问；当前保留。 |
| 素材上传/版本、培训文件、售后证据/SOP、设计预约附件、内贸参考图、客户经营产品图/参考图 | cloud → 北京；work → 原业务后端 | 没发现 cloud 绕办公室的同类专项。素材 `501m`、培训 `301m`、其余各自既有上限和流式请求规则保留。 |
| 展会上传/场景图/照片/色板、名片附件、知识库资源、销售洞察附件 | cloud → 北京；work → 原业务后端 | 没发现同类跨地域遗留；仍需遵守各领域存储/权限规则。短期展会 pending/预览按原实例读取，不等同于耐久 COS 原件。 |
| 客户素材 `/api/customer-media/` | cloud → 北京；work `^~` → 北京 | 已是正确归属。work 中旧的上传 regex 被更高优先级 `^~` 覆盖，不是实际办公室中转。 |
| 色块 `/api/colorwork/` | 两入口均北京 | 已正确。保持既有网关、分片和完成幂等契约。 |
| 公开 `/uploads/`、hair 资源、video 资源 | 耐久命名空间 → 北京；展会短期文件保留原实例 | 未发现本次充值式中转。私有凭证不能改走这些公开路径。 |
| PM 材料版本 | 主站 cloud → 北京；`pm.leshine.work` → 办公室 | PM 独立域明确保留外网 1MiB / 前端 512KiB 限制，以避免慢隧道拖垮全站，LAN 入口承接大文件。COS 不自动消除隧道上传问题；版本差异处理还使用本进程 BackgroundTasks、PM 身份/文件 HMAC。此限制是既有策略，未误当本次路由缺陷。 |
| 北京平板 IP API | 直接北京 `8001` | 未设充值/回款/设计/出货的办公室专项，不在本次主域切换范围。 |

另外，work 的 `customer-image/public/logo` 和 `mini/shipping-inspection/photos` 精确 location 优先于通用上传规则，仍采用默认请求 buffering；这是新加坡磁盘容量的相关风险，不是 cloud 跨地域归属遗留。受管部署脚本显式保留旧照片块；后续调整应先纳管精确规则，验证小程序与办公室上传，不能靠更后的通用正则覆盖。此次不擅自扩大到其他功能的生产切换。

## 线上只读证据

- 北京当前 `COS_INSTANCE_ID=beijing`，21 个领域启用并纳管，COS worker 已启用。应用是 `ark-backend`、`ubuntu`、端口 8001，当前 PID 2740362；配置和相关代码早于该进程启动。
- 充值专用预检以当前运行服务的环境和用户执行。显式 `START TRANSACTION READ ONLY` 查询历史凭证，79 个唯一键全部 COS HEAD 通过，抽样三个下载并通过 SHA256 校验；本机容量预算下缓存可写。没有业务 DB 或 COS PUT/DELETE。
- 只读 transfer 汇总：办公室素材 ready 30560；出货检验 ready 4834、deleted 60，没有 pending/running；色块旧队列 deleted 868。当前已 ready 不意味着未来新上传没有跨实例 pending 窗口。
- 北京 `receipt.storage_proxy.origin()` 有效值为空，已因 `receipt-proofs` 纳管关闭旧文件代理。没有验证两地 OKKI/财务运行配置完全一致，未通过真实回款或设计任务进行探活。

## 本次实现与验证

修改仅限两个内贸专项 location 及其安全准备/激活脚本；北京直连本机、原用户 Host/Authorization 和完整 URI 保留，20MiB 业务文件上限配 21MiB 表单上限，上传/下载超时 300 秒，无缓存、无 upstream 自动重试。没有修改充值金额、审核、余额或账本业务实现。

部署器在准备和激活时验证当前服务身份、启动时配置和 COS 历史数据；检查后配置漂移则拒绝切换，reload 失败遇到外部变更也拒绝覆盖并保留备份。语法检查使用隔离临时目录，不触碰正式 Nginx temp 权限。两站独立回执保留部分成功情况。

- `pytest deploy/tests/test_voucher_routing.py -q`：38 passed。覆盖匹配范围、其他附件规则完整保留、幂等渲染、服务身份/启动时间解析与拒绝、新配置/服务误判、COS 未就绪、激活漂移及回滚并发修改。
- 后端 `test_domestic_review_flow.py`、`test_cos_object_store.py`、`test_domestic_request_notifications.py`：37 passed，2 项既有 SQLAlchemy 弃用警告。使用隔离 SQLite 和模拟 COS SDK；通过真实存储适配器验证上传后只生成 pending、余额/账本不变，切换实例缓存且无原本地文件仍能读同一凭证，同 request_id 仅一申请，其他用户读取 404。
- 最新 `deploy.bat --voucher-routing-only --prepare-only`：exit 0，两站 candidate 语法通过，北京 79 HEAD / 3 SHA256 下载通过。未 reload 或切换正式配置。
- 扩大存储路由回归 81 passed / 1 failed；既有 `test_bad_public_route_rolls_back` 失败：未修改的测试只准备两次 mock 回执，原实现重试多次触发 StopIteration。记录为无关基线失败，不以删断言或改无关实现掩盖。
- 增量约定和 diff 检查通过；10:26 `git_sweep.py --no-fetch` exit 0，任务树 10 修改 / 2 未跟踪，主目录其他代理内容保留。巡检仅本地快照，无 push/merge。

HEAD/GET 预检和模拟上传不代表生产 COS PUT 或 20MiB 满上限上传已经实测；未为验证创建真实资金申请。独立 agent 最后复核未发现阻断本次修复的 P1/P2，部署摘要保护不能替代所有工具之间的原子文件锁。

## 待激活范围

使用当前任务工作树中的统一入口 `deploy\deploy.bat --voucher-routing-only`，只激活新加坡和北京两站内贸充值提交/凭证读取规则；不发布应用、迁移、调整余额、改变其他附件域或启动 Scheduler。生产切换须有该动作的明确授权；现有缓存清理批准只覆盖缓存清理。

切换后核对配置实际 upstream、健康、匿名大请求到达鉴权及新错误日志，再由用户正常业务提交核实 pending、审核前余额不变、私有凭证可读。回款/设计作为后续逐域迁移候选，出货保留原实例耐久转存依赖，不将审计结果说成已全量修复。
