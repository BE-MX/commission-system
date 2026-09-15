CREATE TABLE `local_sessions` (
	`token` text PRIMARY KEY NOT NULL,
	`username` text NOT NULL,
	`created_at` text NOT NULL,
	`expires_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_local_sessions_expires` ON `local_sessions` (`expires_at`);--> statement-breakpoint
CREATE INDEX `idx_local_sessions_username` ON `local_sessions` (`username`);