# 运费退款发布的出库激活恢复控制器

本次原应用版本 `b817650a69a6865886c9f4d7a0c61bc1ec9ec807`，release ID `6d6683095e704b818c90d3db43b1c57d`。schema 246→247 已执行，两个后端、两个路由及五个静态站已完成，最后出库激活因 `Outbound mode control cannot be confirmed` 失败；迁移日志为 `upgraded`，出库回执为 `installed_paused`，原 timer 基线 active/enabled。

现场只读确认 timer inactive/disabled、service MainPID0，Node/mysql2 读得连接 ID 为 number、命名锁 owner 为 null、mode legacy、schema247。同一原部署 `ModeFence` 后续 ready/check/released 全部通过。这只能证明当前门禁可用，原失败时的锁/协议根因仍未确定。

在既有 `--recover-outbound-activation` 入口增加唯一受审映射：本次完整 revision、release ID、精确原 schema246 和 pending247。计划仍仅接受 revision、release_id、journal_sha256。保留历史204映射，不支持任意版本参数恢复。

恢复前验证原日志摘要、九项已完成记录、真实代码/应用运行参数/健康、schema、五站及办公室静态摘要、全部 writer 暂停状态、原出库制品/模式/数据库指纹及调度基线。原恢复尝试回执存在时拒绝重发。恢复只续行原出库激活与核验、关联 writer、邮件 Worker 和维护调度；不重复 DDL、应用启动、静态切换或退款业务操作，不修改模式或伪造原成功记录。

31 项恢复测试通过，覆盖两个受审检查点及错版本、release 混配、迁移链、已激活状态、缺失阶段和原日志摘要。增量约定与 diff 检查通过；独立审查无阻断。

执行时使用固定新控制器候选的 `deploy/deploy.bat --live-root D:/commission-system --revision <controller SHA> --recover-outbound-activation <plan> --prepare-only`，准备核验后去掉 prepare-only。原应用版本与 release ID 保持不变。实际执行结果及线上金额验收见后续发布报告；本文件不声明恢复已经执行成功。

## 首次恢复失败后的受审接续

控制器 `1a7c9897` 的 prepare 通过，activate 再次在原模式门禁失败；既有恢复回执保留为 started，未启动轮询器。后续从办公室发布机重现时，诊断已确认是在 ready 阶段 GET_LOCK 返回 0，owner 为北京后端连接。只读非阻塞线程栈显示一笔真实 `sync_invoice → stock_reservations.fenced → outbound_followup → linked_outbound_service._read_details` 请求正在核对关联出库，不能终止它来腾锁。首次原发布未保存细分错误，不据后续证据追称首次失败也已完全定位。

仅允许再接续这对已检查原始字节摘要：journal `b7db2d80e052a0676f6dc5eb2b2b1ab2c7dca4026004692ea0fd248b530c197f`，旧恢复 receipt `74b17012960bbfae6d1343a5f37b89acced0af2fd36da83443efc4dcbe66c206`。除了原检查点，还要求旧 receipt 的 original/migration 与当前记录一致、阶段停在 outbound-activate、原远端 installed_paused。其余既有尝试仍阻断。

prepare-only 不写重试凭据。正式接续先以独占创建归档旧 journal/receipt 的原始字节，再写带 previous_receipt_sha256 的新尝试；同名档案内容不一致或符号链接均阻断。新尝试失败后摘要改变，不能自动套用本次白名单继续重放。原出库制品和数据库门禁保持不变，等待线上请求自然释放锁。

39 项恢复测试通过；独立审查无阻断。最终恢复结果仍以发布后的实际读回为准。
