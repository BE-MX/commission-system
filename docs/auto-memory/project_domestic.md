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
- 迁移 `127_domestic_route_rules` 于 2026-08-31 在全部 writer 停机且在途事务为 0 时完成生产 schema 升级；3 张新表、25 个新表字段、2 个旧表新字段、3 个唯一约束、10 个外键和全部数据库 COMMENT 已核验。
- `required` 不存规则行；`decision` 按结果编码分配具体单件；`optional` 允许下游扫码时自动跳过。跳过只改变路线资格并留审计，不计入工作量。
- 截至 2026-09-01，`domestic_route_cutover.py apply` 未在真实库执行；工艺映射、存量产品和在制明细仍未切换，业务切换必须另开停写窗口。
- 129 起订单头的 `normal/special` 字段正式改名为 `order_category`；新 `order_type` 与 `order_channel` 是两个独立的 `sys_dict` 值域，新订单必填。历史行允许两列为 `NULL` 并统一展示“未填写”，不推断、不回填，也不保留旧 `order_type=normal/special` 接口兼容。
- 头套和发片使用分离字典：头套有工艺、发长、可选网帽颜色、尺码、发型系列，只有 15厘米头套显示并保存发量；发片把工艺/尺寸合并存到 `craft`，仅再保存发长。现有自由文本和参考图发型要求继续保留。
- 普货只接受启用标准值。特单仅对当前可见属性允许下拉直接输入，新值在订单/草稿同一事务写入对应 `_special` 字典并只供特单复用；订单失败不残留。特单自定义工艺固定继承产品类型默认路线：头套“头套网帽（递针）”、发片“发片网底（递针）”。
- `domestic_attribute_cutover` 默认只做 JSON 预检，显式 `--apply` 才替换受管标准字典与标准工艺映射；必须与迁移 129 和新版应用部署处于同一停写维护窗口。命令保留 `_special` 数据且不改历史产品、订单、明细、属性或路线快照。
- 历史订单是否清空是后续独立破坏性决策；迁移 129 与属性 cutover 都不得夹带清库，执行清空前必须另行取得明确授权。
