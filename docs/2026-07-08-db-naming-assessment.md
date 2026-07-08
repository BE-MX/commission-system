# commission_db 命名规范化改造评估（2026-07-08）

> 评估依据：ORM 模型全量普查（114 张表 / 1231 个 Column 定义）、真实库 information_schema 核对（111 张基表 / 1325 列）、裸 SQL 硬编码引用面扫描、API 契约与前端耦合链扫描。四路证据全部来自实际执行的 grep 与只读 SQL，非印象判断。
> 本报告已过独立 agent 对抗性审查（判定：需小修），审查发现的 9 个问题已全部修订入文（幽灵表点名、P3 重新定级、门控方法修正、FK 字符串/引导 SQL/治理数据三类遗漏点位补入、批次表数矫正）。

## 一、结论速览

1. **最重要的事实反转：担心的字段级乱象基本不存在。** `create_time`/`update_time`/`create_user`/`is_deleted` 等旧式变体在 ORM 模型和真实库中**零命中**；时间戳字段已 100% 统一为 `created_at`（96 列）/ `updated_at`（55 列），拼写错误（udpate 类）零命中。**"每个表 create_time→created_at" 这类大规模字段重命名不需要做。**
2. **真正的乱源是表名，不是字段名**：前缀三轨并存（`ark_` 78 张 / 域前缀 `design_* dingtalk_* sys_ mcp_` / 完全裸名 `process`、`commission_batch` 等），非 `ark_` 表共 **33 张**（+未落库的 `mcp_tokens` 即 34 张）。78+33=111 与真实库账目自洽（注意 `ark_asset_tags` 在 ORM 以 `Table()` 声明、无 `__tablename__`，盘点工具必须同时扫 `Table("...")`，否则漏 1 张）。
3. **次级乱源是三个语义级不一致**：软删除三轨（`deleted_at` / `is_active` / `deleted_flag`）、操作人字段类型分裂（`created_by` 主流 Integer，tracking 却是 String(50)；governance 另用 `operator` String）、备注三轨（`remark` 13 / `notes` 3 / `comment` 3）。这些是**语义/行为差异**，不是纯改名能解决的。
4. **改名会穿透到底**：全仓 0 处 Pydantic alias、0 处「ORM 属性名≠物理列名」写法——物理列名 → ORM 属性 → schema 字段 → JSON key → 前端 prop → 排序参数六层同名焊死，无任何缓冲层。改列名 = 全链路同步改。
5. **表名硬编码引用面已摸清**：四类点位全部有清单（附录 B）——16 个文件约 90~100 个裸 SQL 点位（stock 域 8 文件最密集）、ORM `ForeignKey("表名.列")` 字符串 4 处文件、2 个引导 SQL 死文件、`data_concepts` 表内登记的物理表名数据。
6. **推荐策略：规范先行管增量（必做）→ 注释补齐（低风险高收益）→ 表名分域分批统一（可选，建议做）→ 语义收敛只修三个真痛点（严格限定范围）。不建议做字段级大规模重命名和库名变更。**

## 二、现状普查数据

### 2.1 盘子

| 维度 | 数据 |
|------|------|
| 真实库基表 | 111 张（另 alembic_version；`mcp_tokens` 迁移 051 未落库） |
| 总列数 | 1325 |
| 列注释覆盖 | 626/1325 = **47%**（design 域 92%，insight 域仅 8%） |
| 表注释覆盖 | 49/111 = **44%** |
| Alembic 迁移 | 53 个文件，编号至 051（`002` 前缀重复 ×2、1 个哈希命名 revision） |

### 2.2 已经统一的（不需要动）

- 时间戳：`created_at` / `updated_at`（真实库与模型双向验证，旧变体零命中）
- 状态字段：`status` 32 列，`state` 零命中
- 拼写错误：零命中
- 前端/小程序：消费的已是规范名；小程序对审计字段零消费

### 2.3 真正的不一致清单

**A. 表名前缀三轨**（改造主标的）
- `ark_` 前缀：78 张（77 张映射类 + 1 张 `Table()` 关联表 `ark_asset_tags`）
- 域前缀：`design_*` 8 张、`dingtalk_*` 2 张、`sys_dict`、`mcp_tokens`（在飞）
- 裸名：production 报工 6 张（`process`/`process_route`/`process_route_step`/`product_process_route`/`order_product_process_progress`/`user_process_binding`）、提成老域 9 张（`commission_batch`/`commission_batch_confirmation`/`commission_batch_feedback`/`commission_detail`/`synced_payment`/`payment_commission_status`/`customer_commission_snapshot`/`employee_attribute_history`/`supervisor_relation_history`）、tracking 4 张（`shipment_tracking`/`shipment_staging`/`tracking_events`/`carrier_config`）、governance 3 张（`data_concepts`/`concept_relationships`/`concept_change_logs`）
- 同域内自相矛盾：tracking 域 4 裸名 + 2 张 `ark_`（`ark_waybills`/`ark_shipping_daily_reports`）

**B. 单复数与 `_log(s)` 混乱**
- `ark_production_orders`(复) 与 `ark_production_cart`(单)、`ark_production_audit_log`(单) 与 `ark_production_print_logs`(复) 同域并存
- `_log` 单数 4 张 vs `_logs` 复数 8 张

**C. 软删除三轨（语义级）**
- `deleted_at` DateTime：5 表（ai×2、auth×2、design×1）
- `is_active` Boolean：约 11 表（但其中多数语义是"启用开关"而非软删，如 `ark_insight_sources`、`ark_expo_wigs`）
- `deleted_flag` SmallInteger：1 表（`ark_production_orders`；**docs/database.md 误记为 `delete_flag`，文档已漂移**）

**D. 操作人字段分裂（语义级）**
- `created_by` Integer(=ark_users.id)：13 列（主流）
- `tracking.created_by` **String(50)**（存的是姓名，与主流类型冲突）
- `governance.operator` String(64)、另有 `operator_id` Integer 3 列并行

**E. 备注三轨**：`remark` 13 列 / `notes` 3 列 / `comment` 3 列（`comment` 作列名与 SQLAlchemy `comment=` 参数同名，易混）

### 2.4 改名穿透链（为什么列改名成本极高）

```
物理列名 == ORM 属性名 == Pydantic 字段名 == JSON key == 前端 prop == sort_field 值
```
- 全仓 Pydantic 字段 `alias=/populate_by_name/by_alias` 零命中——无映射层先例（`stock/router.py:255,277` 有 2 处 FastAPI `Query(alias=)`，那是请求参数别名，不是字段映射）
- `.mappings()` + `dict(row)` 直通模式遍布 stock/report/mini/invoice——SELECT 列名直接变 JSON key
- 排序链全程物理列名：el-table `prop="created_at"` → `sort_field` → 后端 13 处 `SORT_MAP` / 2 处 `getattr(Model, sort_by)` + 正则白名单（`Query(pattern=...)`）
- 前端 19 个 view 消费 `created_at`（34 处）；小程序零消费

### 2.5 表名硬编码引用面（改表名的全部暗雷）

- **16 个文件、约 90~100 个裸 SQL 点位**硬编码 commission_db 表名：
  - stock 域 8 文件（`production_order_service.py` 一家约 25 处 text()，含 2 处动态拼列名）
  - `report/data_service.py`（约 12 处，报工 5 张裸名表全在）、`asset/folder_upload_service.py`、`design/utils.py`（`design_request_seq`）、`production/binding_service.py`
  - 运维脚本 4 个（`clear_asset_tags.py`/`bulk_tag_asset.py`/`backfill_payment_fx.py`/`seed_product_process_route.py`）
- 涉及表：`ark_users` 五件套（users/roles/permissions/user_roles/role_permissions）、生产订单四件套、`ark_safety_stock`、`ark_asset*` 三张、`synced_payment`、`design_request_seq`、报工域 5 张裸名表
- **lsordertest 表不在改名范围**：跨库 SQL 中库名走 `{business_db}` 配置插值（唯一例外：`color/social_extract_service.py:155` 把 `lsordertest.` 写死在 SQL 里）

**除裸 SQL 外，还有三类表名字符串点位（对抗性审查补入）**：
1. **ORM `ForeignKey("旧表名.列")` 字符串**：`production/models.py:61,62,81,101,102,127`（process/process_route）、`models/commission.py:58,95,104,122`（commission_batch）、`governance/models.py:188,192,224`（data_concepts）、`design/models.py:82,196`。漏改会在 mapper 配置期 `NoReferencedTableError` 启动即炸（能发现，但应列入每批清单而不是靠炸）
2. **引导 SQL 死文件**：`backend/sql/init.sql`（7 张提成裸名表 CREATE TABLE）、`database/dingtalk_init.sql`（2 张钉钉表）。大概率已被 Alembic 取代，但留着会误导初始化并卡 grep 门控——P2 批次内显式删除或声明废弃
3. **库内数据存表名**：`data_concepts.primary_table`（String）与 `related_tables`（JSON）按设计登记物理表名（`governance/models.py:123,126`）。改名后治理注册表存量数据静默失真，每批需附 `UPDATE data_concepts` 数据修正或人工核对

### 2.6 外部消费方

| 消费方 | 耦合情况 | 改名影响 |
|--------|----------|----------|
| Stimulsoft 报表 | 模板 `.mrt` 存 `ark_report_templates` 表内；数据源是 JSON API，模板绑定 JSON 字段名（来自 `data_service.py` 的 SQL 别名） | 只改表名不改 SELECT 输出别名 → 模板无感；改列名且别名跟着变 → **存量模板全部要改** |
| whatsapp-connector | JSON 文件持久化，不直连库 | 无影响 |
| 微信小程序 | 走后端 API，审计字段零消费 | 表名无影响；列名基本无影响 |
| 钉钉通知/日报 | 走 service 层 | 随代码同步改，无独立风险 |
| Accio 报工（工序进度） | 走 `/api/production/report` API | 表名无影响 |
| 数据概念治理（库内数据） | `data_concepts.primary_table/related_tables` 存物理表名 | **改名后存量登记数据全部失效**，需随批数据修正 |

## 三、命名规范提案（管增量的宪法，无论存量改不改都先立）

### 3.1 表名
1. 统一前缀 `ark_`（方舟资产标识，区分同库/同实例第三方表）
2. `ark_<domain>_<entity>`，entity 用**复数**（`ark_users`、`ark_production_orders`）
3. 日志类统一 `_logs` 复数；配置类单行表用 `_settings`
4. 不把第三方系统名嵌入新表名（存量 `ark_xiaoman_settings` 不追溯）

### 3.2 字段
1. 审计四件套：`created_at` DATETIME / `updated_at` DATETIME / `created_by` INT(=ark_users.id) / `updated_by` INT。**存"姓名"的列一律 `xxx_name` 后缀**（如 `created_by_name`），禁止用 `created_by` 存字符串
2. 软删除：需要软删的表用 `deleted_at` DATETIME NULL（可判"何时删"）；`is_active` 保留但**仅用于"启用/停用开关"语义**，不再当软删用；`deleted_flag` 不再新增
3. 备注统一 `remark`；`comment` 禁用作列名
4. 状态用 `status`；布尔用 `is_` 前缀
5. **新列必须带 `comment=`**（列注释），新表必须带表注释
6. 外键列 `<entity>_id`；操作人语境用 `created_by`/`updated_by`，不再新增 `operator/operator_id`

### 3.3 迁移
- revision ID `NNN_动词_对象` ≤32 字符（已有规则），编号不重复；重命名类迁移必须写可逆 `downgrade()`（rename 是少数完美可逆的 DDL）

### 3.4 落地为机器规则
`scripts/check_conventions.py` 增量 diff 检查新增：① 新 `__tablename__` 不带 `ark_` 前缀 → 红项；② 新 Column 无 `comment=` → 黄项；③ 新列命名撞禁用词表（`create_time/update_time/is_deleted/deleted_flag/operator/state/note` 等）→ 红项。

## 四、改动策略对比与推荐

| 策略 | 内容 | 收益 | 风险/成本 | 判定 |
|------|------|------|-----------|------|
| A. 全量大爆炸 | 表名+列名+语义一次性统一 | 一步到位 | 六层穿透全动、Stimulsoft 存量模板重做、~100 裸 SQL 点位一次性核销、回归面=全系统 | **否决**：字段层已统一，列名重命名收益趋零而成本最高 |
| B. 分层分批（推荐） | 见下方 P0-P3 | 收益/风险每层独立可控，每层可独立叫停 | 周期拉长 | **推荐** |
| C. 只管增量 | 立规范+check 脚本，存量不动 | 零风险 | 表名三轨长期存在，AI 协作时每次都要解释历史包袱 | 保底方案（=只做 P0） |

**推荐 B，且明确不做的事**：字段级大规模重命名（没必要）、库名 `commission_db` 变更（MySQL 无 RENAME DATABASE，需建新库逐表搬迁+改配置链，收益趋零）、索引/约束名追溯规范化（纯内部名，零收益）、`is_active` 语义重构（行为变更，与命名治理解耦）。

## 五、分阶段实施步骤（策略 B）

### P0 规范先行（~0.5 天，必做，零风险）
1. 第三节规范写入 `docs/database.md` 头部（命名宪法区）
2. `check_conventions.py` 加三条检查（3.4）
3. 顺手修正 docs/database.md 的 `delete_flag` → `deleted_flag` 等漂移

### P1 注释补齐（~1 天，低风险高收益，与改名解耦）
1. 从 information_schema 导出无注释的 699 列 + 62 张无注释表清单
2. 按域生成 Alembic 迁移批量补 `COMMENT`（只改注释不改名不改类型；本库数据量小，rebuild 成本可忽略）
3. 同步回填 ORM `comment=` 参数，保证模型与库一致

### P2 表名统一（~3-5 天，分 6 批，可选但建议做）
每批固定流程：**映射表 → Alembic `op.rename_table`（含可逆 downgrade）→ ORM `__tablename__` + `ForeignKey("表名.列")` 字符串 → 裸 SQL 点位核销（按附录 B 清单）→ `data_concepts` 登记数据修正 → 旧表名定向 grep 门控 → pytest + 冒烟 → 独立 agent 对抗性审查 → 部署**。

**grep 门控方法（照抄可用）**：
- 排除 `alembic/versions/`——历史迁移合法保留旧名（`001_initial.py` 的 `ForeignKey("commission_batch.id")`、`006` 的 `INSERT INTO sys_dict` 等），从零重建链依然成立：历史迁移按旧名建表→rename 迁移在 head 追加改名
- 通用词表名（`process`）不能全文 grep，用 SQL 上下文正则：`(FROM|JOIN|INTO|UPDATE)\s+`?process`?\b`（实测运行时裸 SQL 仅 `report/data_service.py:387,403` 两处）
- 其余表名全文 grep（`.py/.sql/.md/.yaml`，排除 alembic/versions 与本评估文档）零命中为过关

**纪律与失败恢复**：P2 全周期内新功能迁移禁止引用旧表名；一批多表 rename 时 MySQL 逐条自提交，中途失败会停在半改名状态且 Alembic 不会自动 downgrade——恢复动作是按映射表手工补齐剩余 RENAME（优先）或回快照（数据窗口损失，最后手段）。

批次划分（按裸 SQL 密度从低到高练手）：
1. governance 3 张 + dingtalk 2 张（运行时无裸 SQL；需删除/废弃 `database/dingtalk_init.sql`，并做 `data_concepts` 数据修正首练）
2. design 8 张（裸 SQL 仅 `design_request_seq` 1 处）
3. tracking 4 张（注意 `shipment_tracking.short_code` 与短链共用 `/s/{code}` 路由，只改表名不影响）
4. 提成老域 9 张（**管钱域，共享层 app/models/ 冻结例外报备**；`synced_payment` 有脚本硬编码；需删除/废弃 `backend/sql/init.sql`）
5. production 报工 6 张（`report/data_service.py` 约 12 处裸 SQL 是主战场；`process` 表用上述定向 grep）
6. `sys_dict` + 单复数矫正批（`ark_production_cart`→`ark_production_carts`、`ark_production_audit_log`→`_logs` 等，一次到位避免二次改名）

每批部署走 `deploy.bat`（停服→迁移→起服，天然原子窗口，30 日活内部系统可接受分钟级停机）。迁移前打 RDS 快照。

### P3 语义收敛（按需，只修三个真痛点，每个单独立项）
**对抗性审查修正：前两项不是"无行为改动的诚实命名"，而是全链路 API 契约变更**——列名会穿透 schema→JSON→前端显示（§2.4 六层焊死同样适用于它们），范围含迁移 + ORM + schema + service dict key + 前端 + 钉钉消息模板：
1. `ark_waybills.created_by` String(50) → `created_by_name`（注意：该列在 **ark_waybills**，不在批次 3 的 shipment 系表上。穿透链：`tracking/models.py:165` → `tracking/schemas.py:142` → `upload_service.py:84,252` dict 直出 + `:287` 钉钉消息 → 前端 `WaybillUpload.vue:99`）
2. `data_concepts.operator` → `operator_name`（穿透链：`governance/schemas.py:172` → 前端 `ChangeLog.vue:27`）
3. `ark_production_orders.deleted_flag` → 评估改 `deleted_at`（行为变更：所有 `WHERE deleted_flag=0` 的裸 SQL 要跟着改，集中在 `production_order_service.py` 约 25 处点位；单独排期单独审查）

## 六、风险清单与控制

| 风险 | 控制手段 |
|------|----------|
| 裸 SQL 点位漏改，注册期不报错运行期才炸 | 附录 B 逐表核销清单 + P2 节的定向 grep 门控（排除 alembic/versions；`process` 表用 SQL 上下文正则） |
| ORM `ForeignKey("旧表名.列")` 字符串漏改 | 启动期即 NoReferencedTableError（可发现），已列入每批固定流程第三步 |
| `data_concepts` 治理登记数据静默失真 | 每批附 UPDATE 数据修正（primary_table 精确替换 + related_tables JSON 替换）+ 全景图谱人工抽查 |
| MySQL DDL 不可回滚惯性认知 | rename 恰好可逆：每个迁移写真实 `downgrade()`；仍按惯例迁移前 RDS 快照 |
| 代码与库版本错配窗口 | 单体架构 + deploy.bat 停服迁移再起服，代码与 DDL 同一窗口原子切换 |
| 08:30 定时任务链（日报 raw SQL 引用 ark_users 五件套） | 部署窗口避开 08:00-09:00；批次 4/5 上线次日人工核对日报产出 |
| Stimulsoft 存量模板失效 | P2 只改表名不改 SELECT 输出别名 → 模板理论无感；每批含报表中心两张核心报表的人工回归 |
| 在飞的 mcp 模块（051 迁移未提交） | P2 首批排在 mcp 落地之后；`mcp_tokens` 建议落地前直接更名 `ark_mcp_tokens`（此刻改零成本） |
| FK/触发器随改名失效 | MySQL RENAME TABLE / RENAME COLUMN 自动更新 FK 引用；本库无触发器/存储过程/视图（information_schema 已核对） |
| 文档漂移 | 每批同步 docs/database.md + api-reference.md；本评估已发现 `delete_flag` 误记先行修正 |

## 七、待拍板决策点

1. **P2 存量表名改造做不做？**（推荐：做，分批；不做则只剩 P0+P1，命名三轨永久保留）
2. **目标形态是否全部收敛到 `ark_` 前缀？** 含 `design_*`/`dingtalk_*`/`sys_dict`（推荐：全收敛，一个规则好过三个例外；代价是批次 2 多 7 张表工作量）
3. **单复数矫正是否纳入 P2？**（推荐：纳入，改一次总比改两次好；保守选项是只统一前缀、单复数只管增量）
4. **库名 `commission_db` 动不动？**（推荐：不动。库名已与"提成系统"名不副实——实际是方舟平台库，但 MySQL 无 RENAME DATABASE，搬迁成本与配置链风险换一个名字，收益趋零。若坚持，可在某次大版本窗口用 `RENAME TABLE old_db.t TO new_db.t` 逐表瞬时搬迁，单独立项）
5. **P3 的 `deleted_flag→deleted_at` 行为级改造做不做？**（推荐：暂缓，等 P2 批次 5 完成后单独评估）

## 附录 A：非 ark_ 前缀存量表全清单（33 张 + 在飞 1 张；9+8+6+4+3+2+1=33）

commission 老域（9）：`commission_batch` `commission_batch_confirmation` `commission_batch_feedback` `commission_detail` `synced_payment` `payment_commission_status` `customer_commission_snapshot` `employee_attribute_history` `supervisor_relation_history`
design（8）：`design_audit_log` `design_capacity_config` `design_designer` `design_request_attachment` `design_request_seq` `design_schedule_request` `design_schedule_task` `design_unavailable_date`
production 报工（6）：`process` `process_route` `process_route_step` `product_process_route` `order_product_process_progress` `user_process_binding`
tracking（4）：`shipment_tracking` `shipment_staging` `tracking_events` `carrier_config`
governance（3）：`data_concepts` `concept_relationships` `concept_change_logs`
dingtalk（2）：`dingtalk_callback_log` `dingtalk_message_log`
system（1）：`sys_dict`
在飞（1）：`mcp_tokens`（落库前直接更名 `ark_mcp_tokens` 零成本）

## 附录 B：裸 SQL 硬编码 commission_db 表名的文件清单（P2 核销用）

app 模块（12）：
`stock/daily_report_service.py`（ark_users 五件套）、`stock/in_transit_service.py`、`stock/overview_service.py`、`stock/print_workstation_service.py`、`stock/production_cart_service.py`、`stock/production_order_service.py`（~25 处，含动态拼列）、`stock/safety_service.py`、`stock/sku_query.py`、`report/data_service.py`（报工 5 张裸名表 + 生产订单）、`asset/folder_upload_service.py`、`design/utils.py`、`production/binding_service.py`

运维脚本（4）：
`backend/scripts/clear_asset_tags.py`、`backend/scripts/bulk_tag_asset.py`、`backend/scripts/backfill_payment_fx.py`（synced_payment）、`backend/scripts/seed_product_process_route.py`

引导 SQL 死文件（2，批次内删除或声明废弃）：
`backend/sql/init.sql`（7 张提成裸名表）、`database/dingtalk_init.sql`（2 张钉钉表）

ORM FK 字符串（启动期可发现，仍列入核销）：
`production/models.py:61,62,81,101,102,127`、`models/commission.py:58,95,104,122`、`governance/models.py:188,192,224`、`design/models.py:82,196`

字段名字符串工作点（列名如有变动才需核对）：13 处 SORT_MAP（值为 ORM 列对象，改名自动跟随，**键是 API 契约不要动**）、`asset/asset_service.py:318` 与 `insight/item_service.py:70` 的 `getattr(Model, sort_by)` + 对应 API 正则白名单、`report/data_service.py` 的 `header_row["..."]` 字典取值。

审查确认无需担心的面（实证过，不列风险）：conftest 用 `Base.metadata.create_all` 建表自动跟随改名；前端无物理表名硬编码（`ProductManage.vue` 的 `process_route` 是 relationship JSON key）；Stimulsoft 渲染入口一律 `dictionary.databases.clear()` 后注入 JSON，模板内即使存了 SQL 数据源也会被清掉；六个批次之间无跨批 FK/JOIN 依赖。
