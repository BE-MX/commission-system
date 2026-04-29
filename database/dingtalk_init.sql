-- 钉钉集成模块初始化
-- 执行: mysql -h <host> -u <user> -p commission_db < dingtalk_init.sql

-- 钉钉回调日志
CREATE TABLE IF NOT EXISTS `dingtalk_callback_log` (
  `id`             INT           NOT NULL AUTO_INCREMENT,
  `event_type`     VARCHAR(64)   NOT NULL                   COMMENT '事件类型',
  `raw_data`       TEXT          NOT NULL                   COMMENT '原始回调数据',
  `processed`      TINYINT(1)    NOT NULL DEFAULT 0         COMMENT '是否已处理',
  `process_result` VARCHAR(255)  DEFAULT NULL               COMMENT '处理结果',
  `created_at`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP  COMMENT '接收时间',
  `processed_at`   DATETIME      DEFAULT NULL               COMMENT '处理时间',
  PRIMARY KEY (`id`),
  INDEX `idx_callback_event_type` (`event_type`),
  INDEX `idx_callback_processed` (`processed`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='钉钉回调日志';


-- 钉钉消息发送日志
CREATE TABLE IF NOT EXISTS `dingtalk_message_log` (
  `id`            INT           NOT NULL AUTO_INCREMENT,
  `msg_type`      VARCHAR(32)   NOT NULL                   COMMENT '消息类型: markdown/action_card/text',
  `title`         VARCHAR(128)  NOT NULL                   COMMENT '消息标题',
  `content`       TEXT          NOT NULL                   COMMENT '消息内容',
  `at_mobiles`    VARCHAR(255)  DEFAULT NULL               COMMENT '@的手机号(逗号分隔)',
  `send_status`   VARCHAR(16)   NOT NULL DEFAULT 'pending' COMMENT '发送状态: pending/success/failed',
  `error_msg`     TEXT          DEFAULT NULL               COMMENT '错误信息',
  `related_type`  VARCHAR(32)   DEFAULT NULL               COMMENT '关联业务类型',
  `related_id`    VARCHAR(64)   DEFAULT NULL               COMMENT '关联业务ID',
  `created_at`    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP  COMMENT '创建时间',
  `sent_at`       DATETIME      DEFAULT NULL               COMMENT '发送时间',
  PRIMARY KEY (`id`),
  INDEX `idx_msg_status` (`send_status`),
  INDEX `idx_msg_related` (`related_type`, `related_id`),
  INDEX `idx_msg_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='钉钉消息发送日志';
