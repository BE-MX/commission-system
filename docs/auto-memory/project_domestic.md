# 内贸订单领域记忆

- 内贸订单与外贸生产平行建模，只共用工序、工艺路线和用户-工序绑定。
- 116 是停写迁移，旧版本不会维护余额账本/逐件映射，绝不能与新版本滚动混写。
- 金额以 `Decimal/Numeric(14,2)` 计算；客户余额是快照，`ark_domestic_customer_ledger` 是审计真相源。草稿不扣款，提交才扣，编辑结算差额，终止/可删除退款。
- 建单和追加明细都必须持久化客户端幂等键；追加序号从订单行的 `next_line_no` 分配，单据上限为 50 行/5000 件、单明细 2000 件。
- 件级真相源是 `ark_domestic_item_units` + `ark_domestic_report_units`；`ark_domestic_item_progress.completed_qty` 仍是查询快照。数量报工必须按 unit_no 递增选件，逐件报工必须精确校验同一件的上下游。
- 单件码前缀是 `ARK-DU`，明细流转码是 `ARK-D`，客户进度 scene 签名域是 `ARK-DT`，三者不得混用。
- 客户进度页返回完整订单，但工序必须在服务端按 `process.show_in_domestic_track` 过滤，不能只靠前端隐藏。
- 关键权限：`domestic:recharge`、`domestic_quantity_report:write`、`domestic_unit_report:write`。仅有逐件权限时进逐件模式，两者皆有/皆无保持旧数量模式兼容。
- PDA Android 客户端在 `pda-reporting/`：用主站 `/api/auth/login` 登录后直接复用 `/api/mini/domestic/*`；`get_current_mini_user` 可读取主站 JWT 的 `sub`，所以不要为 PDA 复制一套报工后端。扫描优先走键盘模拟 + Enter，广播统一 action 为 `com.leshine.pdareporting.SCAN`。键盘逐件模式可自动报 1 件（广播必须确认），数量模式必须确认；写请求失败重试必须沿用同一个、提交前持久化的 `request_id`，仅允许 HTTPS 服务地址。
- 手机/PDA 浏览器备用报工入口是 `/domestic/reporting`，用主站登录但仍调用 `/api/mini/domestic/*`。支持 HTTPS 摄像头、扫描头键盘模拟和手输；Android 6/Chrome 49 由 Vite legacy 兼容包与 CSS flex 回退兜底，摄像头 API 不可用时不能阻断扫描头。浏览器待确认提交按用户 ID 保存于 `ark_mobile_domestic_pending_v1:{user_id}`，只有明确的非鉴权 4xx 才可清除，网络/5xx 必须沿用原幂等号重试；参考原图必须逐张加载并切换即释放，避免低内存 PDA 同时解码多张大图。
