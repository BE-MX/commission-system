ALTER TABLE `artifacts` ADD `status` text DEFAULT 'uploading' NOT NULL;--> statement-breakpoint
ALTER TABLE `artifacts` ADD `jpg_size` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `artifacts` ADD `psd_size` integer DEFAULT 0 NOT NULL;