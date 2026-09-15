CREATE TABLE `template_source_state` (
	`template_id` text PRIMARY KEY NOT NULL,
	`revision` integer DEFAULT 0 NOT NULL,
	`current_version_id` text,
	`next_version_number` integer DEFAULT 1 NOT NULL,
	`last_mutation_id` text,
	`updated_by_user_id` text,
	`updated_by_email` text,
	`updated_by_display_name` text,
	`updated_at` text
);
--> statement-breakpoint
CREATE TABLE `template_source_versions` (
	`id` text PRIMARY KEY NOT NULL,
	`template_id` text NOT NULL,
	`version_number` integer NOT NULL,
	`status` text DEFAULT 'uploading' NOT NULL,
	`source_psd_key` text NOT NULL,
	`reference_jpg_key` text NOT NULL,
	`source_psd_name` text NOT NULL,
	`reference_jpg_name` text NOT NULL,
	`source_psd_size` integer DEFAULT 0 NOT NULL,
	`reference_jpg_size` integer DEFAULT 0 NOT NULL,
	`config_json` text,
	`asset_manifest_json` text DEFAULT '{}' NOT NULL,
	`diff_json` text,
	`unresolved_json` text DEFAULT '[]' NOT NULL,
	`failure_reason` text,
	`created_by_user_id` text NOT NULL,
	`created_by_email` text NOT NULL,
	`created_by_display_name` text NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`activated_at` text
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_template_source_versions_template_number` ON `template_source_versions` (`template_id`,`version_number`);--> statement-breakpoint
CREATE INDEX `idx_template_source_versions_template_status` ON `template_source_versions` (`template_id`,`status`);--> statement-breakpoint
CREATE INDEX `idx_template_source_versions_template_created` ON `template_source_versions` (`template_id`,`created_at`);--> statement-breakpoint
ALTER TABLE `master_versions` ADD `source_version_id` text;