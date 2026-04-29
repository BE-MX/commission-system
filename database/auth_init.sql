-- ============================================================
-- 莱莎方舟 Auth 数据库脚本
-- 数据库: commission_db
-- 执行顺序: 按顺序执行，不可乱序
-- ============================================================

-- ------------------------------------------------------------
-- 1. 用户表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ark_users` (
  `id`                    INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `username`              VARCHAR(50)  NOT NULL COMMENT '登录用户名，唯一',
  `password_hash`         VARCHAR(128) NOT NULL COMMENT 'bcrypt hash',
  `real_name`             VARCHAR(50)  NOT NULL COMMENT '真实姓名',
  `email`                 VARCHAR(100)          COMMENT '邮箱（可选）',
  `phone`                 VARCHAR(20)           COMMENT '手机号（可选）',
  `dingtalk_id`           VARCHAR(100)          COMMENT '钉钉用户ID，SSO预留',
  `avatar_url`            VARCHAR(500)          COMMENT '头像URL',
  `is_active`             TINYINT(1)   NOT NULL DEFAULT 1  COMMENT '1=正常 0=禁用',
  `must_change_password`  TINYINT(1)   NOT NULL DEFAULT 0  COMMENT '1=首次登录需改密',
  `last_login_at`         DATETIME              COMMENT '最后登录时间',
  `last_login_ip`         VARCHAR(45)           COMMENT '最后登录IP（支持IPv6）',
  `created_at`            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted_at`            DATETIME              COMMENT '软删除时间戳',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`),
  UNIQUE KEY `uk_dingtalk_id` (`dingtalk_id`),
  KEY `idx_is_active` (`is_active`),
  KEY `idx_deleted_at` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

-- ------------------------------------------------------------
-- 2. 角色表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ark_roles` (
  `id`          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`        VARCHAR(50)  NOT NULL COMMENT '角色标识，如 admin',
  `label`       VARCHAR(100) NOT NULL COMMENT '角色中文名',
  `description` VARCHAR(255)          COMMENT '角色说明',
  `is_system`   TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1=系统内置角色，不可删除',
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='角色表';

-- ------------------------------------------------------------
-- 3. 权限表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ark_permissions` (
  `id`          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `code`        VARCHAR(100) NOT NULL COMMENT '权限标识，如 commission:write',
  `module`      VARCHAR(50)  NOT NULL COMMENT '所属模块，如 commission',
  `action`      VARCHAR(50)  NOT NULL COMMENT '操作，如 write',
  `label`       VARCHAR(100) NOT NULL COMMENT '权限中文名',
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code` (`code`),
  KEY `idx_module` (`module`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='权限表';

-- ------------------------------------------------------------
-- 4. 角色-权限关联表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ark_role_permissions` (
  `role_id`       INT UNSIGNED NOT NULL,
  `permission_id` INT UNSIGNED NOT NULL,
  `created_at`    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`role_id`, `permission_id`),
  CONSTRAINT `fk_rp_role` FOREIGN KEY (`role_id`) REFERENCES `ark_roles`(`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_rp_perm` FOREIGN KEY (`permission_id`) REFERENCES `ark_permissions`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='角色-权限关联';

-- ------------------------------------------------------------
-- 5. 用户-角色关联表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ark_user_roles` (
  `user_id`    INT UNSIGNED NOT NULL,
  `role_id`    INT UNSIGNED NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `created_by` INT UNSIGNED COMMENT '分配操作人ID',
  PRIMARY KEY (`user_id`, `role_id`),
  CONSTRAINT `fk_ur_user` FOREIGN KEY (`user_id`) REFERENCES `ark_users`(`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_ur_role` FOREIGN KEY (`role_id`) REFERENCES `ark_roles`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户-角色关联';

-- ------------------------------------------------------------
-- 6. Refresh Token 存储表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ark_refresh_tokens` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `token_hash`  CHAR(64)     NOT NULL COMMENT 'SHA-256 of token，不存明文',
  `user_id`     INT UNSIGNED NOT NULL,
  `device_info` VARCHAR(255)          COMMENT 'User-Agent 摘要',
  `ip_address`  VARCHAR(45)           COMMENT '创建时IP',
  `expires_at`  DATETIME     NOT NULL COMMENT 'Token过期时间',
  `revoked_at`  DATETIME              COMMENT '主动吊销时间',
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_token_hash` (`token_hash`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_expires_at` (`expires_at`),
  CONSTRAINT `fk_rt_user` FOREIGN KEY (`user_id`) REFERENCES `ark_users`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Refresh Token存储';

-- ------------------------------------------------------------
-- 7. 登录日志表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ark_login_logs` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`     INT UNSIGNED              COMMENT 'NULL表示用户名不存在的尝试',
  `username`    VARCHAR(50)  NOT NULL     COMMENT '登录时输入的用户名',
  `ip_address`  VARCHAR(45)  NOT NULL,
  `user_agent`  VARCHAR(500),
  `status`      ENUM('success','failed','locked') NOT NULL,
  `fail_reason` VARCHAR(255)              COMMENT '失败原因',
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_username_created` (`username`, `created_at`),
  KEY `idx_ip_created` (`ip_address`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='登录日志';

-- ============================================================
-- 初始化数据
-- ============================================================

-- 插入权限
INSERT IGNORE INTO `ark_permissions` (`code`, `module`, `action`, `label`) VALUES
-- 用户管理
('user:read',           'user',       'read',        '查看用户列表'),
('user:write',          'user',       'write',       '创建/编辑用户'),
('user:delete',         'user',       'delete',      '禁用用户'),
('user:assign_role',    'user',       'assign_role', '分配角色'),
-- 提成管理
('commission:read_own', 'commission', 'read_own',    '查看本人提成'),
('commission:read_all', 'commission', 'read_all',    '查看全部提成'),
('commission:write',    'commission', 'write',       '录入/修改提成'),
('commission:settle',   'commission', 'settle',      '提成结算'),
('commission:export',   'commission', 'export',      '导出提成报表'),
-- 物流跟踪
('tracking:read',       'tracking',   'read',        '查看物流'),
('tracking:write',      'tracking',   'write',       '更新物流状态'),
('tracking:delete',     'tracking',   'delete',      '删除物流记录'),
-- 设计预约
('design:submit',       'design',     'submit',      '提交设计预约'),
('design:read_own',     'design',     'read_own',    '查看自己的预约'),
('design:read_all',     'design',     'read_all',    '查看所有预约'),
('design:approve',      'design',     'approve',     '审批/驳回预约'),
('design:manage',       'design',     'manage',      '管理排期工作量'),
-- 系统管理
('system:config',       'system',     'config',      '系统配置'),
('system:logs',         'system',     'logs',        '查看操作日志'),
('system:backup',       'system',     'backup',      '数据备份'),
('role:read',           'system',     'read',        '查看角色列表'),
('role:write',          'system',     'write',       '创建/编辑角色'),
('role:delete',         'system',     'delete',      '删除角色');

-- 插入角色
INSERT IGNORE INTO `ark_roles` (`name`, `label`, `description`, `is_system`) VALUES
('super_admin',   '超级管理员', '全平台所有权限，系统内置，不可删除', 1),
('admin',         '管理员',     '管理用户和角色，查看全平台数据',     1),
('supervisor',    '主管',       '审批设计预约，查看提成汇总',         1),
('salesperson',   '业务员',     '提交预约、查看自己提成、查看物流',   1),
('design_staff',  '设计部',     '管理设计排期与工作量',               1),
('finance',       '财务',       '管理提成结算、导出财务报表',         1);

-- 角色-权限映射（super_admin跳过，代码层面特判）
-- admin
INSERT IGNORE INTO `ark_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `ark_roles` r, `ark_permissions` p
WHERE r.name = 'admin'
  AND p.code IN (
    'user:read','user:write','user:delete','user:assign_role',
    'commission:read_own','commission:read_all','commission:write','commission:settle','commission:export',
    'tracking:read','tracking:write','tracking:delete',
    'design:submit','design:read_own','design:read_all','design:approve','design:manage',
    'system:logs',
    'role:read','role:write','role:delete'
  );

-- supervisor
INSERT IGNORE INTO `ark_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `ark_roles` r, `ark_permissions` p
WHERE r.name = 'supervisor'
  AND p.code IN (
    'commission:read_own','commission:read_all','commission:export',
    'tracking:read',
    'design:submit','design:read_own','design:read_all','design:approve'
  );

-- salesperson
INSERT IGNORE INTO `ark_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `ark_roles` r, `ark_permissions` p
WHERE r.name = 'salesperson'
  AND p.code IN (
    'commission:read_own',
    'tracking:read','tracking:write',
    'design:submit','design:read_own'
  );

-- design_staff
INSERT IGNORE INTO `ark_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `ark_roles` r, `ark_permissions` p
WHERE r.name = 'design_staff'
  AND p.code IN (
    'design:read_own','design:read_all','design:manage'
  );

-- finance
INSERT IGNORE INTO `ark_role_permissions` (`role_id`, `permission_id`)
SELECT r.id, p.id FROM `ark_roles` r, `ark_permissions` p
WHERE r.name = 'finance'
  AND p.code IN (
    'commission:read_own','commission:read_all','commission:write','commission:settle','commission:export'
  );

-- 初始 super_admin 账号（密码由后端启动时自动生成 bcrypt hash）
-- 密码: Admin@leisa2026，must_change_password=1 强制首次改密
-- password_hash 为占位符，后端 init_admin 脚本会自动修正
INSERT IGNORE INTO `ark_users` (
  `username`, `password_hash`, `real_name`, `is_active`, `must_change_password`
) VALUES (
  'admin',
  '__PENDING_HASH__',
  '系统管理员',
  1,
  1
);

-- 给初始账号分配 super_admin 角色
INSERT IGNORE INTO `ark_user_roles` (`user_id`, `role_id`)
SELECT u.id, r.id FROM `ark_users` u, `ark_roles` r
WHERE u.username = 'admin' AND r.name = 'super_admin';
