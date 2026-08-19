CREATE TABLE `wholesale_access_logs` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`account_id` integer,
	`phone` text NOT NULL,
	`level` text,
	`sales_person` text,
	`result` text NOT NULL,
	`access_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_wholesale_access_logs_time` ON `wholesale_access_logs` (`access_at`);--> statement-breakpoint
CREATE TABLE `wholesale_accounts` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`company_name` text NOT NULL,
	`phone` text NOT NULL,
	`level` text DEFAULT 'a' NOT NULL,
	`sales_person` text DEFAULT '未分配' NOT NULL,
	`note` text DEFAULT '' NOT NULL,
	`status` text DEFAULT 'active' NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `wholesale_accounts_phone_unique` ON `wholesale_accounts` (`phone`);--> statement-breakpoint
CREATE TABLE `wholesale_sessions` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`token` text NOT NULL,
	`account_id` integer NOT NULL,
	`expires_at` text NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `wholesale_sessions_token_unique` ON `wholesale_sessions` (`token`);--> statement-breakpoint
CREATE INDEX `idx_wholesale_sessions_account` ON `wholesale_sessions` (`account_id`);--> statement-breakpoint
PRAGMA optimize;
