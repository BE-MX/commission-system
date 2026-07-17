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

**业务库常用表口径（lsordertest，OKKI 同步投影，只读）**：
- `customer_info` — 客户主表（company_id bigint 主键，company_name，country_name，**owner_user_ids JSON 数组**=归属 OKKI user_id 列表、空数组=公海；私海过滤用 `JSON_CONTAINS`）
- `customer_contacts` — 客户联系人（company_id→customer_info，name/email/tel/is_main；发票录入「按联系人搜客户」数据源，2026-07-14 起）

**主要业务表（commission_db）**：
- `sys_dict` — 系统字典（type, code, label, sort, is_active）；`(type, code)` 唯一索引
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
  - `ark_production_orders` — 生产订单主表（order_no UNIQUE, status 0已提交/1已终止/2已完成, deleted_flag 软删, created_by, remark）
  - `ark_production_order_items` — 生产订单明细（order_id, product_id, product_name, model, spec_info, order_qty, received_qty, status, is_urgent SmallInteger, expected_delivery_date Date, remark；无独立软删字段，靠 FK CASCADE 跟随订单删除）
  - `ark_production_cart` — 生产购物车（user_id + product_id UNIQUE, product_name, model, spec_info, order_qty, remark）
  - `ark_production_audit_log` — 生产订单审计日志（order_id, action, old_value, new_value, operator_id）
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
- **客户机会台（3 张表，031 迁移，insight/models.py）**：
  - `ark_inquiry_import_batches` — 阿里询盘导入批次（batch_id 唯一，source/schema_version，统计 created/updated/unassigned/failed，status processing/success/partial_failed/failed）
  - `ark_customer_opportunities` — 客户机会卡（source_key 唯一幂等键，owner_user_id FK ark_users，owner_binding_id FK ark_user_external_bindings，priority_level A/B/C/D，urgency urgent/high/normal/low，due_at 按等级计算，status pending/contacted/replied/quoted/won/lost/dismissed，含背调/AI策略/话术字段，**full_report_html TEXT** ACCIO 完整背调报告 HTML）
  - `ark_customer_opportunity_events` — 机会事件（opportunity_id FK CASCADE，event_type created/imported/viewed/status_changed/feedback/assigned）
- **客户经营雷达（3 张表，034 迁移，insight/models.py）**：
  - `ark_customer_profiles` — 客户活画像（customer_external_id UNIQUE，customer_name + customer_region 组合查重，owner_user_id FK ark_users，priority_score 优先级分，total_opportunities/total_events 统计，profile_tags/profile_signals_json/profile_judgement 画像数据，suggested_message 推荐话术，status active）
  - `ark_customer_profile_events` — 客户事件流（profile_id FK CASCADE，event_source/event_type 分类，event_score 正负评分，opportunity_id FK ark_customer_opportunities，actor_user_id 操作人）
  - `ark_customer_actions` — 行动候选池（profile_id FK CASCADE，owner_user_id FK ark_users，thread_group 线索分组，thread_priority 优先级，action_status pending/completed/dismissed/snoozed，snoozed_until 延后截止，action_date 行动日期）
- **素材管理（7 张表，020 迁移）**：
  - `ark_tag_dimensions` — 标签维度
  - `ark_tag_values` — 标签值
  - `ark_assets` — 素材主表
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
  - `ark_pantone_reference` — Pantone TCX 参考色库（2310 条，pantone_code, hex_code, rgb, lab）
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
- **订单发票（8 张表，044 迁移 + 049 扩展）**：
  - `ark_invoices` — 发票主表（invoice_no UNIQUE, order_type stock/production, customer_id/name, 联系人快照 contact_name/phone/email + delivery_address, 业务员快照 sales_user_id/name/phone/email, invoice_date, currency, status draft/ready/synced/sync_failed, express_channel/shipping_fee/surcharge_name/surcharge_amount/payment_term, product_amount=行净额合计, total_amount=行净额+包装费+运费+手续费, internal_discount=明细折扣合计只读快照, internal_accessory=包装费, packaging_quantity=包装数量且不参与金额乘算——071 迁移, internal_received=预付款, internal_balance=尾款, xiaoman_order_id/no, sync_status/error/synced_at, xiaoman_removed_lines 已推明细删除快照 JSON——066 迁移，编辑删行时累积、推单成功清空; okki_new_deal/okki_free_shipping/okki_first_return 三个 OKKI 必填业务标记——068 迁移，1是/0否/NULL 推单时兜底：新成交=客户无 okki 历史订单、包邮=运费为 0、首返=否）
  - `ark_invoice_items` — 发票明细（invoice_id FK CASCADE, item_type stock/custom, product_id 可空, sku_id, custom_product_id, product_name/display, net_weight_grams, curl, model 可空, color, length, quantity, standard_price+customer_price 双价快照, price_per_piece, discount_amount 行级折扣负数/0——070 迁移, total_price=单价×数量+折扣, price_source customer_rule/manual/missing_std, xiaoman_unique_id）
  - `ark_custom_products`（049）— 生产单沉淀产品（match_key UNIQUE=归一化 display|model|color|size|unit, product_display/name, model/color/size/unit, okki_product_id/okki_sku_id 对账回填, use_count）；**okki_products 保持只读，本地产品一律进此表**
  - `ark_price_color_types`（049）— 色号→色型（color_code UNIQUE 归一化小写无#, color_type solid/piano/ombre/balayage）
  - `ark_std_prices`（049）— 标准价矩阵（series_grade+length+weight_unit+color_type UNIQUE, price, currency）
  - `ark_customer_price_rules`（049）— 客户调价规则（customer_id UNIQUE, adjust_type fixed/percent, adjust_value 有符号, enabled, preferred_template）
  - `ark_invoice_sync_logs`（049）— OKKI 推送日志（invoice_id FK CASCADE, action, success, request_digest/response_body/error_message, operator_id）
  - `ark_xiaoman_settings`（049）— OKKI 推送配置单行表（generic_product_no/id/sku_id 通用产品, default_order_status, default_currency, access_token）
  - `ark_receipt_repair_log`（052）— 回款日期修复审计表（batch_id 分组一次执行, cash_collection_id, order_no, company_name, old_date→new_date, source_file, operator_id, created_at）；**唯一写 `lsordertest.okki_receipts.collection_date` 的入口，每条改动留回滚记录**
- **展会 AI 试戴（7 张表，045 迁移；047 加发色/场景；048 加发色库）**：
  - `ark_expo_customers` — 试戴客户（name 称呼, phone, wechat_id, primary_need volume/gray_cover/style_change, style_pref, **consent_at 非空才允许存照片**, expo_code 届次）
  - `ark_expo_wigs` — 发型库（model_no UNIQUE, series classic/zhizhen 驱动至臻锚点, angle_photos JSON, composite_prompt, fit_tags JSON, evidence_refs JSON, priority, must_recommend 主推=置顶推荐 060 加列/065 语义升级）
  - `ark_expo_hair_colors` — 发色库（code UNIQUE 色号, name, hex_code UI 色块可自动提取, swatch_path 色板图**仅 UI 色块与溯源**（2026-07-14 起不进合成）, color_description, priority, is_active）
  - `ark_expo_wig_colors` — 发型×发色组合三角度参考图（072）：wig_id/hair_color_id 双 FK（BigInteger，ON DELETE CASCADE）, UNIQUE(wig_id,hair_color_id), angle_photos JSON 三角度图组, cover_path, is_active。稀疏存储只存备图组合；合成时按选择匹配唯一颜色图组（参考图即目标色，取代文字/色板图上色）；「原色」用发型自身 angle_photos 不在此表
  - `ark_expo_scripts` — 话术卡库（script_type opener/demo/objection/closer/faq, track emotional/rational/identity, audience_tags JSON, evidence_points JSON；写入时禁用词强校验）
  - `ark_expo_sessions` — 试戴会话（**mode tryon/scene 双入口**——scene=佩戴实拍生成场景图跳过分析, photo_path, analysis_json 含 **internal 内部字段仅销售端可见**, matched_wig_ids JSON 全量排名, strategy_json 双轨话术（scene 模式不生成）, status pending/analyzed/generating/done/failed）
  - `ark_expo_results` — 效果图（session_id FK CASCADE, **wig_id 可空**——scene 模式为 NULL, hair_color_json 发色快照（048 起 hair_color_id/code/name/hex/swatch_path/description；历史行为 palette 旧形态）, scene_json 场景快照 key/label, reaction loved/soso, short_code 分享码, gen_ms）
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

## 培训速递（迁移 075）

- `ark_training_digests`：培训速递主表——基本信息（培训名/机构/讲师/日期/参训人/标签）、一句话总结、`sections_json` 结构化分区（重点/亮点/可应用点/方法/参训人点评）、draft/published 状态、阅读时长与浏览/有用计数。
- `ark_training_digest_files`：原始资料附件元数据，`storage_path` 相对 `TRAINING_STORAGE_ROOT` 私有目录；删除主表行时 service 层负责删行+清盘（不依赖 CASCADE）。
- `ark_training_digest_feedback`：「有用」轻反馈，`(digest_id, user_id, kind)` 唯一约束防重复。
