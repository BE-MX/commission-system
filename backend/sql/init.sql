-- ============================================================
-- 提成管理系统 - 初始化 DDL
-- 数据库: commission_db
-- ============================================================

CREATE DATABASE IF NOT EXISTS `commission_db`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `commission_db`;

-- 1. 员工属性历史表
CREATE TABLE IF NOT EXISTS `employee_attribute_history` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `employee_id` VARCHAR(64) NOT NULL COMMENT '关联业务库员工ID',
  `attribute_type` ENUM('develop','distribute') NOT NULL COMMENT '开发/分配',
  `effective_start` DATE NOT NULL COMMENT '生效开始时间',
  `effective_end` DATE NULL COMMENT '生效结束时间，NULL表示当前有效',
  `is_current` TINYINT(1) DEFAULT 1 COMMENT '是否当前有效',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `ix_employee_attr_emp_current` (`employee_id`, `is_current`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. 业务员-主管关系历史表
CREATE TABLE IF NOT EXISTS `supervisor_relation_history` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `salesperson_id` VARCHAR(64) NOT NULL COMMENT '业务员ID',
  `supervisor_id` VARCHAR(64) NOT NULL COMMENT '业务主管ID',
  `effective_start` DATE NOT NULL,
  `effective_end` DATE NULL,
  `is_current` TINYINT(1) DEFAULT 1,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `ix_supervisor_rel_sp_current` (`salesperson_id`, `is_current`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. 客户提成归属快照表
CREATE TABLE IF NOT EXISTS `customer_commission_snapshot` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `customer_id` VARCHAR(64) NOT NULL COMMENT '客户ID',
  `first_order_id` VARCHAR(64) NULL COMMENT '首单订单ID',
  `first_order_date` DATE NULL COMMENT '首单生效日期',
  `salesperson_id` VARCHAR(64) NOT NULL COMMENT '归属业务员ID',
  `salesperson_attribute` ENUM('develop','distribute') NULL COMMENT '业务员属性快照',
  `salesperson_rate` DECIMAL(5,4) NULL COMMENT '业务员提成比例',
  `supervisor_id` VARCHAR(64) NULL COMMENT '归属业务主管ID',
  `supervisor_attribute` ENUM('develop','distribute') NULL COMMENT '主管属性快照',
  `supervisor_rate` DECIMAL(5,4) NULL COMMENT '主管提成比例',
  `is_complete` TINYINT(1) DEFAULT 0 COMMENT '是否完整',
  `is_current` TINYINT(1) DEFAULT 1 COMMENT '是否当前有效',
  `source` ENUM('auto','manual','import','init') DEFAULT 'auto' COMMENT '来源',
  `is_manual_reset` TINYINT(1) DEFAULT 0 COMMENT '是否人工重置产生',
  `reset_reason` TEXT NULL COMMENT '重置原因',
  `operator` VARCHAR(64) NULL COMMENT '操作人',
  `operated_at` DATETIME NULL COMMENT '操作时间',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `ix_snapshot_customer_current` (`customer_id`, `is_current`),
  INDEX `ix_snapshot_is_complete` (`is_complete`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. 已同步回款记录表
CREATE TABLE IF NOT EXISTS `synced_payment` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `payment_id` VARCHAR(64) NOT NULL COMMENT '业务库回款ID',
  `order_id` VARCHAR(64) NOT NULL COMMENT '关联订单ID',
  `customer_id` VARCHAR(64) NOT NULL COMMENT '关联客户ID',
  `payment_date` DATE NOT NULL COMMENT '回款日期',
  `payment_amount` DECIMAL(12,2) NOT NULL COMMENT '回款金额',
  `synced_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '同步时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_payment_id` (`payment_id`),
  INDEX `ix_synced_payment_date` (`payment_date`),
  INDEX `ix_synced_payment_customer` (`customer_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. 提成批次表
CREATE TABLE IF NOT EXISTS `commission_batch` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `batch_name` VARCHAR(128) NOT NULL COMMENT '批次名称',
  `period_type` ENUM('monthly','quarterly','semi_annual','annual') DEFAULT 'quarterly',
  `period_start` DATE NOT NULL COMMENT '周期开始日期',
  `period_end` DATE NOT NULL COMMENT '周期结束日期',
  `status` ENUM('draft','calculated','confirmed','voided') DEFAULT 'draft',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `created_by` VARCHAR(64) NULL,
  `confirmed_at` DATETIME NULL,
  `confirmed_by` VARCHAR(64) NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. 提成明细表
CREATE TABLE IF NOT EXISTS `commission_detail` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `batch_id` BIGINT NOT NULL,
  `payment_id` VARCHAR(64) NOT NULL COMMENT '回款单ID',
  `order_id` VARCHAR(64) NOT NULL COMMENT '订单ID',
  `customer_id` VARCHAR(64) NOT NULL COMMENT '客户ID',
  `payment_amount` DECIMAL(12,2) NOT NULL COMMENT '本条回款金额',
  `salesperson_id` VARCHAR(64) NOT NULL,
  `salesperson_rate` DECIMAL(5,4) NOT NULL,
  `salesperson_commission` DECIMAL(12,2) NOT NULL COMMENT '业务员提成金额',
  `supervisor_id` VARCHAR(64) NULL,
  `supervisor_rate` DECIMAL(5,4) NULL,
  `supervisor_commission` DECIMAL(12,2) DEFAULT 0 COMMENT '主管提成金额',
  `calc_rule_note` VARCHAR(256) NULL COMMENT '计算规则说明',
  `calculated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `status` ENUM('pending','confirmed','paid','voided') DEFAULT 'pending',
  PRIMARY KEY (`id`),
  INDEX `ix_detail_batch` (`batch_id`),
  INDEX `ix_detail_payment` (`payment_id`),
  INDEX `ix_detail_order` (`order_id`),
  INDEX `ix_detail_salesperson` (`salesperson_id`),
  INDEX `ix_detail_supervisor` (`supervisor_id`),
  CONSTRAINT `fk_detail_batch` FOREIGN KEY (`batch_id`) REFERENCES `commission_batch` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7. 回款提成状态表
CREATE TABLE IF NOT EXISTS `payment_commission_status` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `payment_id` VARCHAR(64) NOT NULL COMMENT '回款单ID',
  `batch_id` BIGINT NOT NULL,
  `calculated_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '计算时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_pcs_payment_id` (`payment_id`),
  CONSTRAINT `fk_pcs_batch` FOREIGN KEY (`batch_id`) REFERENCES `commission_batch` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
