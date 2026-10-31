# 客户门户地址、价格与订单处理体验

实现分支 `codex/portal-customer-settings`；2026-10-28 亮哥授权提交、合并 main 并推送 origin。生产部署不在本次范围，未连接共享数据库写入；迁移由部署入口执行。

## 操作与数据边界

- 方舟「客户下单门户 → 客户访问 → 管理」增加客户地址和商品价格入口。亮哥已确认地址采用方舟自有客户资料层，不回写只读 `lsordertest.customer_info`。
- 保存地址落在 `ark_invoice_customer_profiles`，与客户门户 Delivery details、发票新建默认资料共用；已有订单/报价快照不改。缺省带出账号旧资料/最近发票资料；历史自由文本地址不猜拆城市和国家。
- 商品价格表展示标准价，支持选中多项批量填写，USD最多4位小数。只保存修改项；清空恢复现有客户定价规则。后台验证当前客户已授权商品、权限、归属和版本，原子保存并使旧报价失效；报价和提交重新验证含专属价的指纹。
- 缺货门槛按销售单位：genius weft与其它30；tape hair / k tape / nano tape / i tape为200；butterfly weft为5。严格低于门槛缺货，等于门槛仍可售。已有产品族和继承规格通过212迁移更新；独立SKU安全余量保留。
- checkout地址默认收缩，非必填；允许无地址报价/提交及后续PI修订。已填字段仍校验格式。订单现有库存复查、费用确认、幂等恢复不变。
- 登录后原Logo去黄底保留黑色字形；favicon复用方舟黄色图标。
- 新订单号使用 `POR-YYYYMMDD-01`，每日独立事务流水；原订单不重编号。为避免第100单重号，流水至少两位，100起自然扩位。全局授权锁内分配，事务回滚不消耗流水。
- orders 列表和详情显示英文当前处理状态；独立标记出库证据，不能用有出库代替整单已完成。
- 验货单增加物流关联入口：先在现有物流跟踪上传确认运单，再在验货单关联。门户按自身订单→发票→精确出库→已提交且无需重新复核的验货单→未删除的已上传运单读取；只投影承运商、运单号、状态和轨迹，不返回内部员工、原始响应或图片路径。

## 迁移

`212_portal_customer_settings` 接 `211_color_measure_record_type`：客户资料新增 delivery_json/delivery_version，商品授权新增 nullable unit_price，验货单新增 nullable shipment_tracking_id 外键及独立 shipment_version（默认0，不改变验货版本）。旧价格NULL沿用既有规则，旧订单快照保留。降级禁止删列丢失业务数据。

## 验证

- 门户全套：`python -m pytest --confcutdir=tests/portal tests/portal -q`，886 passed、2 skipped。后续新增或调整范围另跑：客户资料/物流/订单投影/空地址PI/发票地址共用专项44 passed；PI修订全文件26 passed（含29/30库存边界）；MySQL迁移DDL静态编译1 passed。各组有重叠，不相加。
- 门户前端 `npm test`：147 passed，`npm run build`通过；主后台最终 `npm run build`通过，保留既有大包提示。
- 浏览器：门户1440/375，后台地址和价格1440/390均通过。覆盖默认折叠、旧地址带出、保存/回执丢失后GET核对、批选两项单次PUT、If-Match和客户切换迟到结果隔离。截图：repo/tmp/portal-customer-settings/admin；门户截图在同worktree父目录tmp/portal-customer-experience/customer。
- 独立审查修复了业务状态覆盖、验货待复核物流泄露、实时验货权限、迟到响应和PI可选地址的跨模块不一致；物流关联使用独立版本，不改变验货版本或资金。
- `check_conventions.py`增量无违规，`git diff --check`通过，`git_sweep.py --no-fetch`已运行（本地远端快照，不自动处理其它分支）。
- 全套回归发现原SQLite fixture中发票行/分组BigInteger自增不兼容、迁移head断言停在209，已按隔离测试真实类型和当前单head修正；未弱化业务断言。

所有业务测试使用无.env隔离SQLite或内存API，MySQL连接在fixture中被禁止；没有运行生产迁移或真实订单写入。构建和本地验收不代表线上生效。
