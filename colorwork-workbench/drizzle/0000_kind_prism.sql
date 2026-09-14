CREATE TABLE `allowed_accounts` (
	`email` text PRIMARY KEY NOT NULL,
	`display_name` text NOT NULL,
	`role` text DEFAULT 'member' NOT NULL,
	`enabled` integer DEFAULT true NOT NULL,
	`added_by` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `artifacts` (
	`id` text PRIMARY KEY NOT NULL,
	`owner_user_id` text NOT NULL,
	`owner_email` text NOT NULL,
	`owner_display_name` text NOT NULL,
	`source_template_id` text NOT NULL,
	`source_artifact_id` text,
	`name` text NOT NULL,
	`config_json` text NOT NULL,
	`jpg_key` text NOT NULL,
	`psd_key` text NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_artifacts_owner_created` ON `artifacts` (`owner_user_id`,`created_at`);--> statement-breakpoint
CREATE INDEX `idx_artifacts_template_created` ON `artifacts` (`source_template_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `template_files` (
	`template_id` text PRIMARY KEY NOT NULL,
	`source_psd_key` text NOT NULL,
	`reference_jpg_key` text NOT NULL,
	`source_psd_name` text NOT NULL,
	`reference_jpg_name` text NOT NULL,
	`imported_by` text NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `users` (
	`id` text PRIMARY KEY NOT NULL,
	`email` text NOT NULL,
	`display_name` text NOT NULL,
	`role` text NOT NULL,
	`last_seen_at` text NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_users_email` ON `users` (`email`);