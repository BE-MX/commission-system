CREATE TABLE `inventory_events` (
	`id` text PRIMARY KEY NOT NULL,
	`template_id` text NOT NULL,
	`spec_id` text NOT NULL,
	`event_type` text NOT NULL,
	`from_status` text,
	`to_status` text NOT NULL,
	`inventory_revision` integer NOT NULL,
	`actor_user_id` text NOT NULL,
	`actor_email` text NOT NULL,
	`actor_display_name` text NOT NULL,
	`occurred_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_inventory_events_template_revision` ON `inventory_events` (`template_id`,`inventory_revision`);--> statement-breakpoint
CREATE INDEX `idx_inventory_events_spec_time` ON `inventory_events` (`spec_id`,`occurred_at`);--> statement-breakpoint
CREATE TABLE `inventory_states` (
	`spec_id` text PRIMARY KEY NOT NULL,
	`template_id` text NOT NULL,
	`status` text NOT NULL,
	`revision` integer DEFAULT 1 NOT NULL,
	`updated_by_user_id` text NOT NULL,
	`updated_by_email` text NOT NULL,
	`updated_by_display_name` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_inventory_states_template` ON `inventory_states` (`template_id`);--> statement-breakpoint
CREATE TABLE `inventory_template_state` (
	`template_id` text PRIMARY KEY NOT NULL,
	`revision` integer DEFAULT 0 NOT NULL,
	`last_mutation_id` text,
	`updated_by_user_id` text,
	`updated_by_email` text,
	`updated_by_display_name` text,
	`updated_at` text
);
--> statement-breakpoint
CREATE TABLE `master_specs` (
	`id` text PRIMARY KEY NOT NULL,
	`business_key` text NOT NULL,
	`template_id` text NOT NULL,
	`entry_id` text NOT NULL,
	`color_id` text NOT NULL,
	`length` integer NOT NULL,
	`created_by_user_id` text NOT NULL,
	`created_by_email` text NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_master_specs_business_key` ON `master_specs` (`business_key`);--> statement-breakpoint
CREATE UNIQUE INDEX `idx_master_specs_template_entry_length` ON `master_specs` (`template_id`,`entry_id`,`length`);--> statement-breakpoint
CREATE INDEX `idx_master_specs_template` ON `master_specs` (`template_id`);--> statement-breakpoint
CREATE TABLE `master_template_state` (
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
CREATE TABLE `master_version_entries` (
	`version_id` text NOT NULL,
	`entry_id` text NOT NULL,
	`color_id` text NOT NULL,
	`lengths_json` text NOT NULL,
	`hot` integer DEFAULT false NOT NULL,
	`section_key` text,
	`display_order` integer NOT NULL,
	PRIMARY KEY(`version_id`, `entry_id`)
);
--> statement-breakpoint
CREATE INDEX `idx_master_version_entries_order` ON `master_version_entries` (`version_id`,`display_order`);--> statement-breakpoint
CREATE TABLE `master_version_specs` (
	`version_id` text NOT NULL,
	`spec_id` text NOT NULL,
	`display_order` integer NOT NULL,
	PRIMARY KEY(`version_id`, `spec_id`)
);
--> statement-breakpoint
CREATE INDEX `idx_master_version_specs_order` ON `master_version_specs` (`version_id`,`display_order`);--> statement-breakpoint
CREATE TABLE `master_versions` (
	`id` text PRIMARY KEY NOT NULL,
	`template_id` text NOT NULL,
	`version_number` integer NOT NULL,
	`action` text NOT NULL,
	`restored_from_version_id` text,
	`note` text,
	`created_by_user_id` text NOT NULL,
	`created_by_email` text NOT NULL,
	`created_by_display_name` text NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `idx_master_versions_template_number` ON `master_versions` (`template_id`,`version_number`);--> statement-breakpoint
CREATE INDEX `idx_master_versions_template_created` ON `master_versions` (`template_id`,`created_at`);