CREATE TABLE `retail_access_logs` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`phone` text NOT NULL,
	`result` text NOT NULL,
	`access_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_retail_access_logs_time` ON `retail_access_logs` (`access_at`);--> statement-breakpoint
CREATE TABLE `retail_sessions` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`token` text NOT NULL,
	`phone` text NOT NULL,
	`expires_at` text NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `retail_sessions_token_unique` ON `retail_sessions` (`token`);--> statement-breakpoint
CREATE INDEX `idx_retail_sessions_phone` ON `retail_sessions` (`phone`);--> statement-breakpoint
PRAGMA optimize;
