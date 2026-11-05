CREATE TABLE `retail_tryon_entitlements` (
	`phone` text PRIMARY KEY NOT NULL,
	`grant_token` text NOT NULL,
	`grant_expires_at` text NOT NULL,
	`used_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `retail_tryon_entitlements_grant_token_unique` ON `retail_tryon_entitlements` (`grant_token`);--> statement-breakpoint
CREATE INDEX `idx_retail_tryon_grant` ON `retail_tryon_entitlements` (`grant_token`);
