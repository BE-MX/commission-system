# 莱莎方舟 数据库表参考

> 本文档由 CLAUDE.md 瘦身治理（2026-07-03，见 docs/2026-07-03-architecture-assessment.md G-1）拆出。
> 变更 API/表结构/模块行为时**同步更新本文件**。

## 命名宪法（2026-07-08 起对增量强制，评估见 docs/2026-07-08-db-naming-assessment.md；check_conventions.py 机器检查）

**表名**
1. 新表一律 `ark_<domain>_<entity>`，entity 用**复数**（`ark_invoices`、`ark_production_orders`）
2. 日志类统一 `_logs` 复数；单行配置表用 `_settings`；不把第三方系统名嵌入新表名
3. 关联表也走 `ark_` 前缀；用 `Table()` 声明的关联表必须在本文档登记（盘点工具会漏 `Table()`，全库现仅 `ark_asset_tags`）

**字段**
1. 审计四件套：`created_at` / `updated_at` DATETIME + `created_by` / `updated_by` INT（=ark_users.id）。存姓名一律 `xxx_name` 后缀，禁止用 `created_by` 存字符串
2. 软删除用 `deleted_at` DATETIME NULL；`is_active` 仅表示"启用/停用开关"，不当软删用；`deleted_flag`/`is_deleted` 禁止新增
3. 备注统一 `remark`；禁用 `note`/`notes`/`comment` 作列名；状态用 `status` 禁 `state`；操作人不再新增 `operator`/`operator_id`
4. 布尔列 `is_` 前缀；外键列 `<entity>_id`；**新列必须带 `comment=` 注释（中文优先，术语/外部系统字段可英文），新表必须带表注释**；枚举/状态列把可选值写进注释，金额列注明币种口径

**迁移**：revision ID `NNN_动词_对象` ≤32 字符；重命名类迁移必须写可逆 `downgrade()`

## 数据库

- 提成库 `commission_db`：读写，存放提成系统自有数据
- 业务库 `lsordertest`：只读，跨库查询订单/回款原始数据
- 两库在同一 RDS 实例，通过库名前缀跨库访问
- 生产后端使用 `ark_app@%`：`commission_db.*` 授予 `SELECT, INSERT, UPDATE, DELETE`，`lsordertest.*` 授予 `SELECT`；唯一跨库写例外是 `lsordertest.okki_receipts.collection_date` 的列级 `UPDATE`，由回款修复服务写入并在 `ark_receipt_repair_log` 审计。迁移与 DDL 由单独 DBA 账号执行。

## 统一客户经营库（迁移 126，2026-08-31）

迁移 126 将公海背调、智能搜索、客户池、客户机会台和经营雷达统一到一个客户域。`ark_customer_accounts.id` 是唯一客户主键；主档代表公司或商业账户，`canonical_company_name` 可以为空，不能用公司名、个人邮箱或联系人姓名作为身份键。阿里、OKKI、Google、官网、LinkedIn 等只作为来源，经过身份解析、事实化和证据绑定后进入方舟；下游 Agent 只读方舟。

迁移冻结了 **39 张表、778 个字段**的 MySQL 物理契约。每张表都有数据库 `TABLE_COMMENT`，每个字段都有 `COLUMN_COMMENT`；完整逐字段类型、约束和备注保存在 `backend/alembic/versions/126_unified_customer_domain_schema.json`，并由 SHA-256 固定。2026-08-31 在 MySQL 8.4.11 严格模式下通过 `information_schema` 核验：空表备注 0、空字段备注 0。

| 分层 | 表 | 职责 |
|---|---|---|
| 客户身份 | `ark_customer_accounts`、`ark_customer_names`、`ark_customer_external_identities`、`ark_customer_resolution_keys`、`ark_customer_relationships` | 公司/商业账户主档、名称别名、外部身份、解析键和公司关系；弱身份只能形成候选，不能自动合并 |
| 联系人与触点 | `ark_customer_contacts`、`ark_customer_contact_points`、`ark_customer_contact_relationships` | 联系人、邮箱/电话/社媒触点和联系人—公司任职关系；个人邮箱归联系人，不等于公司身份 |
| 来源、事实与证据 | `ark_customer_source_records`、`ark_customer_facts`、`ark_customer_fact_evidence_links`、`ark_customer_fact_conflicts`、`ark_customer_events`、`ark_customer_annotations` | 不可变来源版本、可计算事实、证据链接、冲突、业务事件和人工标记；推断与原始事实分开保存 |
| 档案与 Agent 上下文 | `ark_customer_profile_versions`、`ark_customer_agent_contexts`、`ark_customer_list_projections` | 可迭代档案版本、面向 Agent 的受控上下文和列表投影；Agent 必须携带所读档案版本及事实/证据 ID |
| 归属与治理 | `ark_customer_assignments`、`ark_customer_object_ownerships`、`ark_customer_change_proposals`、`ark_customer_agent_run_scopes`、`ark_customer_suppression_registry` | 唯一主负责人、合并后逻辑归属、高影响变更提案、Agent Run 数据范围和禁止联系/抑制登记 |
| 沟通与订单 | `ark_customer_conversations`、`ark_customer_messages`、`ark_customer_conversation_analyses`、`ark_customer_orders`、`ark_customer_order_items` | 阿里/邮件/社媒等会话消息及分析、OKKI 订单与明细；订单决定真实成交与采购周期，不由机会状态替代 |
| 获客与公海 | `ark_sales_search_jobs`、`ark_sales_search_results`、`ark_sales_search_result_sources`、`ark_sales_public_pool_batches`、`ark_customer_target_matches`、`ark_customer_acquisition_attributions`、`ark_customer_research_tasks`、`ark_customer_qualification_reviews`、`ark_customer_sync_cursors` | 目标画像快照、搜索候选及逐来源证据、公海批次、目标匹配、归因、背调、资格审核和同步游标 |
| 机会与行动 | `ark_customer_opportunities`、`ark_customer_opportunity_events`、`ark_customer_actions` | 客户机会当前态、不可变机会事件和经营雷达行动；完成行动必须落真实销售活动事件，不能把建议当成已触达 |

`ark_sales_target_profiles` 保留原表，并由迁移增加版本化策略字段；`ark_inquiry_import_batches`、旧 `ark_sales_companies/contacts/research_*`、旧 `ark_customer_profiles/profile_events` 等重复主档在切换时删除。回款、物流、售后、展会数据不在本期客户档案范围内。

关键数据库不变量：

- 公司名是可验证属性，不是必填身份键。仅有个人名/个人邮箱时创建 provisional 客户与联系人，再通过公开商业证据反查公司；禁止调查私人社会关系。
- 一个客户同一时刻最多一个有效主负责人；无有效主负责人表示进入公海，是否“可领取”必须结合资格、DNC、冷却期、团队和额度实时计算。
- 来源记录不可变；事实必须保存置信度、方法版本、分类、可见范围和证据。冲突不静默覆盖。
- 合并、拆分、主负责人转交、DNC 设置/撤销和重大风险确认走 `ark_customer_change_proposals`，审批与执行分离并校验档案版本。
- 迁移 126 无 downgrade，必须通过 `scripts/customer_domain_cutover.py` 的维护窗证据链执行；禁止直接运行裸 `alembic upgrade head` 完成这次重建。

**业务库常用表口径（lsordertest，OKKI 同步投影，只读）**：
- `customer_info` — 客户主表（company_id bigint 主键，company_name，country_name，**owner_user_ids JSON 数组**=归属 OKKI user_id 列表、空数组=公海；私海过滤用 `JSON_CONTAINS`）
- `customer_contacts` — 客户联系人（company_id→customer_info，name/email/tel/is_main；发票录入「按联系人搜客户」数据源，2026-07-14 起）
- `customer_contact_socials` — 联系人社交账号（customer_id→customer_contacts.customer_id，platform/value；社媒客户 MCP 查询源）
- 社媒客户 MCP 查询索引（2026-07-22，业务库手工在线 DDL，不进 Alembic）：`customer_info.idx_social_mcp_customer_email(email(191))`、`customer_contacts.idx_social_mcp_contact_phone(tel)`、`customer_contact_socials.idx_social_mcp_social_value(value(191))`
- 订单智能分析索引（2026-08-13，业务库幂等在线 DDL，不进 Alembic）：`okki_orders.idx_order_intel_user_account_date(user_id, account_date)`，加速个人范围和由团队成员反查订单的日期区间查询；执行 `cd backend && python -m scripts.ensure_order_intelligence_indexes`

**主要业务表（commission_db）**：
- `ark_semifinished_materials` — 半成品主数据；`(size,color_key)` 唯一，数量业务统一用 g，颜色类型描述物料本身（solid/t/named_t）。
- `ark_semifinished_product_mappings` / `ark_semifinished_product_components` — OKKI 产品解析快照与半成品组成；产品唯一键 `(source_type,product_id)`，组成比例合计由服务层保证为 1，自动结果可进入 `needs_review`。
- `ark_semifinished_orders` / `ark_semifinished_order_items` — 手工或随生产订单创建的半成品订单及明细；状态 `submitted/partial/completed/terminated`，订购量和累计入库量均为 `DECIMAL(14,3)` g。
- `ark_semifinished_inventory_balances` — 每物料唯一余额快照，分 `on_hand_grams` 与 `reserved_grams`；可用量实时计算为实存减占用，更新时持有行锁。
- `ark_semifinished_inventory_ledger` — 不可变库存流水；全局 `idempotency_key` 唯一，记录变化后实存/占用、业务来源及操作人。
- `ark_semifinished_cart_plans` — 生产购物车行的半成品同步下单计划；购物车数量变化时按比例缩放，创建生产订单后级联删除。
- `ark_invoice_semifinished_allocations` — 发票当前已出库量和 OKKI 同步期间待处理差额；`(invoice_id,material_id)` 唯一，`pending` 批次通过 `operation_key` 串联预占、完成或释放。
- `ark_invoice_sync_logs.inventory_operation_key` — 121 迁移新增；把 OKKI 成功日志与本次半成品预占批次精确关联，管理员恢复时禁止用历史成功日志误确认新批次。
- `ark_invoice_items.semifinished_enabled` / `semifinished_plan` — 生产型发票行是否使用半成品及当次计划快照；JSON 只保存 `material_id/quantity_grams`，同步前重新校验已审核映射。
- `sys_dict` — 系统字典（type, code, label, sort, is_active）；`(type, code)` 唯一索引。GMV 钉钉日报复用三个保留 type：`dingtalk_gmv_team`（部门/队长）、`dingtalk_gmv_member`（人员/所属队/是否排除）、`dingtalk_gmv_admin`（明确勾选的管理员接收人），不增加专用配置表；三个 type 从通用字典列表/读取中隐藏，通用 CRUD 明确拒绝，只能经 `dingtalk:admin` 专页校验后写入
- `dingtalk_message_log` — 钉钉消息日志；GMV 日报用 `related_type + related_id` 标识日期、队伍/管理员接收人，保存首次消息快照并实现成功幂等、失败重试
- `ark_permissions` — 权限表（code 唯一, module, action, label；046 起新增 **kind** page/action/data、**is_legacy** 下架标记、**sort**；seed 为 upsert，元数据每次启动刷新）
- `ark_permission_audit` — 角色权限变更审计（046 迁移：role_id/role_name, operator, added_codes/removed_codes JSON）
- `ark_waybills` — 运单录入表（waybill_no 唯一，carrier, recipient_name, recipient_country, ship_date, status, estimated_delivery_date, entry_source, created_by）；通过图片 OCR 或手动录入
- `shipment_tracking` — 运单跟踪表（waybill_no, carrier, current_status, unified_status, last_pushed_status, dingtalk_user_id, short_code, estimated_delivery_date, deleted_at）；轮询自动维护，`unified_status` 为统一状态码（picked_up/in_transit/customs_hold/out_for_delivery/delivered/exception），`last_pushed_status` 防重复推送；`deleted_at` 软删标记（056 迁移，与 `is_active` 轮询开关语义分离，已删行对列表/详情/统计不可见，钉钉重新提交自动恢复）
- `ark_short_links` — 短链记录表(short_code VARCHAR(8) UNIQUE, original_url TEXT, created_at, click_count);承载 `https://leshine.work/s/{code}` 跳转,与历史 `shipment_tracking.short_code`(8 位旧承运商短码)共用 `/s/{code}` 路由
- `design_schedule_request` — 拍摄预约申请；`shoot_type VARCHAR(255)` 逗号分隔多选值，`customer_level VARCHAR(64)`，`props_requirement VARCHAR(512)` 逗号分隔道具要求，`preferred_designer_id INT` 期望设计师
- `design_schedule_task` — 设计排期任务；`shoot_type VARCHAR(255)` 逗号分隔多选值
- `design_request_attachment` — 预约附件（file_name, file_path, file_size）；物理文件存 `backend/uploads/design/`
- `design_unavailable_date` — 设计不可预约日(date, period am/pm/NULL=全天, reason);`(date, period)` 唯一约束,reason 用于甘特图 hover 展示
- `ark_ai_providers` — AI 服务提供商配置（name, provider_type, api_base, api_key 加密存储, api_type: openai/anthropic, extra_headers JSON, timeout_sec）
- `ark_ai_presets` — AI 预设（preset_name, provider_id, model, system_prompt, parameters）
- `ark_ai_call_logs` — AI 调用日志（caller_module, preset_name, tokens, duration_ms, status）
- `ark_shipping_daily_reports` — 物流日报（user_id, report_date, html_content, short_url, is_pushed）；`(user_id, report_date)` 唯一约束，每日 08:30 自动生成
- `ark_insight_sources` — 信源配置表（name, source_type, url, keywords JSON, exclude_keywords JSON, proxy_url, css_selector, request_headers JSON, config_json JSON, fetch_interval_hours, is_active, pipeline, sort_order）；source_type 扩展为 `google_alerts_rss/pinterest_scrape/google_trends_rss/amazon_bestseller/competitor_rss/competitor_html/aihot_api/xpoz/competitor_monitor/perplexity/amazon/manual`；config_json 存差异化配置（cron/target_accounts/monitor_fields 等）；keywords 做「包含」过滤，exclude_keywords 做「排除」过滤，proxy_url 供 Google Alerts / Trends / Pinterest 走代理
- `ark_safety_stock` — 安全库存配置（product_id UNIQUE, safety_stock, lead_time_days, safety_factor, source: 0手动/1公式/2TFT）
- `ark_stock_daily_reports` — 安全库存日报（report_date UNIQUE, shortage_skus/warning_skus JSON, dingtalk_sent）
- **生产订单（025/026 迁移）**：
  - `ark_production_orders` — 生产订单主表（order_no UNIQUE, status 0已提交/1已终止/2已完成, deleted_flag 软删, created_by, remark；新写入的 created_at/updated_at 均为北京时间；123 只平移写路径确定为 UTC 的历史 created_at，历史 updated_at 因 ORM UTC 与 SQL NOW() 混写不盲改）
  - `ark_production_order_items` — 生产订单明细（order_id, product_id, product_name, model, spec_info, order_qty, received_qty, status, is_urgent SmallInteger, expected_delivery_date Date, remark；无独立软删字段，靠 FK CASCADE 跟随订单删除）
  - `ark_production_cart` — 生产购物车（user_id + product_id UNIQUE, product_name, model, spec_info, order_qty, remark）
  - `ark_production_audit_log` — 生产订单审计日志（order_id, action, old_value, new_value, operator_id）
  - `ark_platform_time_backup_123` — 123 时间治理迁移对 58 张表、142 个经逐写路径确认的 UTC-naive 字段保存逐表/逐行/逐字段原值；仅用于核对和可逆回滚，不参与业务查询。存在 `NOW()`/旧 UTC/外部时间混写证据的列（如素材 `updated_at`、设计生图提示词模板时间）不猜测平移。
  - `ark_production_print_logs` — 打印日志（039 迁移，order_id, order_no, scope order/category, category_index, category_label, item_ids_json JSON, printed_by, printed_by_name, printed_at）
- **生产报工（027 迁移）**：
  - `process` — 工序基础表（name UNIQUE, description, sort_order, status 0禁用/1启用）
  - `process_route` — 工序路线表（name UNIQUE, description, status）
  - `process_route_step` — 路线明细（route_id + step_order UNIQUE, route_id + process_id UNIQUE; FK route CASCADE, process RESTRICT）
  - `product_process_route` — 产品路线绑定（product_id BIGINT UNIQUE, route_id; 一个产品只绑一条路线）
  - `order_product_process_progress` — 工序进度（order_product_id FK ark_production_order_items CASCADE, process_id, route_id, step_order, status 0待完成/1已完成, completed_at, completed_by_user_id, completed_by_wx_id）
  - `user_process_binding` — 用户工序绑定（user_id + process_id UNIQUE）
  - `ark_users` 新增 `wx_id VARCHAR(100) UNIQUE` — 微信原始 ID（FromUserName），报工时匹配方舟账号
  - `ark_users` 新增 `okki_department_id BIGINT` + `okki_department_name VARCHAR(100)`（068）— OKKI 业绩归属部门（推单 departments 必填；选项从 okki_orders 聚合，id=0「我的企业」合法）
- `ark_insight_reports` — 洞见报告表（report_type: industry_daily/ai_tools/shop_analysis/competitor_analysis/inquiry_analysis/intelligence_overview, report_date, html_content LONGTEXT, file_path, source_data JSON, status: pending/published/failed/generating/completed, trigger_type: manual/scheduled, date_range_start/date_range_end, item_ids JSON, config_snapshot JSON, is_pinned）；`(report_type, report_date)` 为业务唯一键，幂等生成覆盖旧记录
- `ark_case_library` — 业务员案例库（title, scenario, what_was_done, result, customer_name, customer_country, communication_channel, communication_period, total_rounds, final_result, background_check_status, tags JSON, rounds_analysis JSON, dimension_scores JSON, golden_phrases JSON, red_flags JSON, core_strengths JSON, result_analysis JSON, improvements JSON, next_actions JSON, ai_draft JSON, user_corrections JSON, original_content, source_type, uploaded_by, share_person, share_date, status: draft/published/archived/processing/failed, like_count, view_count）；AI 整理时加载 `chat-analysis SKILL` 进行分析，支持用户评价修正；作者可编辑/删除自己的案例，admin 可编辑/删除全部
- **情报采集库（3 张表，021 迁移）**：
  - `ark_insight_items` — 情报条目（source_id, source_type, collected_at, published_at, original_url, title, content_mode: full_text/summary, content_md LONGTEXT, credibility_score 1-5, credibility_label: verified/plausible/uncertain/unverifiable, credibility_note, tags JSON, item_type, related_competitor, is_featured, status: active/archived/flagged, xpoz_post_id, like_count, comment_count, media_type, ai_signal, ai_meaning, ai_action_hint, priority: high/medium/low）
  - `ark_insight_collection_logs` — 采集任务日志（source_id, run_at, status: success/partial/failed, items_fetched/written/filtered, error_message, duration_ms）
  - `ark_insight_schedule_rules` — 速览定时生成规则（rule_name, is_active, cron_expression, config_json, notify_dingtalk, last_run_at）
- **外部账号绑定（2 张表，031 迁移，auth/models.py）**：
  - `ark_user_external_bindings` — 用户外部账号绑定（provider + external_account_id 唯一，ark_user_id FK ark_users，binding_status active/inactive/conflict/pending，软删 deleted_at）
  - `ark_external_binding_candidates` — 外部账号绑定候选（provider + external_account_id 唯一，suggested_user_id 自动匹配，candidate_status pending/bound/ignored）
- **统一客户经营（迁移 126）**：客户机会、机会事件和经营行动均以非空 `customer_id` 关联本文顶部的统一客户主档；迁移 031/034 的导入批次、活画像和 `profile_id` 关联已退役。
- **素材管理（7 张表，020 迁移；078 标签体系 v2 加列）**：
  - `ark_tag_dimensions` — 标签维度（078 加 `is_visible` 可见开关=新旧体系并存/退役机制、`is_managed` 系统托管标记——色系维度由派生脚本独占写入禁人工编辑）
  - `ark_tag_values` — 标签值（078 加 `name_en` 英文名、`aliases` JSON 别名数组（agent 检索匹配用）、`parent_value_id` 自引用 FK unsigned——内容子类挂内容大类/产品型号挂产品族）
  - `ark_assets` — 素材主表（078 加 `orientation` 画幅 landscape/portrait/square，上传时自动算，存量由 `scripts/tag_taxonomy/retag.py` 回填）
  - `ark_asset_versions` — 版本历史
  - `ark_asset_tags` — 素材-标签关联
  - `ark_asset_permissions` — 权限
  - `ark_favorite_folders` — 收藏夹
  - `ark_favorite_items` — 收藏项
  - `ark_download_logs` — 下载日志
- **发色数字化（7 张表，022 迁移）**：
  - `ark_color_palette` — 基础色号（industry_code, hex_code, rgb, lab, hsl, undertone, color_family, pantone_tcx）
  - `ark_color_blend` — 混合色号（blend_code, blend_type, computed_hex, source）
  - `ark_color_blend_component` — 混合色成分（blend_id, palette_id, position, weight, sort_order）
  - `ark_competitor_color_watch` — 竞品色号监控（brand, color_code, extracted_hex, social_mentions_30d, popularity_score）
  - `ark_color_trend_data` — 色彩趋势时序（color_family, data_source, period_date, raw_value, normalized_score）
  - `ark_color_swatch_image` — 色板图生成记录（palette_id/blend_id, prompt, model_used, image_path, delta_e, pass_check, status）
  - `ark_pantone_reference` — Pantone 参考色库（AI 生图提示词使用 Solid Coated V5 3219 条；另保留其他 collection；pantone_code, hex_code, rgb, lab, collection）
- **WhatsApp 同步（7 张表，035 迁移）**：
  - `ark_whatsapp_accounts` — 已绑定 WhatsApp 账号（account_uid UNIQUE, ark_user_id FK, phone_number, status binding/active/revoked, connector_status）
  - `ark_whatsapp_bind_sessions` — 扫码绑定会话（bind_session_uid UNIQUE, ark_user_id FK, status pending/scanning/bound/expired/failed, qr_code_url）
  - `ark_whatsapp_conversations` — 会话投影（conversation_uid UNIQUE, account_uid + chat_id 唯一, contact_phone, contact_name, is_group, last_message_at）
  - `ark_whatsapp_messages` — 消息投影（message_uid UNIQUE, account_uid + external_message_id 唯一, direction in/out, content_type text/image/video/document, content_text, sent_at）
  - `ark_whatsapp_attachments` — 附件元数据（message_uid, file_name, mime_type, file_size, storage_url）
  - `ark_whatsapp_pull_cursors` — 增量拉取游标（account_uid + resource + scope_uid 唯一, cursor_value, last_pulled_at）
  - `ark_whatsapp_audit_logs` — 操作审计（account_uid, ark_user_id FK, action, result, detail）
- **数据概念治理（3 张表，030 迁移）**：
  - `data_concepts` — 概念主表（id VARCHAR(64) PK 语义化业务 ID，~20 业务字段，status pending/active/deprecated/archived，layer/confidence/priority ENUM）
  - `concept_relationships` — 关联关系（source_id + target_id + relation_type 唯一约束，relation_type: parent_of/influences/conflicts_with/composed_of/derived_from/requires，is_auto_generated 标记双向边）
  - `concept_change_logs` — 变更记录（concept_id FK, action, snapshot JSON 全量, changed_fields JSON diff, operator）
- **提成批次确认（3 张表/变更，041-043 迁移）**：
  - `commission_batch` — status ENUM 新增 `confirming`（draft/calculated/confirming/confirmed/voided）
  - `commission_batch_feedback` — 业务员反馈（batch_id FK, ark_user_id, user_name, business_user_ids, content TEXT）；`(batch_id)` + `(ark_user_id)` 索引
  - `commission_batch_confirmation` — 业务员确认（batch_id FK, ark_user_id, user_name, business_user_ids, confirmation_text, status confirmed/revoked）；`(batch_id, ark_user_id)` 唯一约束
- **订单发票（9 张业务表，另有 3 张 108 迁移备份表；044 迁移 + 049 扩展 + 107 代创建授权 + 108 北京时间 + 119 截图来源）**：
  - `ark_invoices` — 发票主表（invoice_no UNIQUE, order_type stock/production, customer_id/name, 联系人快照 contact_name/phone/email + delivery_address, 业务员快照 sales_user_id/name/phone/email, invoice_date, currency, status draft/ready/synced/sync_failed, express_channel/shipping_fee/surcharge_name/surcharge_amount/payment_term, product_amount=行净额合计, total_amount=行净额+包装费+运费+手续费, internal_discount=仅头发明细折扣合计的只读兼容快照, internal_accessory=包装费, packaging_quantity=包装数量且不参与金额乘算——071 迁移, internal_received=预付款, internal_balance=尾款, xiaoman_order_id/no, sync_status/error/synced_at, xiaoman_removed_lines 已推明细删除快照 JSON——066 迁移，编辑删行时累积、推单成功清空; okki_new_deal/okki_free_shipping/okki_first_return 三个 OKKI 必填业务标记——068 迁移，1是/0否/NULL 推单时兜底：新成交=客户无 okki 历史订单、包邮=运费为 0、首返=否；119 新增 `source_type` manual/okki_screenshot、`source_order_id/no/name`、`source_image_sha256`，外部接入功能再将 `external_api` 纳入应用层来源值域，并以接入请求 `public_id` 写 `source_order_id`；不保存原图，`(source_type, source_order_id)` 与 `(source_type, source_image_sha256)` 唯一防重复；108 起 created_at/updated_at/synced_at 直接存北京时间）
  - `ark_invoice_items` — 发票明细（invoice_id FK CASCADE, `product_kind` hair/accessory（073）, item_type stock/custom, product_id 可空, sku_id, custom_product_id, product_name/display, net_weight_grams/curl/length 对配件可空, model 可空, color, quantity, standard_price+customer_price 双价快照, price_per_piece, discount_amount 行级折扣负数/0——070 迁移, total_price=`ROUND_HALF_UP(单价×数量,2)+ROUND_HALF_UP(折扣,2)`, price_source customer_rule/manual/missing_std, xiaoman_unique_id）。hair 保持原规格校验；accessory 仅使用 Name/Model/Color 与真实 product_id+sku_id。
  - `ark_custom_products`（049）— 生产单沉淀产品（match_key UNIQUE=归一化 display|model|color|size|unit, product_display/name, model/color/size/unit, okki_product_id/okki_sku_id 对账回填, use_count）；**okki_products 保持只读，本地产品一律进此表**
  - `ark_price_color_types`（049）— 色号→色型（color_code UNIQUE 归一化小写无#, color_type solid/piano/ombre/balayage）
  - `ark_std_prices`（049，073 扩展，074 唯一键隔离）— 标准价矩阵。`product_kind=hair` 使用 product_kind+series_grade+length+weight_unit+color_type 唯一键；`product_kind=accessory` 使用 product_kind+product_id+sku_id 唯一组合及 accessory_name/model/color 快照。配件不从 OKKI `group_name` 推断，一个 SKU 一条标准价。
  - `ark_customer_price_rules`（049）— 客户调价规则（customer_id UNIQUE, adjust_type fixed/percent, adjust_value 有符号, enabled, preferred_template）
  - `ark_invoice_sync_logs`（049）— OKKI 推送日志（invoice_id FK CASCADE, action, success, request_digest/response_body/error_message, operator_id）
  - `ark_invoice_delegate_grants`（107）— 订单代创建授权（delegate_user_id 代办人、sales_user_id 归属业务员、created_by 授权操作人；代办人+归属业务员唯一，三列均关联 ark_users，用户删除时授权级联清理/操作人置空）
  - `ark_invoice_time_backup_108` / `ark_invoice_item_time_backup_108` / `ark_invoice_sync_log_time_backup_108` — 108 历史 UTC→北京时间迁移前逐行时间备份，仅用于核对与可逆回滚，不参与业务查询
  - `ark_xiaoman_settings`（049）— OKKI 推送配置单行表（generic_product_no/id/sku_id 通用产品, default_order_status, default_currency, access_token）
  - `ark_receipt_repair_log`（052）— 回款日期修复审计表（batch_id 分组一次执行, cash_collection_id, order_no, company_name, old_date→new_date, source_file, operator_id, created_at）；**唯一写 `lsordertest.okki_receipts.collection_date` 的入口，每条改动留回滚记录**
- **外部站点发票接入（2 张表，125 迁移）**：
  - `ark_integration_apps` — 站点机器凭证（`public_id` UNIQUE、name、`owner_user_id` FK→`ark_users` CASCADE、`token_hash` CHAR(64) UNIQUE、仅展示用 `token_suffix`、scopes JSON、is_active、expires_at、last_used_at、`created_by` FK→`ark_users` SET NULL、北京时间审计字段）。明文 Token 不落库；当前固定 scope 为 `invoice:write`。
  - `ark_invoice_ingest_requests` — 外部订单幂等与结果恢复记录（`public_id` UNIQUE、`integration_app_id` FK→`ark_integration_apps` CASCADE、external_order_id、规范化请求 `request_sha256`、`invoice_id` FK→`ark_invoices` SET NULL、status=`processing/created/rejected`、稳定 error_code、结构化 error_json、attempt_count、完成/审计时间）。`(integration_app_id, external_order_id)` 唯一，保证不同 App 可复用同一外部订单号、同一 App 不能重复建单。方舟安全删除 `external_api` 发票时，service 同一事务先删除接入记录再删发票，释放 App + `external_order_id`，避免 FK `SET NULL` 留下 `created` 孤儿记录。
- **展会 AI 试戴（7 张表，045 迁移；047 加发色/场景；048 加发色库）**：
  - `ark_expo_customers` — 试戴客户（name 称呼, phone, wechat_id, primary_need volume/gray_cover/style_change, style_pref, **consent_at 非空才允许存照片**, expo_code 届次）
  - `ark_expo_wigs` — 发型库（model_no UNIQUE, series classic/zhizhen 驱动至臻锚点, angle_photos JSON, composite_prompt, fit_tags JSON, evidence_refs JSON, priority, must_recommend 主推=置顶推荐 060 加列/065 语义升级）
  - `ark_expo_hair_colors` — 发色库（code UNIQUE 色号, name, hex_code UI 色块可自动提取, swatch_path 色板图**仅 UI 色块与溯源**（2026-07-14 起不进合成）, color_description, priority, is_active）
  - `ark_expo_wig_colors` — 发型×发色组合三角度参考图（072）：wig_id/hair_color_id 双 FK（BigInteger，ON DELETE CASCADE）, UNIQUE(wig_id,hair_color_id), angle_photos JSON 三角度图组, cover_path, is_active。稀疏存储只存备图组合；合成时按选择匹配唯一颜色图组（参考图即目标色，取代文字/色板图上色）；「原色」用发型自身 angle_photos 不在此表
  - `ark_expo_scripts` — 话术卡库（script_type opener/demo/objection/closer/faq, track emotional/rational/identity, audience_tags JSON, evidence_points JSON；写入时禁用词强校验）
  - `ark_expo_sessions` — 试戴会话（**mode tryon/scene 双入口**——scene=佩戴实拍生成场景图跳过分析, photo_path, analysis_json 含 **internal 内部字段仅销售端可见**, matched_wig_ids JSON 全量排名, strategy_json 双轨话术（scene 模式不生成）, status pending/analyzed/generating/done/failed）
  - `ark_expo_results` — 效果图（session_id FK CASCADE, **wig_id 可空**——scene 模式为 NULL, hair_color_json 发色快照（048 起 hair_color_id/code/name/hex/swatch_path/description；历史行为 palette 旧形态）, scene_json 场景快照 key/label, reaction loved/soso, short_code 分享码, gen_ms, quality 出图档位（083，2026-07-31 起弃用新行为空）, prompt_variant 合成版本 real/soft/beauty（085；空=回落 real，085 之前的历史行全为 NULL 且当时压根没注入面部子句，故「复现同一张图」对历史行不成立））
  - `ark_expo_feedback` — 销售反馈（intent_level A/B/C/D 直通客户机会台口径, next_action）
- **MCP 网关（1 张表，051 迁移）**：
  - `ark_mcp_tokens`（053 更名，原 mcp_tokens）— 业务员个人 access token（token_hash sha256 UNIQUE 只存哈希, user_id FK ark_users.id CASCADE 归属, label 用途备注, is_active 停用即撤销, last_used_at, created_by）；`(user_id)` 索引。供入口无关的 MCP 工具鉴权→复用登录 claims 产出 current_user dict

## 客户售后管理（迁移 057-059）

- `ark_aftersales_cases`：售后主单、业务快照、证据判定、AI/措施、赔偿、审批快照、执行结果和乐观锁版本。
- `ark_aftersales_evidence`：图片/视频证据元数据和受控存储路径，随主单级联删除。
- `ark_aftersales_ai_runs`：每次 AI 输入摘要、结构化结果、模型信息、耗时和错误。
- `ark_aftersales_reviews`：主管/总监审核轮次、决定、意见、代理原因和幂等键。
- `ark_aftersales_events`：不可变审计事件；`case_id` 可空以记录 SOP 启用等模块级事件。
- `ark_aftersales_sop_versions`：原始 SOP、解析条款、问题映射、版本状态及启用信息。
- `ark_aftersales_notification_logs`：按业务事件与接收人幂等的钉钉 outbox、重试次数和下次重试时间；接收人未绑定钉钉时 ID 可空。

## PM 项目资料协作站（迁移 076_pm_hub，8 张表，2026-07-17）

- `ark_pm_projects`：咨询项目（本期仅 1 条 alibaba-ai-agent；code UNIQUE，project 维度为后续项目复用留口）。
- `ark_pm_members`：用户名白名单（username UNIQUE 非真名拼音；is_active=0 即移出名单，token 每请求回查立即失效）。
- `ark_pm_materials`：资料条目。`(project_id, name)` UNIQUE——名称即下载文件名前缀，软删时改名 `name#del{id}` 让位；delivery_type=file/offline(凭据禁传原文)/link(外部链接)；status 状态机 not_started/preparing/submitted/confirmed/not_required；phase 1-4 按清单「准备顺序」批次，与 importance 无关。
- `ark_pm_material_versions`：资料版本。`(material_id, version_no)` UNIQUE 并发上传靠约束+重试；版本号只增不复用，当前版本=未删除最大版本号；diff_status=pending/done/failed/not_applicable + diff_summary/diff_error；软删后下载端点立即拒绝。
- `ark_pm_tasks` / `ark_pm_task_materials`：任务看板（todo/in_progress/done/blocked，blocked_reason 必填）与任务-资料关联（复合主键 task_id+material_id）。
- `ark_pm_comments`：评论（2026-07-19 起**版本评论已启用**：version_id 必挂未删版本、parent_id 单层回复、软删占位；anchor_text/anchor_context 留给划线锚点评论，未启用）。
- `ark_pm_activity_logs`：审计日志（username/action/object_type/object_id/object_name 快照/detail JSON；idx (project_id, created_at)）。
- 文件存储：`REPO_ROOT/backend/data/pm/{material_id}/{uuid}{ext}`——**绝不放 uploads/**（公开静态挂载）；下载/预览一律 300s 短时效签名 URL（PM_TOKEN_SECRET 派生 HMAC）。时间戳统一北京时间（bj_now）。
## 培训速递（迁移 075）

- `ark_training_digests`：培训速递主表——基本信息（培训名/机构/讲师/日期/参训人/标签）、一句话总结、`sections_json` 结构化分区（重点/亮点/可应用点/方法/参训人点评）、draft/published 状态、阅读时长与浏览/有用计数。
- `ark_training_digest_files`：原始资料附件元数据，`storage_path` 相对 `TRAINING_STORAGE_ROOT` 私有目录；删除主表行时 service 层负责删行+清盘（不依赖 CASCADE）。077 加 `file_type`（类型 code 白名单见 app/training/schemas.py，NULL=未分类存量）+ `remark`（备注 ≤200 字）。
- `ark_training_digest_feedback`：「有用」轻反馈，`(digest_id, user_id, kind)` 唯一约束防重复。

## 工作台配置（迁移 080，2026-07-25）

- `ark_dashboard_preference`：每用户一行的工作台布局配置。`user_id`（INT UNSIGNED FK→ark_users.id ON DELETE CASCADE，UNIQUE）+ `prefs`（JSON：`{version, metrics:{hidden,order}, actions:{hidden,order}}`）+ 时间戳。卡片 key 的合法性不在库层校验——真相源是前端 `views/dashboard/cards.js` 注册表，未知 key 前端忽略（注册表增删卡片对存量配置向前兼容）。

## 内贸订单（迁移 081/082/116/127/129，2026-07-27、2026-08-17、2026-08-31、2026-09-01）

与外贸生产订单/报工**平行**的一套表。不复用 `order_product_process_progress`：那张表 FK 硬绑 `ark_production_order_items` 且是整行 0/1 流转，内贸要按数量拆批，结构不同；平行建表换取外贸链路零改动。共用的是 `process` / `process_route` / `process_route_step` / `user_process_binding`（工序、路线、工人分工内外贸同一套）。

> **116 必须停写升级，禁止滚动混部。** 升级前停止全部旧版主站/小程序写实例，确认无建单、改单、充值、报工请求后执行 116，再只启动含 116 逻辑的新版本。旧版不会维护预存款账本与逐件报工映射；迁移后若让旧实例继续写，会造成漏扣款或逐件链路断裂。回填与一致性校验在迁移内完成，任一进度累计与有效流水不一致会直接中止迁移。

> **127 同样必须在停写维护窗口升级，禁止新旧写实例混部。** 旧代码不认识分流结果与跳过事实；先停止主站、小程序和 PDA 的旧版写流量，再执行 `alembic upgrade head` 并确认唯一 head，最后只启动新版本。127 只加结构，不修改任何工艺映射、产品路线或在制明细；业务切换必须在应用验证后单独走受控 cutover。

> **129 是破坏性字段改名，也必须停写切换。** `ark_domestic_orders.order_type` 原本表示 `normal/special`，迁移中直接重命名为 `order_category`，再新增另一个语义不同的可空 `order_type` 和可空 `order_channel`；没有旧接口兼容层。结构升级、新版应用部署与 `domestic_attribute_cutover` 必须在同一维护窗口完成，旧写实例不得与新结构混用。

- `ark_domestic_customers`：内贸客户，`shop_name` UNIQUE，`custom_code` 可选且 UNIQUE，另存会员等级、省/市和 `balance` 充值余额。有订单的客户禁删只停用。
- `ark_domestic_customer_ledger`：客户充值/订单扣款/差额补扣/退款流水。`amount` 是有符号变动额，`balance_after` 是变动后快照，`business_key` 唯一；充值时将客户端 `request_id` 编码为业务键实现幂等。所有余额变动在客户行锁下完成，不允许透支。
- `ark_domestic_products`：下单选属性后 find-or-create 沉淀，`attrs_key` 使用稳定 JSON 数组编码 `product_type/craft/net_color/size/length/density/hair_style_series`，UNIQUE 即产品身份，避免属性值含分隔符时碰撞；`route_id` 按工艺映射自动绑定，可人工改绑。129 新增可空 `hair_style_series`，并将 `size/density` 放宽为可空：头套使用工艺、发长、可选网帽颜色、必填尺码和发型系列，只有 `15厘米` 头套有必填发量；发片将工艺和尺寸合并存入 `craft`，只再保存发长，其余头套专属字段均为 `NULL`。标准属性值存 `domestic_cap_*` 与 `domestic_piece_*` 字典，特单自定义值存对应 `_special` 字典。
- `ark_domestic_craft_routes`：`(product_type, craft)` UNIQUE → `route_id`。这张表是「下单人零操作」的支点：配一次，之后同工艺的新产品自动带路线。
- `ark_domestic_orders`：`domestic_no`（系统号 `DO{YYYYMMDD}-{NNN}` UNIQUE）+ `order_no`（客户订单号）+ 客户 + `order_category`（`normal=普货 / special=特单`）+ `order_type`（`sys_dict: domestic_order_type`）+ `order_channel`（`sys_dict: domestic_order_channel`）+ `status`（0草稿/1生产中/2已完工/3已发货/4已终止）+ `total_amount` + `charged_amount` + 软删。应用层要求新建和每次编辑后的最终订单类型/渠道都非空且命中启用字典；数据库列暂时可空是为了保留历史行，读取历史 `NULL` 时展示“未填写”，不做猜测或回填，编辑时必须一次补齐两项。`request_id` UNIQUE 与 `request_hash` 防止弱网重试重复建单/扣款；`next_line_no` 在订单行锁下分配 A1/A2/…，避免追加明细与改单/报工发生反向锁序；`item_count` / `total_unit_qty` 在同一订单锁下维护当前行数和合计件数。草稿不扣款，提交时一次性扣款；在制单改数量/单价只结算差额，终止或可删除时退回已扣金额。
- `ark_domestic_order_items`：一单多品，`line_no` 是订单内稳定非空序号（展示 A1/A2/…），`unit_price` 与 `order_qty` 推导明细金额。逐件码需同步物化，API 限制每单最多 50 行、合计 5000 件、单明细 2000 件。其余含四组图文要求、路线快照和明细级发货信息。
- `ark_domestic_item_append_requests`：追加明细的持久化幂等占位，`(order_id, request_id)` UNIQUE 并保存请求指纹与首次创建的 `item_id`；明细后来删除也保留占位，避免弱网旧请求再次创建和扣款。
- `ark_domestic_item_units`：每个明细数量物化为一行，`(item_id, unit_no)` UNIQUE；显示码如 `A1-01`。数量报工始终选取当前工序最小可报 `unit_no`，保证 01/02/03 后续从 04 开始。
- `ark_domestic_report_units`：报工流水到具体单件的映射，`(log_id, unit_id)` UNIQUE；127 新增 `outcome_code`，冻结该单件在 `decision` 工序选择的结果。撤销保留映射供审计，因此同一单件+工序历史上可有多条映射；「当前只有一条有效映射」由明细行锁下的服务校验保证，有效性由关联流水的 `revoked` 决定。
- `ark_domestic_item_progress`：**按数量累计，不是 0/1**。`completed_qty` 永远只统计真实报工；条件路线的通行真相为 `有效通过单件 = 有效报工单件 ∪ 有效跳过单件`，因此另派生 `skipped_qty / passed_qty / required_qty / reportable_qty`，跳过绝不伪装成完成工作。无规则的旧路线仍退化为严格线性口径。`step_order` 由 `init_item_progress` 按位置从 1 重排，不沿用路线表编号。
- `ark_domestic_report_logs`：报工流水；127 新增 `outcome_json` 保存一次 `decision` 报工的结果数量分配。`report_mode` 记录 quantity/unit；撤销是 `revoked=1` 而非删行，`request_id` UNIQUE 保证弱网幂等。计件统计唯一口径仍是 `revoked=0` 的 `report_qty` 求和。
- `ark_domestic_route_rules`：127 新增，`(route_id, process_id)` UNIQUE 且复合 FK 必须命中真实路线步骤。没有记录即 `required`；存储类型只有 `decision`（报工必须给结果分配）和 `optional`（允许下一道扫码自动绕过）。分流 JSON 由服务端校验：编码唯一且格式固定、至少两个选项、跳过目标必须是同路线后续启用工序。
- `ark_domestic_skip_logs` / `ark_domestic_skip_units`：127 新增的稀疏跳过审计。来源为 `decision / optional_bypass / manual`，按具体单件记录；`manual` 还保存数量/逐件模式、稳定请求号、操作人和 5～500 字原因。跳过不写 `ark_domestic_report_logs`，所以不产生工资。撤销触发报工时会在同一事务撤销它生成的跳过；只要任一对应单件已有更后面的真实报工，就必须先撤最早的下游实际报工。
- 共用 `process.show_in_domestic_track`：控制该工序是否出现在客户免登录进度页；内部订单页和报工不受影响。

### 迁移 129 的字典与切换口径

- `domestic_order_type` 的稳定编码为 `first_order/repurchase/return_order/supplementary/after_sales_remake`，标签分别为首单/复购/返单/补单/售后重做；`domestic_order_channel` 为 `wechat/phone/exhibition/offline_visit/other`，标签分别为微信/电话/展会/线下拜访/其他。
- 应用层对所有内贸属性、订单类型和渠道的字典 `code` 做大小写精确匹配；MySQL 查询显式转二进制比较，并在取行后再次核对原始字符串，不能依赖 `sys_dict.code` 的 `utf8mb4_unicode_ci`。特单输入与标准值仅大小写不同时仍按自定义值处理；唯一索引竞争不得回收仅大小写不同的行。
- 头套标准字典为 `domestic_cap_craft`、`domestic_cap_net_color`、`domestic_cap_size`、`domestic_cap_length`、`domestic_cap_density`、`domestic_cap_hair_style_series`；发片标准字典为 `domestic_piece_craft_size`、`domestic_piece_length`。特单值使用相同 type 加 `_special`，只允许在特单保存事务中按当前可见属性创建和复用；普货只接受启用的标准字典项。
- 特单自定义属性与订单/草稿同事务保存，失败不残留字典项；自定义工艺没有映射时才在同一事务建立默认路线映射，头套使用“头套网帽（递针）”、发片使用“发片网底（递针）”。仅新建映射时校验默认路线；已有映射直接沿用且不被默认路线覆盖，唯一键竞争后读取并保留数据库中的胜方映射。SQLite 下单和追加明细在任何读后写判断前使用 `BEGIN IMMEDIATE` 取得写者槽位，避免双连接同时创建特单字典、映射或重复明细序号；MySQL 继续使用行锁和唯一键收敛逻辑。
- `python -m scripts.domestic_attribute_cutover` 默认只读预检；执行必须同时显式传入 `--apply --confirm-writes-stopped DOMESTIC_WRITES_STOPPED`，否则拒绝。它保留所有 `_special` 字典与特单映射，不更新/删除 `ark_domestic_products`、`ark_domestic_orders`、`ark_domestic_order_items` 或属性/路线快照；必须与 129 结构升级和新版应用部署处于同一停写维护窗口，并先由运维真实停止所有内贸写入、等待在途事务排空。
- 本次迁移和切换不清理历史订单。即使业务确认未来可以全部清空，也必须作为后续单独授权的破坏性操作执行，不能夹带在 Alembic 或属性切换命令中。

## 采购节大屏（迁移 084/087，2026-07-30、2026-08-04）

- `ark_festival_events` — 大屏事件流（摘要屏滚动记录 + 弹窗触发源）：event_type/level(L3插播条|L4全屏弹窗)/subject_type(person|team|camp|company)/subject_id/subject_name/amount/detail，**dedup_key UNIQUE 幂等**。迁移 087 增加钉钉投递时间、租约、下次重试、次数和最近错误；成功后才标记完成，失败按 1/2/4/8/16/30 分钟退避，15 分钟僵尸租约可接管；迁移时历史事件全部标记已发送，运行时首轮基线再屏蔽尚未落库的旧事实，避免上线补发旧弹框。
- `ark_festival_states` — 排名、里程碑、当日连击与日报投递的持久状态。首轮观察只建立基线、不补发历史；后续用前后快照识别重复名次上升、149 目标每 10%、阵营 110% 起每 10% 超额和同日第 2 单起的连击。日报用 `delivery:daily:YYYY-MM-DD` 主键 claim 防止 17:30 cron 与分钟恢复任务重复发送。

## 名片管家（迁移 086，2026-08-01）

业务员电子名片（`leshine.work/card/<slug>/`）的口令层。口令 = 客户自己的邮箱或 WhatsApp 号，归一化（邮箱小写去空格 / 号码纯数字，<5 位数字视为无效）后存查询列——录入与解锁两侧共用 `service.normalize_passcode` 同一入口，防「录得进、解不开」。

- `ark_card_salespersons` — 业务员档案：`slug` UNIQUE（**与印刷二维码绑定，禁改**，086 种子 ginny/janny/katy/sylvia）、name/title/email/whatsapp（可空待补）/intro/links_json/is_active。
- `ark_card_customers` — 客户档案：`email_norm`/`whatsapp_norm`（各自建索引，即口令查询口径，至少一个非空由端点校验）、display_name（解锁问候语）、expo_code 届次、remark 内部备注（不对客户展示）、created_by（ark_users.id，无 FK 随 expo 先例）。同口令重复建档时 unlock 取最新一条（现场录重是常态）。
- `ark_card_entries` — 沟通纪要：entry_type text/image、title/content、attachment_path（`uploads/card/` uuid 命名，公开静态可读）；客户凭口令可见，FK CASCADE 随客户删除。
- `ark_card_inquiries` — 客户询盘：contact 原文 + message、customer_id 命中档案时回填（FK SET NULL）、status new/handled 驱动跟进。

## 设计部 AI 生图工作台（迁移 089/091/103/115，2026-08-05）

迁移 `089_design_image_studio` 在 `ark_ai_call_logs` 增加 nullable JSON `usage_detail`，并建立五张领域表。迁移采用存在性检查以收敛已有对象；`downgrade()` 刻意不删审计数据或表，回滚走权限/Preset 开关，结构清理由单独审计迁移完成。

- `ark_design_image_sessions`：owner 会话；`owner_user_id → ark_users.id RESTRICT`。索引 `idx_di_session_owner_updated(owner_user_id, updated_at)`。
- `ark_design_image_messages`：用户/助手消息；`session_id → sessions.id RESTRICT`。迁移 `103_di_message_interact` 增加 nullable `client_request_id VARCHAR(64)` 与 `interaction_json JSON`；`uq_di_message_session_client_request(session_id, client_request_id)` 让无 job 的确认轮次也能按会话幂等。`interaction_json` 只保存输出方式确认所需的结构化状态和最小请求快照：`output_mode_confirmation` 必须含 `pending|resolved` 状态、`count`、`item_kind=angle|variant` 与最小附件请求；HTTP 序列化使用字段白名单，不返回提示词快照、Provider 参数或内部错误。索引 `idx_di_message_session_created(session_id, created_at)`。
- `ark_design_image_assets`：私有上传与输出元数据，保存相对路径、MIME、字节数、宽高、SHA-256、draft/attached 状态和软删除时间。JPEG/PNG/WebP 原图经清理后保存；单页 PDF 与 SVG 刀版在入口转成白底 PNG 预览，原始文档不落库。`session_id → sessions`、`message_id → messages`、`source_asset_id → assets`、`created_by → ark_users` 均为 RESTRICT。索引 `idx_di_asset_session_created(session_id, created_at)`、`idx_di_asset_draft(status, expires_at)`。
- `ark_design_image_jobs`：状态、输入/配置快照、租约、用量、计费确定性及错误。`owner_user_id → ark_users.id`、`session_id → ark_design_image_sessions.id`、`request_message_id/response_message_id → ark_design_image_messages.id`、`base_asset_id/output_asset_id → ark_design_image_assets.id`、`ai_call_log_id → ark_ai_call_logs.id`、`retry_of_job_id → ark_design_image_jobs.id` 均为 RESTRICT；`uq_di_job_owner_idem(owner_user_id, idempotency_key)` 保证用户范围幂等。索引 `idx_di_job_claim(status, lease_expires_at, created_at)`、`idx_di_job_owner_day(owner_user_id, created_at, status)`、`idx_di_job_session_created(session_id, created_at)`。
- `ark_design_image_job_assets`：任务参考图顺序；`job_id → jobs.id CASCADE`、`asset_id → assets.id RESTRICT`，唯一约束 `uq_di_job_asset(job_id, asset_id)`，检查约束 `ck_di_job_asset_position(position >= 0)`，索引 `idx_di_job_asset_position(job_id, position)`。
- `ark_design_image_prompt_templates`：迁移 091 建立的提示词模板，保存 category/name/content/options/is_active/sort。迁移 115 将历史“包装效果图”分类改为“LOGO生成包装效果图”，并按 `(category, name)` 幂等新增“刀版图生成包装效果图 / 通用刀版包装效果图”；不覆盖现有模板正文或参数配置。该迁移为 forward-only 数据变更，downgrade 不回改用户可能已编辑的数据。
- `ark_design_image_library_assets`：迁移 091 建立的公/私参考图库；public 全员可见、private 仅 owner 可见，上传仅支持 JPEG/PNG/WebP 图片。

关联真相链为 `request_message → job → ai_call_log/output_asset/response_message`；一条用户消息可对应 1 个组合图 root job，或 2～4 个共享该消息的独立 root jobs。输出资产的 `source_asset_id` 指回显式编辑基准，参考图顺序在 job_assets 中冻结。用量不另建汇总表：`/usage` 从 jobs LEFT JOIN `AiCallLog` 派生，job token 快照优先、日志 token 兜底。成本只有配置了调用时的 rate-card 快照且细分 usage 可计算时才为估算值，否则 `billing_certainty=unknown`。

每日额度按 `Asia/Shanghai` 自然日统计该用户当天所有已接受 job；clarification 不建 job、不计额度，组合图计 1 次，N 张独立图计 N 次，成功、失败和重试都计数。提交和 worker claim 都遵循 `ark_users owner → ark_design_image_jobs` 的统一锁序；提交在 owner 锁内一次性检查整批额度与幂等，worker 在每用户 running 上限内领取。SQLite 自动化只能验证语义，MySQL 两连接下的 InnoDB 等待、当前读和 `FOR UPDATE SKIP LOCKED` 仍是上线外部门禁。

## 客户产品效果图门户（迁移 102/104，2026-08-07）

迁移 `102_customer_image_portal` 建立八张领域表：产品、产品素材、产品选项、选项值、邀请、邀请产品关联、邀请素材和生成记录。产品素材是稳定副本，不引用可变图库文件；cover 是单槽，reference 是按 `position` 排序的多槽。替换、下移或删除只把旧行标为 retired，历史 generation 继续通过冻结的素材 ID 读取当时版本，不物理覆盖旧文件。

| 实际表名 | 归属与核心字段 | FK 删除策略、唯一与检查约束 |
|---|---|---|
| `ark_customer_image_products` | `created_by` 是模板管理员；`config_version/is_published/sort` 驱动发布目录 | `created_by → ark_users.id RESTRICT`；检查 `config_version > 0` |
| `ark_customer_image_product_assets` | 产品稳定 cover/reference 副本；`role/position/retired_at` 表示当前或历史槽位 | `product_id → products CASCADE`；检查 role 仅 cover/reference、`position >= 0`；当前多 reference 的连续唯一位置由产品行锁内 service 维护 |
| `ark_customer_image_product_options` | 产品内的 `key/label/control_type/required/default_value/sort` | `product_id → products CASCADE`；唯一 `(product_id, key)` |
| `ark_customer_image_option_values` | 选项值及隐藏 `prompt_fragment`、颜色/Pantone、启停和顺序 | `option_id → product_options CASCADE`；唯一 `(option_id, value)` |
| `ark_customer_image_invites` | `created_by` 是业务 owner；冻结客户/OKKI owner；只存 `token_hash/token_suffix`；额度为 `quota_total/quota_used` | `created_by → ark_users.id RESTRICT`、`current_logo_asset_id → assets RESTRICT`；`token_hash` 唯一；检查总额度为正、已用非负且不超过总额、结束晚于开始 |
| `ark_customer_image_invite_products` | 邀请获准产品集合 | `invite_id → invites CASCADE`、`product_id → products RESTRICT`；唯一 `(invite_id, product_id)` |
| `ark_customer_image_assets` | 邀请归属的 LOGO/生成结果，`deleted_at` 是保留清理边界 | `invite_id → invites RESTRICT`；检查 asset type 仅 logo/generated；当前 LOGO 由 invites 的反向 RESTRICT FK 保护 |
| `ark_customer_image_generations` | owner 继承 `invite.created_by`；冻结产品、素材、选项、提示词、参数与计价；`quota_refunded_at` 保证最多退款一次 | invite/product/logo/output/AI call log 均为 `RESTRICT`；唯一 `(invite_id, request_id)`；检查 `claim_count/provider_attempt_count >= 0` |

邀请只存定长 SHA-256 token hash 与末 6 位 suffix，`ark_customer_image_invites` 冻结客户外部 ID/显示名、创建人、有效期和正数额度。非管理员查询必须以 `created_by` 为数据边界。额度以邀请行的 `quota_total/quota_used` 为原子账本，并由 generation 与 `quota_refunded_at` 留下审计依据；提交在邀请锁内检查 `(invite_id, request_id)` 幂等键、当前配置和剩余额度，再一次性增加已用额度并创建 generation，避免重复请求重复扣减。

`ark_customer_image_generations` 冻结产品/LOGO/reference、公开选项、隐藏提示词、计价与执行参数。迁移 `104_ci_generation_snapshots` 增加 nullable `requirement_snapshot` 与非空 JSON `parameters_snapshot`：补充要求单独冻结去除首尾空白后的原文；参数快照只供 worker 使用，保存尺寸、质量、Provider/config version、下载白名单等非公开参数。102 已建立的 `provider_attempt_count` 仅统计真实 Provider 请求次数，不能与数据库领取次数混用。`option_snapshot` 只保存按产品定义顺序排列的客户安全选择项，`pricing_snapshot` 只保存调用时 rate card，`prompt_snapshot` 保存最终隐藏提示词。公开 API 不返回补充要求、提示词、Provider/config、rate card、token/hash 或磁盘路径。

worker 通过 queued/running、lease 与 claim 字段实现可恢复领取。失败只在明确属于可退款分类且尚未 `refunded_at` 时原子退款一次；不能证明未计费的 Provider 失败不退款。`ark_customer_image_assets.deleted_at` 是邀请 LOGO/输出的软删除边界；邀请过期满保留期且不存在 queued/running generation 时才进入清理，数据库先提交软删除，再按记录的精确原图/缩略图路径 best-effort 删除，文件失败由下一次任务重试。

## 客户拍摄素材交付与门户（迁移 114，2026-08-14；业务预览无新迁移，2026-08-17）

- `ark_customer_media_batches`：一条设计任务一个交付批次，保存客户与申请人快照、审核状态、修订号、乐观锁和发布/下架时间；`task_id` 唯一。
- `ark_customer_media_assets`：批次图片/视频私有原件元数据，存储适配器与 object key 唯一；`deleted_at` 是软删除边界。
- `ark_customer_media_reviews`：送审、通过、退回、下架等不可变审计记录，按批次与时间索引。
- `ark_customer_portal_accounts`：一个 customer_id 一个门户账号、登录邮箱唯一；只保存 bcrypt 密码哈希和会话失效版本。
- `ark_customer_portal_sessions`：只保存会话 token 的 SHA-256、版本、IP/UA、过期和撤销时间；账号删除级联会话。
- `ark_customer_media_downloads`：客户下载素材审计，素材和账号均为 RESTRICT，避免历史记录悬空。

业务员客户切换与预览复用以上表，不新增副本或迁移。客户范围实时联结 active `ark_user_external_bindings(provider='okki')` 与当前 `customer_commission_snapshot.salesperson_id`；门户内容仍由 `ark_customer_media_batches.status='published'` 和素材 `deleted_at IS NULL` 决定，因此业务预览与客户实际可见内容保持同一真相源。

## 客户 AI 方案对话（迁移 100，2026-08-09）

- `ark_ai_chat_sessions`：owner 会话；`owner_user_id → ark_users.id RESTRICT`，索引 `idx_ai_chat_session_owner_updated(owner_user_id, updated_at)` 支撑最近会话分页。
  - 迁移 `124_ai_chat_modes` 新增可空 JSON `mode_snapshot`：首次发送时保存固定方式 ID、显示元数据、完整规则正文及 SHA-256 版本；已发送会话不可更换方式，重试/历史预览均读取此快照。原有会话保持 NULL，仍为普通聊天；内置规则不复用附件表。
- `ark_ai_chat_messages`：用户/助手 Markdown 消息，状态为 `completed/streaming/stopped/failed`。`session_id → ark_ai_chat_sessions.id RESTRICT`，`ai_call_log_id → ark_ai_call_logs.id RESTRICT`；`uq_ai_chat_message_session_request(session_id, request_id)` 保证会话内发送幂等，`uq_ai_chat_message_session_id(session_id, id)` 是复合外键目标。助手消息用 `reply_to_message_id` 指向触发它的用户消息；重试助手消息用 `retry_of_message_id` 指向原 stopped/failed 助手消息。两条自引用均通过 `(session_id, message_id)` 复合 FK 限定在同一会话，禁止跨会话串链。
- `ark_ai_chat_attachments`：私有附件元数据与抽取正文；`session_id → ark_ai_chat_sessions.id RESTRICT`、`created_by → ark_users.id RESTRICT`。发送前 `message_id=NULL/status=draft`，发送事务绑定用户消息后为 `attached`，状态值域为 `draft/attached/failed`；`fk_ai_chat_attachment_message_session(session_id, message_id)` 强制附件只能绑定同一会话内的消息。

owner 真相在 session；消息访问必须经 session 的 `owner_user_id`，附件访问同时校验 session owner 与 `created_by`，跨 owner 与不存在统一 404。数据库 FK/复合 FK 保证引用边界，service 在绑定附件的同一事务中再校验 owner、session 与 draft 状态。

## 薪资计算（迁移 092，2026-08-06）

一次建 10 张表。所有引用 `ark_users.id` 的列（`user_id` / `created_by` / `confirmed_by` / `modified_by`）都是 `INT UNSIGNED`——目标列是 unsigned，模型侧靠 `USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")` 对齐，SQLite 测试库回落普通 Integer。金额统一 `DECIMAL(12,2)`、工时 `DECIMAL(8,2)`（`day_hours=7.83` 要两位）、天数 `DECIMAL(6,2)`。

**PII 双列**：身份证与银行卡各存 `_cipher`（AES-256-GCM，随机 IV）+ `_hash`（HMAC-SHA256）。唯一约束与社保/公积金导入的匹配 JOIN 都建在哈希列上——随机 IV 的密文既不能做唯一索引也无法跨表比对，这是双列存在的唯一理由。

主数据（M1 已用）：
- `ark_salary_employee_profile` — 员工档案。`emp_no` UNIQUE（服务端去空格去前导零，3 与 003 归一）、`id_card_hash` UNIQUE、`bank_card_hash` **只建普通索引 `idx_salary_profile_bank_card`**（迁移 093 从 UNIQUE 降级：夫妻/亲属共用一张卡代发是真实存在的，UNIQUE 会让第二个人永远建不了档案）、`user_id → ark_users.id SET NULL`。`dept_group_override` 与 `base_salary_override` 是两个「按人覆盖」列，优先级高于映射表与职级表。`payroll_included` / `fund_included` 控是否进工资表与公积金。
- `ark_salary_dept_mapping` — 明细部门 → 汇总大部门，`dept_detail` UNIQUE。
- `ark_salary_grade_table` — 职级薪级表，版本化：`uk_salary_grade_ver(scheme, grade_code, effective_from)`。`manage` 赛道取 `std_salary`，其余取 `base_salary`。
- `ark_salary_rule_param` — 规则参数 KV，版本化 `uk_salary_param_ver(param_key, effective_from)`，值一律按字符串存、由 `value_type` 决定解析。注意 `full_month_days=31`（日工资折算分母）与 `mid_month_weight_base=30`（月中入离职权重基数）是两个不同参数，不是笔误。
- `ark_salary_change_logs` — 调薪/调级/转正台账，`employee_id → profile CASCADE`。

批次与计算（M2~M4 落地，表已建）：
- `ark_salary_period` — 月度批次，`year_month` UNIQUE，`status_version` 是批次级乐观锁，`param_snapshot` 在锁定时冻结规则参数。
- `ark_salary_attendance` — 考勤汇总，`uk_salary_attendance_pe(period_id, employee_id)`，`raw_payload` 留钉钉原始返回便于对账。
- `ark_salary_insurance_import` / `ark_salary_fund_import` — 社保、公积金导入行。`employee_id` 可空 + `SET NULL`：匹配不上的行也要留在库里让 HR 看到，不能静默丢弃；`match_status` 与 `idx_*_hash(period_id, id_card_hash)` 支撑二次匹配。
- `ark_salary_record` — 工资明细行，`uk_salary_record_pe(period_id, employee_id)` + `row_version` 行级乐观锁。三类列口径不同：单字段引擎列（底薪/工龄/全勤/社保/公积金/缺勤，减项存负数与 HR 源表一致）、`*_auto` / `*_manual` / `*_final` 三元组（奖励/绩效/其他/补贴，人工覆盖不抹掉引擎值以便追溯）、纯手动列（个税、税后实发）。`snap_*` 是批次锁定时冻结的档案快照——工资条必须能复现发放当时的部门/职务/银行卡，档案后续变更不得回溯改写历史。

`downgrade()` 按 `_TABLES` 的反建表序 drop。**教训**：在已 apply 的迁移里改表名会让它自己的 downgrade 失效（库里是旧名，drop 报 1051 并卡在半途），改名后必须先手工把库回滚干净再重跑。

**迁移 093（2026-08-06）**：`bank_card_hash` 由 UNIQUE 降级为普通索引，见上。

**迁移 094 / 095（2026-08-07）**：`ark_salary_period_event` 批次事件时间线；`ark_salary_period.workday_source` 工作日数来源标记（`weekday_auto` / `needs_review` / `manual`）。自动推算只按周一~五数、不含法定节假日与调休，标记落在批次行上前端才拿得到——只写进事件 payload 等于发不出去，而 2 月批次的 20 天是所有月中入离职人员缺勤扣款的分母。

**迁移 096（2026-08-07）**：`dingtalk_userid` 的普通索引升为 UNIQUE（`uk_salary_profile_dingtalk`）。两份档案共用一个 userid 时考勤同步会静默丢掉其中一个人：钉钉按 userid 只回一条，字典推导让后来者覆盖前者，而 `source_count == synced`、`failed == 0`、`unbound` 为空——**所有告警指标全绿**，被覆盖的人在失败清单、未绑定清单、考勤列表里都不出现，M3 只能按全勤给他发钱。UNIQUE 允许多个 NULL，所以没绑钉钉的人不受影响；空串不同（彼此相等），所以升级脚本先把空串归一成 NULL，否则约束建不上而 MySQL DDL 不可回滚。service 层另有一道同名检查，管的是 096 之前的存量数据和绕过 ORM 的写入路径。

PII 密钥 `ARK_SALARY_ENCRYPTION_KEY` / `ARK_SALARY_HASH_KEY` 在 `backend/.env`，**未配置时 `pii.py` 直接抛 `SalaryKeyNotConfigured`，不回落占位密钥**。开发机与生产共用同一套 RDS，两边必须配完全相同的值——值不同则同一张身份证算出不同 HMAC，唯一约束形同虚设、M2 社保导入按哈希匹配会全空。

**迁移 098（2026-08-07，请假自动拉取）**：`ark_salary_attendance.leave_source`——请假四列（事假/病假小时、年假天/余额）的归属标记：`NULL`=从没写过（同步可填）/ `dingtalk`=同步在管（重同步刷新）/ `manual`=人工改过（同步永远让路）。钉钉权限 `qyapi_get_attendance_data` 开通后请假走 `getleavestatus` 明细接口自动填充，这列就是「人工值不被同步覆盖」红线在自动拉取时代的精确化。

**迁移 097（2026-08-07，M3 计算引擎前置）**：四个新列，全部可空/带默认、纯新增。`ark_salary_employee_profile.special_calc`（特殊计薪：不发全勤、工龄按钉值或 0——姜妮妮/刘德明类，§9.5 的 HR 确认标记）与 `seniority_override`（工龄手动钉值，刘德明 3 月工龄 1000 规则复原不了）；`ark_salary_attendance.due_days_manual`（应出天数手动钉值，李晓雨 21.75；独立成列是因为同步每轮重写 `due_days`，钉值混在里面会被冲掉）；`ark_salary_record.calc_flags`（引擎判定标记 JSON：negative_net / guaranteed_topup / mid_month_weighted / absence_clamped 等，异常面板的记录级检查直接读它，不必每次重算推导过程）。

## 订单经营 AI 简报（迁移 109，2026-08-12）

- `ark_order_intelligence_brief_jobs`：持久化后台简报任务，`owner_user_id → ark_users.id CASCADE`，状态为 `queued/running/succeeded/failed`。`active_key` 在活动期固定为 `user:{ark_user_id}` 并建唯一约束，终态置 NULL，从数据库层阻止同一用户双击、多标签页和并发提交重复调用 AI。任务冻结提交时的日期、focus 与数据范围快照，并保存简报内容、来源、证据及失败原因。`idx_oi_brief_owner_created` 支撑用户历史，`idx_oi_brief_status_updated` 支撑状态与超时扫描。

## 运行与自动化治理（迁移 110 / 111，2026-08-12）

- `ark_operation_audits`：运行中心任务控制的追加式审计，保存操作人、来源 IP、实例 hostname、job/action、requested→accepted/rejected/failed 结果与安全摘要。控制前必须先写 requested；审计库不可用则拒绝动作。
- `ark_scheduler_job_policies`：按 `(instance_id, job_id)` 保存暂停策略。scheduler 启动注册任务后重新应用 paused 行，避免应用重启把人工暂停静默恢复；多实例之间不互相污染。

迁移 111 增加跨进程观测事实：

- `ark_job_runs`：按实例、任务与计划时间的 SHA-256 唯一键幂等保存 running/success/failed/missed/skipped；异常只保存类型摘要，不落原始消息与 traceback。默认保留 90 天，调度实例重启时会把本机遗留 running 标成失败，避免永久“执行中”。
- `ark_runtime_instances`：按 `(service_id, instance_id)` 保存实例最新状态、版本、启动/活动/心跳时间与能力依赖。心跳凭证绑定服务和实例；超过失联阈值降级，长期失联自动退役，恢复上报可重新激活。
- `ark_runtime_heartbeats`：采样保存实例心跳历史，默认保留 7 天，避免高频上报无限增长。

## 发货检验（迁移 128，2026-09-01）

- `ark_shipping_inspections`：每个 OKKI 出库单一行，`outbound_record_id` 唯一键（存业务库出库单 id 字符串，不建跨库外键）；冗余 `outbound_no / customer_name` 便于检索；`status` 为 `draft/submitted`，提交时落 `photo_count / submitted_at / submitted_by`（BigInteger 存 ark_users.id，未建 FK——ark_users.id 为 INT UNSIGNED，类型不匹配）。
- `ark_shipping_inspection_photos`：`inspection_id → ark_shipping_inspections.id CASCADE`；`item_id` 为出库明细 id 字符串、NULL 表示整单照片；`file_path` 存相对路径（私有存储根 `SHIPPING_INSPECTION_STORAGE_ROOT`，鉴权端点读图，不挂静态目录）。
- 数据源 `lsordertest.okki_outbound_records / okki_outbound_record_items` 为 OKKI 同步只读镜像（2026-09-01 已实库摸底，3966 单 / 14125 明细）：单头单号 `serial_id`、出库时间 `warehouse_invoice_time`、客户 `company_name`、制单人 `create_user_name`；明细数量 `outbound_count`、单位 `product_unit`、规格 `product_model`、SKU `sku_code`。**明细关联单头走 `outbound_invoice_id` 桥**（两表都有此列，全量命中）；`items.outbound_record_id` 是 OKKI 侧另一实体 id，与 `records.id` 完全不相交，不能 join。自适应候选映射见 `app/shipping_inspection/outbound_service.py`。

## 已退役：智能获客旧表（迁移 099，迁移 126 删除）

> 以下仅保留迁移 126 之前的历史口径用于审计，不得用于新代码或运维。`ark_sales_companies`、`ark_sales_contacts`、`ark_sales_research_runs`、`ark_sales_research_facts` 已删除；当前结构见本文顶部“统一客户经营库”。

<!-- 迁移 126 前的旧智能获客表仅保留在源码中用于历史审计。

主动获客是独立领域，不写入只读 OKKI `lsordertest.customer_info/customer_contacts`，也不复用入站询盘 `ark_customer_opportunities`。候选被人工确认后，后续阶段才允许投影成销售机会。

- `ark_sales_target_profiles`：本公司产品能力、优势、目标国家/行业/角色和排除条件；`profile_key=default` 唯一。
- `ark_sales_search_jobs`：异步 Agent 任务、冻结画像、补充条件、任务幂等键、批次回执、统计、15 分钟租约和失败原因；迁移 117 增加 `public_pool_deduplicated_count`，单独记录命中当前 OKKI 公海而被阻止入开发池的候选；只保存 `lease_token_hash`，原始租约只在领取响应中返回一次；状态 `pending/running/completed/failed`。
- `ark_sales_companies`：候选公司主档；`normalized_domain` 非空唯一，是公司身份真相源，显示名称不参与去重；状态 `candidate/approved/rejected`；确认后 `owner_user_id → ark_users.id SET NULL`。
- `ark_sales_search_results`：任务与公司多对多来源快照；`(job_id,company_id)` 唯一，保留来源 URL、采集时间、原始载荷、排名和本次评分。
- `ark_sales_contacts`：公司联系人；`(company_id,identity_key)` 唯一，邮箱优先作为身份，保存 `unknown/valid/risky/invalid` 验证状态及来源证据。
- `ark_sales_research_runs`：一次企业研究的摘要、触达角度、风险、执行方/模型、状态与公司范围幂等键。
- `ark_sales_research_facts`：原子事实；每条必须有来源 URL、采集时间和 0~1 置信度，`(run_id,fact_hash,source_url_hash)` 唯一。

所有表具备 `created_by/updated_by/created_at/updated_at/deleted_at` 审计字段。M1 只覆盖搜索、联系人和研究，不建邮件发送、回复或 WhatsApp 外发表。

-->

## AI Agent 控制面（迁移 118，2026-08-20）

- `ark_agent_profiles`：不可变 Profile 版本，冻结 Runtime、模型 Preset、系统提示词与哈希、Skill 清单、工具白名单、预算/策略和输出 Schema；`(profile_key,version)` 唯一。
- `ark_agent_sessions`：用户围绕客户、订单或 SearchJob 的业务会话；owner 与 Profile 均为 `RESTRICT`，业务对象用 `context_type/context_id` 软引用。
- `ark_agent_runs`：单次执行、用户范围幂等键、触发方式、冻结权限上下文、租约哈希、重试次数、步骤/Token/成本和终态错误。`(owner_user_id,idempotency_key)` 唯一；`idx_agent_run_claim` 支撑 Worker 原子领取。
- `ark_agent_events`：每个 Run 的追加式事件账本；`(run_id,sequence_no)` 与 `(run_id,event_id)` 双唯一保证连续顺序和提交幂等。`payload_json` 只保存标准化脱敏载荷，`raw_payload_cipher` 为可选密文。每日 03:50 仅清空超过 `AGENT_RUNTIME_RAW_EVENT_RETENTION_DAYS` 的原始密文，标准事件和哈希不删除。
- `ark_agent_artifacts`：通过 Profile Schema 与 evidence policy 校验的结构化成果；`(run_id,artifact_type,content_sha256)` 唯一，人工决策为 `draft/accepted/rejected`。

迁移同时给 `ark_customer_actions` 增加 `source_type/source_run_id/source_fingerprint/policy_version/evidence_status/generated_at`。
规则刷新沿用稳定 fingerprint 幂等，禁止覆盖 `done/dismissed/snoozed` 用户事实；DSH 复购成果仅在人工接受、归属匹配且原行动仍为 `pending` 时投影。`downgrade()` 会删除控制面五表及以上行动来源列，因此生产回滚应优先关闭 Feature Flag 并保留 118 结构，不执行破坏性 downgrade。

### 已退役：公海背调旧表（迁移 106/113，迁移 126 删除）

> 以下为历史设计记录。`ark_sales_research_subjects`、`ark_sales_public_pool_tasks`、`ark_sales_deal_assessments` 等旧表和双主档逻辑已删除；当前公海、研究任务、资格审核及机会统一使用 `customer_id`。

<!-- 迁移 126 前的旧公海表仅保留在源码中用于历史审计。

迁移 106 只在方舟库建表；`lsordertest` 仍由 `BusinessPoolGateway` 用只读 SQL 查询，不建立跨库外键，也不回写 OKKI。

- `ark_sales_research_subjects`：统一研究主体。OKKI 客户用 `external_key=okki:{company_id}`，智能获客高分候选用 `external_key=lead_company:{company_id}`，并由 `(source_system,source_customer_id)` 双重唯一约束；允许在尚无官网域名时进入背调。保存初筛档位、信息完整度、历史订单/画像评分摘要和来源快照哈希。
- `ark_sales_public_pool_batches`：每日抽样批次。`idempotency_key=日期+策略版本+每档配额+规范化画像哈希（有画像时）`，保存生成时公海审计快照、冻结的 `audit_snapshot.profile_conditions`、T1/T2/T3 配额和实际选取数；画像条件变化会创建独立批次，同画像重试保持幂等。
- `ark_sales_public_pool_tasks`：逐客户背调任务。状态 `pending/running/completed/failed/skipped`，具备 15 分钟租约；人工审核状态与 Agent 执行状态分列，确认后可关联 `ark_customer_opportunities`。
- `ark_sales_public_pool_tasks`：迁移 113 增加 `gate_status` / `gate_snapshot` 两阶段止损；只有行业门控通过才允许昂贵的深入背调，无关客户在门控提交时直接完成。
- `ark_sales_deal_assessments`：后端重算的 A/B/C/D 成交研判。业务质量分、成交分、证据置信度和优先分分开保存；迁移 113 增加行业相关性与停止原因、调研深度、社媒活跃画像、企业知识不可变版本引用、客户类型/采购阶段/体量/正负信号，以及真实性、采购潜力、需求准备度、专业度、产品市场匹配、增长、决策权、交易合规、互动和战略价值十维资格研判。后端另算已评分维度的归一资格分与证据覆盖率。行业无关由 schema 与 service 双层清空社媒关系、风险、资格研判、正向得分、联系人、供应商判断和触达内容。
- `ark_sales_contacts` / `ark_sales_research_runs`：新增 nullable `subject_id`，并将原 `company_id` 改为 nullable，使无官网的 OKKI 主体也能复用有来源联系人与原子事实模型。两种主体至少命中一种由服务层保证。

T1 = 当前公海且有历史订单；T2 = 无历史订单但有企业邮箱、独立站或非 WhatsApp 业务社媒；T3 = 不满足 T2、但有私人邮箱、电话或 WhatsApp；其余进入冷藏区。每日默认每档选 20 条，其中 16 条按确定性质量排序、最多 4 条固定种子探索，180 天内已进入有效任务的客户不重复抽取。

手工与定时的 v3 默认画像先取满足任一成交条件的 T1 客户：`成交数 >=2 且累计金额 > USD 1500`、`任一单 > USD 1000`、`全部历史成交单名均为 Sample/样品/样单`；再同时限制历史成交额 Top 10 国家、Instagram/Facebook/电话至少一项、历史产品包含天才/平型/贴发任一关键词、至少 60 天未下单、客户资料至少 30 天未更新。成交单沿用订单经营分析有效口径（已结束，或终止且已结清；排除 `trail` 含“个人”），金额、最近下单、样单及产品均只从该口径计算。联系方式排序为 Instagram → Facebook → 电话。同步业务库没有独立跟进记录表，`customer_info.update_time` 仅作为最近跟进的代理字段；空值按从未跟进纳入，批次快照通过 `followup_time_source` 明示该口径。

2026-08-25 已对 `lsordertest` 做只读列检查并以 `LIMIT 1` 执行完整画像 SQL，确认 `customer_info.update_time`、`okki_order_items.product_cn_name` 及画像查询链路可用；该检查不写入同步业务库。

智能获客候选在创建 `ark_sales_companies` 前，以归一化官网域名（无官网时可用非免费企业邮箱域名）精确查询当前 OKKI 公海，命中即拦截；未命中且画像匹配分 `>=70` 时创建 `lead_company` 研究主体和 T2 形态任务，继续复用 `ark_sales_deal_assessments` 的结构化背调结果。

-->

## 企业知识库（迁移 101/105/112，2026-08-09 至 2026-08-13）

- `ark_knowledge_libraries`：知识库主表，软删除；迁移 105 增加 `category VARCHAR(16) NOT NULL`，值为 company/department/personal，存量行回填 company 后再收紧为非空。
- `ark_knowledge_library_members`：资源 ACL，`(library_id,user_id)` 唯一，角色为 viewer/editor/reviewer/admin。
- `ark_knowledge_documents`：目录和文档树；`draft_revision_id`、`published_revision_id` 与 `pending_approval_id` 分开保存，避免草稿覆盖线上内容。
- `ark_knowledge_revisions`：不可变 Tiptap JSON 和派生纯文本，`(document_id,version_no)` 唯一。
- `ark_knowledge_approval_requests`：审批绑定不可变 revision；`(document_id,pending_slot)` 唯一，pending 时 slot=1，approved/rejected/cancelled 终态置 NULL，数据库层阻止并发双待审。知识库或节点软删除时关联待审批进入 cancelled。
- `ark_knowledge_audit_logs`：成员、编辑、审批和 MCP 读取的追加式安全审计。
- `ark_knowledge_assets`：私有图片元数据和相对存储路径；状态为 temporary/attached，临时图带过期时间。
- `ark_knowledge_revision_assets`：修订与图片的不可变有序引用，`(revision_id,asset_id)` 唯一；图片不能跨库附着。
- `ark_knowledge_ai_profiles`：AI Preset、两类业务提示词、安全与配额配置；每次更新递增 `config_version`。
- `ark_knowledge_ai_profile_sources` / `ark_knowledge_ai_profile_targets`：配置允许读取的来源库及适用目标库；两表均按 `(profile_id,library_id)` 唯一。
- `ark_knowledge_ai_profile_logs`：配置 create/update/delete 追加式审计，不保存知识正文。
- `ark_knowledge_ai_jobs`：冻结基准修订、配置/Preset 指纹、状态、租约、确定性校验与独立语义审计结果及应用修订；`ai_call_log_id` 和 `verification_ai_call_log_id` 分别关联生成与语义审计调用日志，`(owner_user_id,idempotency_key)` 唯一。
- `ark_knowledge_ai_job_sources`：任务创建时冻结的已发布来源修订、顺序和评分；引用只能落在这些 revision 上。

正文事实源是受服务端节点白名单校验的 ProseMirror/Tiptap JSON；`content_text` 仅用于检索和 Agent 纯文本输出。发布操作只能把 `published_revision_id` 指向 approval 中冻结的 `revision_id`。

同一知识库内的新建、保存、提交、审批和软删除共用 `ark_knowledge_libraries` 行锁串行化；获取锁后重新校验文档与审批状态，避免删除期间产生活跃孤儿节点或残留待审批。

图片文件不进入数据库，存放在 `KNOWLEDGE_STORAGE_ROOT/{library_id}/...` 私有目录，数据库只保存相对路径。修订事务会锁定并校验图片所有权后写 `ark_knowledge_revision_assets`；24 小时仍为 temporary 且无引用的图片由每日清理任务软删后移除文件。

AI Worker 用 `status + lease_token + lease_expires_at` 领取任务，模型网络调用期间不持有业务行锁。租约按 Provider timeout 延长，过期任务最多领取 3 次；达到上限转 failed，避免无限重放。应用结果时重新锁定知识库/文档/任务并核对 `base_revision_id`，因此不会覆盖任务创建后的编辑。
