CREATE TABLE `runtime_assets` (
	`asset_key` text PRIMARY KEY NOT NULL,
	`sha256` text NOT NULL,
	`size` integer NOT NULL,
	`uploaded_by` text NOT NULL,
	`updated_at` text NOT NULL
);
