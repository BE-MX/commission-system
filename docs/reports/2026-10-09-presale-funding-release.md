# 预售预付资金与当批发货发布记录

## 规则与影响

- 定金只在人工确认最后一批时扣；预付货款从本批开始支付商品、包装、手续费与运费。剩余余额保留，不自动退款或冲销。
- 每批只编辑当批明细，保留历史商品原数量/金额/UID、结算快照及出库关联；当前导出与当前金额一致。已到账回款的金额、实际银行手续费、日期及凭证不随编辑重算。
- V2补款使用实际银行手续费，V1旧报价与原请求恢复保持原语义；重复提交、跨批占额、取消释放及释放后用途更正都由当前授权和锁校验。
- Veronika981的1062回款USD1077已确认为预付货款，本批627商品+38运费共665，应剩412。生产原批已通过受审计服务升级，原回款改为预付货款，665已占额、412可用；状态1待出库已生成且打印列表/数据核验通过。

## 验证证据

- 汇总受影响后端408 passed；最终旧批升级专项54 passed，独立审查定向7 passed，包含重叠用例，不把数量相加冒充独立总数。179迁移只加七列；180只新增升级审计表，MySQL离线DDL、唯一键/FK/JSON、单head与拒绝删除历史的降级检查通过。
- 独立MySQL8.4.6、fresh目录、127.0.0.1随机端口及随机凭据，最终六项真实并发通过。两个线程的锁争用经performance_schema.data_lock_waits观测；赢家占665、余额412，旧RR快照等待后读取当前占额，取消释放/用途纠错/原key恢复通过。仅有限相关生产schema，未宣称完整生产迁移重放。进程已正常停止；清理data/temp被工具策略拦截，目录与验证证据保留。
- Node39通过；真实Vue/Element Plus合成API在1440/390宽度覆盖用途纠错后自动刷新与版本、数量提示、末批使报价失效、原请求末批/数量冻结、可用余额/定金/待生效分列。既有资金风险页面在1440/390/320宽度通过；无真实业务HTTP写入。
- 前端生产build、覆盖所有新增文件的严格约定及diff检查通过；保留原有chunk及auth混合导入提示。独立财务及历史/页面审查发现的边界均已修复复核。

## 小满专用实测与限制

- `ARK-PRESALE-ROLLING-20261009-155340`：原0.03回款保持，订单由0.03降0.01，同SKU追加新UID而旧UID与状态1待出库关联保留。
- 已删除待出库并核验可用库存恢复9923、实际9999；亮哥删除receipt105841964279070后，两次完整活动列表证明移除，再清理测试订单和客户。最终durable journal为cleanup_complete。
- 无产品初始订单、新增回款直接超过当期明细、实际出库之后缩减历史数量未实测。亮哥选择暂不追加测试并保留限制；未新增正式租户测试对象，不改手续费或虚构商品绕过供应商限制。

## 发布

- 应用候选 `890c59927f3666f7e25d0f9ec028669f0f24f7f5` 已合并推送；办公室统一入口先 prepare 再 publish，均 exit0，release ID `923e5e9407024a8989206f09b8b38e90`，范围 `office-and-cloud`，deferred 为空。
- 共享 schema 为 `180_settlement_funding_amendment`；办公室、北京 health 均 `ok/database=connected`。北京 HEAD 精确匹配应用候选，backend/config 无差异；两主域入口与 main、InvoiceManage JS/CSS 共10项 SHA256 匹配。Scheduler 办公室 true / 北京 false，出库轮询原 active/enabled 和邮件 worker 原 inactive/MainPID0 基线保留。主目录原24项修改完整保留。证据在主目录 `.deploy_state/presale-prepayment/verification-summary.json`。
- Veronika 原批升级首次被 `ReceiptIndexNotReady` 拒绝，提交前无资金写入；回读仍是结算1 V1/awaiting_payment、Receipt1062 定金/1077/fee0/version4、无资金应用、无出库、无升级审计。现金事实哈希、原运费ID及回款ID列表不变。恢复后沿稳定请求 `veronika981_advance_upgrade_20261009` 成功提交，durable journal 为 committed；唯一 amendment1，Receipt1062 用途为 presale_advance，627 goods 与38 freight 两项 reserved，剩余可用412。原现金事实哈希、回款ID列表及运费ID始终不变。
- 诊断显示办公室时钟比独立 UTC 约慢30秒，最新小满回款时间超出当前校验上界。Windows W32Time 原 stopped/manual，已启动；原 time.windows.com 无可用数据。亮哥恢复 GameViewer SSH 后，独立 UTC 已对齐；ntp.aliyun.com 三次测得误差约0.04秒，改用该源后 resync 成功，Leap0/stratum3、同步时间18:24:40。保留原配置与校时证据，未放宽时间或资金完整性校验。自动派发在此前索引校验阶段明确失败且未POST；用原任务的现有 retry-outbound 服务核查编号不存在、记录审计后，在北京同候选/共享库仅派发该ID一次，不开启另一调度或扫全队列。
- 原 ShipmentOutbound1 已核验为 pending_remote，远端105842096302467、编号 `2026.Veronika赊销-01`、状态1，5行数量4/3/5/5/1。正常每分钟镜像已收敛到record93262；实际打印列表精确订单查询返回1行、can_print=true，print-data返回5行/18件（打印排序1/5/5/4/3）。原运费单105841919266053与现金事实不变，无新回款、运费回款或运费出库，未调用实际出库确认。原invoice_no保留用于已有身份，业务order_type为presale。最终本地/远端/打印证据为主目录 `.deploy_state/presale-prepayment/veronika-status.json`、`veronika-remote-after.json`，原before文件保留。
