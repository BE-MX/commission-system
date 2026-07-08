"""enrich overwritten comments (P1 review fix)

命名规范化 P1（docs/2026-07-08-db-naming-assessment.md）：以 ORM comment= 为真相源，
将注释刷入库。所有 MODIFY 的列定义逐字转录自 information_schema，仅附加 COMMENT，
不改类型/NULL/DEFAULT/EXTRA（生成器：scratchpad/gen_comment_migration.py，
前后 schema 快照 diff 验证除注释外零变化）。

Revision ID: 055_enrich_comments
Revises: 054_backfill_comments
Create Date: 2026-07-08
"""

from alembic import op

revision = "055_enrich_comments"
down_revision = "054_backfill_comments"
branch_labels = None
depends_on = None

UPGRADE_SQL = [
    "ALTER TABLE `ark_color_blend` MODIFY COLUMN `blend_code` varchar(30) NOT NULL COMMENT '混合编码，如 #8/8/60, #1C/18/46', MODIFY COLUMN `computed_hex` char(7) NULL DEFAULT NULL COMMENT '加权混合HEX（加权混合计算的综合HEX）', MODIFY COLUMN `brand_name` varchar(100) NULL DEFAULT NULL COMMENT '品牌命名，如 Vanilla Latte'",
    "ALTER TABLE `ark_color_palette` MODIFY COLUMN `industry_code` varchar(20) NOT NULL COMMENT '行业标准色号，如 #1, #613, #1C/18', MODIFY COLUMN `brand_code` varchar(50) NULL DEFAULT NULL COMMENT '品牌特有编码，如 Bellami的Vanilla Latte', MODIFY COLUMN `display_name` varchar(100) NOT NULL COMMENT '展示名称（中英双语）', MODIFY COLUMN `hex_code` char(7) NOT NULL COMMENT 'HEX值，如 #6B5A52', MODIFY COLUMN `lab_l` decimal(6,2) NULL DEFAULT NULL COMMENT 'LAB L*（CIE LAB - L* (明度 0-100)）', MODIFY COLUMN `lab_a` decimal(6,2) NULL DEFAULT NULL COMMENT 'LAB a*（CIE LAB - a* (绿红 -128~127)）', MODIFY COLUMN `lab_b_val` decimal(6,2) NULL DEFAULT NULL COMMENT 'LAB b*（CIE LAB - b* (蓝黄 -128~127)）', MODIFY COLUMN `hsl_h` smallint NULL DEFAULT NULL COMMENT 'HSL色相 0-360', MODIFY COLUMN `hsl_s` decimal(5,2) NULL DEFAULT NULL COMMENT 'HSL饱和度 0-100', MODIFY COLUMN `hsl_l` decimal(5,2) NULL DEFAULT NULL COMMENT 'HSL亮度 0-100', MODIFY COLUMN `luminance_level` varchar(16) NULL DEFAULT NULL COMMENT '明度级别（low/medium-low/medium/medium-high/high/very-high）', MODIFY COLUMN `color_family` varchar(16) NOT NULL COMMENT '色族（black/brown/blonde/red/silver/vibrant）', MODIFY COLUMN `pantone_tcx` varchar(30) NULL DEFAULT NULL COMMENT '最近Pantone TCX色号', MODIFY COLUMN `pantone_delta_e` decimal(4,2) NULL DEFAULT NULL COMMENT '与Pantone色差（与Pantone的ΔE2000值）', MODIFY COLUMN `peak_season` varchar(64) NULL DEFAULT NULL COMMENT '高峰季节（高峰销售季节 spring/summer/autumn/winter 逗号分隔）'",
    "ALTER TABLE `ark_custom_products` MODIFY COLUMN `okki_product_id` bigint NULL DEFAULT NULL COMMENT 'OKKI 建品后回填的真实产品ID'",
    "ALTER TABLE `ark_customer_opportunities` MODIFY COLUMN `owner_user_id` int unsigned NULL DEFAULT NULL COMMENT '方舟归属用户，空=待分配'",
    "ALTER TABLE `ark_customer_price_rules` MODIFY COLUMN `adjust_value` decimal(12,4) NOT NULL COMMENT '有符号调价值：fixed=差价金额(发票币种,+2=加2/-3=减3)；percent=百分数(5=+5%)——与提成 0.02=2% 的小数口径不同'",
    "ALTER TABLE `ark_invoice_items` MODIFY COLUMN `custom_product_id` bigint NULL DEFAULT NULL COMMENT 'ark_custom_products.id, no FK by design'",
    "ALTER TABLE `ark_production_orders` MODIFY COLUMN `deleted_flag` smallint NOT NULL DEFAULT '0' COMMENT '0=正常,1=已删除(软删)'",
    "ALTER TABLE `ark_short_links` MODIFY COLUMN `short_code` varchar(8) NOT NULL COMMENT '短码（6位 MD5 前缀，预留 2 位扩展）'",
    "ALTER TABLE `ark_stock_daily_reports` MODIFY COLUMN `warning_skus` json NOT NULL COMMENT '预警SKU详情JSON数组'",
    "ALTER TABLE `ark_user_external_bindings` MODIFY COLUMN `provider` varchar(50) NOT NULL COMMENT '外部系统: alibaba_icbu/okki/dingtalk/email'",
    "ALTER TABLE `ark_users` MODIFY COLUMN `wx_id` varchar(100) NULL DEFAULT NULL COMMENT '微信原始ID（FromUserName），用于报工时匹配方舟账号'",
    "ALTER TABLE `ark_waybills` MODIFY COLUMN `waybill_no` varchar(50) NOT NULL COMMENT '运单号（唯一）', MODIFY COLUMN `carrier` varchar(50) NOT NULL DEFAULT '未知' COMMENT '物流商：FedEx/DHL/UPS/未知', MODIFY COLUMN `status` varchar(20) NOT NULL DEFAULT '待跟踪' COMMENT '状态：待跟踪/运输中/已签收/异常', MODIFY COLUMN `entry_source` varchar(20) NOT NULL DEFAULT 'manual' COMMENT '录入来源：ocr/manual', MODIFY COLUMN `created_by` varchar(50) NOT NULL COMMENT '录入人（登录用户名）'",
    "ALTER TABLE `commission_detail` MODIFY COLUMN `payment_amount` decimal(12,2) NOT NULL COMMENT '回款金额（USD）', MODIFY COLUMN `salesperson_commission` decimal(12,2) NOT NULL COMMENT '业务员提成（USD）', MODIFY COLUMN `supervisor_commission` decimal(12,2) NULL DEFAULT '0.00' COMMENT '一级主管提成（USD）', MODIFY COLUMN `second_supervisor_commission` decimal(12,2) NULL DEFAULT '0.00' COMMENT '二级主管提成（USD）'",
    "ALTER TABLE `concept_change_logs` MODIFY COLUMN `concept_id` varchar(64) NOT NULL COMMENT '概念ID FK→data_concepts.id'",
    "ALTER TABLE `concept_relationships` MODIFY COLUMN `source_concept_id` varchar(64) NOT NULL COMMENT '源概念ID FK→data_concepts.id', MODIFY COLUMN `target_concept_id` varchar(64) NOT NULL COMMENT '目标概念ID FK→data_concepts.id', MODIFY COLUMN `is_auto_generated` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否由系统自动生成（如 conflicts_with 反向边）'",
    "ALTER TABLE `order_product_process_progress` MODIFY COLUMN `process_id` int NOT NULL COMMENT '关联工序ID（关联 process.id）'",
    "ALTER TABLE `process_route_step` MODIFY COLUMN `route_id` int NOT NULL COMMENT '关联路线ID（关联 process_route.id）', MODIFY COLUMN `process_id` int NOT NULL COMMENT '关联工序ID（关联 process.id）'",
    "ALTER TABLE `product_process_route` MODIFY COLUMN `route_id` int NOT NULL COMMENT '关联路线ID（关联 process_route.id）'",
    "ALTER TABLE `synced_payment` MODIFY COLUMN `payment_amount` decimal(12,2) NOT NULL COMMENT '回款金额（USD，来源 okki_receipts.amount_usd）', MODIFY COLUMN `service_fee` decimal(15,2) NULL DEFAULT '0.00' COMMENT '服务费（USD，来源 service_fee_amount_usd）'",
    "ALTER TABLE `sys_dict` MODIFY COLUMN `sort` int NOT NULL DEFAULT '0' COMMENT '排序，越小越靠前'",
]

DOWNGRADE_SQL = [
    "ALTER TABLE `ark_color_blend` MODIFY COLUMN `blend_code` varchar(30) NOT NULL COMMENT '混合编码', MODIFY COLUMN `computed_hex` char(7) NULL DEFAULT NULL COMMENT '加权混合HEX', MODIFY COLUMN `brand_name` varchar(100) NULL DEFAULT NULL COMMENT '品牌命名'",
    "ALTER TABLE `ark_color_palette` MODIFY COLUMN `industry_code` varchar(20) NOT NULL COMMENT '行业标准色号', MODIFY COLUMN `brand_code` varchar(50) NULL DEFAULT NULL COMMENT '品牌特有编码', MODIFY COLUMN `display_name` varchar(100) NOT NULL COMMENT '展示名称', MODIFY COLUMN `hex_code` char(7) NOT NULL COMMENT 'HEX值', MODIFY COLUMN `lab_l` decimal(6,2) NULL DEFAULT NULL COMMENT 'LAB L*', MODIFY COLUMN `lab_a` decimal(6,2) NULL DEFAULT NULL COMMENT 'LAB a*', MODIFY COLUMN `lab_b_val` decimal(6,2) NULL DEFAULT NULL COMMENT 'LAB b*', MODIFY COLUMN `hsl_h` smallint NULL DEFAULT NULL COMMENT 'HSL色相', MODIFY COLUMN `hsl_s` decimal(5,2) NULL DEFAULT NULL COMMENT 'HSL饱和度', MODIFY COLUMN `hsl_l` decimal(5,2) NULL DEFAULT NULL COMMENT 'HSL亮度', MODIFY COLUMN `luminance_level` varchar(16) NULL DEFAULT NULL COMMENT '明度级别', MODIFY COLUMN `color_family` varchar(16) NOT NULL COMMENT '色族', MODIFY COLUMN `pantone_tcx` varchar(30) NULL DEFAULT NULL COMMENT '最近Pantone TCX', MODIFY COLUMN `pantone_delta_e` decimal(4,2) NULL DEFAULT NULL COMMENT '与Pantone色差', MODIFY COLUMN `peak_season` varchar(64) NULL DEFAULT NULL COMMENT '高峰季节'",
    "ALTER TABLE `ark_custom_products` MODIFY COLUMN `okki_product_id` bigint NULL DEFAULT NULL COMMENT 'backfilled once OKKI creates the real product'",
    "ALTER TABLE `ark_customer_opportunities` MODIFY COLUMN `owner_user_id` int unsigned NULL DEFAULT NULL COMMENT '方舟归属用户'",
    "ALTER TABLE `ark_customer_price_rules` MODIFY COLUMN `adjust_value` decimal(12,4) NOT NULL COMMENT 'signed'",
    "ALTER TABLE `ark_invoice_items` MODIFY COLUMN `custom_product_id` bigint NULL DEFAULT NULL COMMENT 'ark_custom_products.id'",
    "ALTER TABLE `ark_production_orders` MODIFY COLUMN `deleted_flag` smallint NOT NULL DEFAULT '0' COMMENT '0=正常,1=已删除'",
    "ALTER TABLE `ark_short_links` MODIFY COLUMN `short_code` varchar(8) NOT NULL COMMENT '短码'",
    "ALTER TABLE `ark_stock_daily_reports` MODIFY COLUMN `warning_skus` json NOT NULL COMMENT '预警SKU详情'",
    "ALTER TABLE `ark_user_external_bindings` MODIFY COLUMN `provider` varchar(50) NOT NULL COMMENT 'alibaba_icbu/okki/dingtalk/email'",
    "ALTER TABLE `ark_users` MODIFY COLUMN `wx_id` varchar(100) NULL DEFAULT NULL COMMENT '微信原始ID（FromUserName），用于报工匹配'",
    "ALTER TABLE `ark_waybills` MODIFY COLUMN `waybill_no` varchar(50) NOT NULL COMMENT '运单号', MODIFY COLUMN `carrier` varchar(50) NOT NULL DEFAULT '未知' COMMENT '物流商', MODIFY COLUMN `status` varchar(20) NOT NULL DEFAULT '待跟踪' COMMENT '状态', MODIFY COLUMN `entry_source` varchar(20) NOT NULL DEFAULT 'manual' COMMENT '录入来源', MODIFY COLUMN `created_by` varchar(50) NOT NULL COMMENT '录入人'",
    "ALTER TABLE `commission_detail` MODIFY COLUMN `payment_amount` decimal(12,2) NOT NULL COMMENT '本条回款金额', MODIFY COLUMN `salesperson_commission` decimal(12,2) NOT NULL COMMENT '业务员提成金额', MODIFY COLUMN `supervisor_commission` decimal(12,2) NULL DEFAULT '0.00' COMMENT '一级主管提成金额', MODIFY COLUMN `second_supervisor_commission` decimal(12,2) NULL DEFAULT '0.00' COMMENT '二级主管提成金额'",
    "ALTER TABLE `concept_change_logs` MODIFY COLUMN `concept_id` varchar(64) NOT NULL COMMENT '概念ID'",
    "ALTER TABLE `concept_relationships` MODIFY COLUMN `source_concept_id` varchar(64) NOT NULL COMMENT '源概念ID', MODIFY COLUMN `target_concept_id` varchar(64) NOT NULL COMMENT '目标概念ID', MODIFY COLUMN `is_auto_generated` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否由系统自动生成'",
    "ALTER TABLE `order_product_process_progress` MODIFY COLUMN `process_id` int NOT NULL COMMENT '关联工序ID'",
    "ALTER TABLE `process_route_step` MODIFY COLUMN `route_id` int NOT NULL COMMENT '关联路线ID', MODIFY COLUMN `process_id` int NOT NULL COMMENT '关联工序ID'",
    "ALTER TABLE `product_process_route` MODIFY COLUMN `route_id` int NOT NULL COMMENT '关联路线ID'",
    "ALTER TABLE `synced_payment` MODIFY COLUMN `payment_amount` decimal(12,2) NOT NULL COMMENT '回款金额', MODIFY COLUMN `service_fee` decimal(15,2) NULL DEFAULT '0.00' COMMENT '交易服务费'",
    "ALTER TABLE `sys_dict` MODIFY COLUMN `sort` int NOT NULL DEFAULT '0' COMMENT '排序'",
]


def upgrade() -> None:
    for sql in UPGRADE_SQL:
        op.execute(sql)


def downgrade() -> None:
    for sql in DOWNGRADE_SQL:
        op.execute(sql)
