CREATE TABLE `retail_ai_tryon_grants` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`phone` text NOT NULL,
	`token` text NOT NULL,
	`expires_at` text NOT NULL,
	`claim_id` text,
	`claimed_at` text,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `retail_ai_tryon_grants_phone_unique` ON `retail_ai_tryon_grants` (`phone`);--> statement-breakpoint
CREATE UNIQUE INDEX `retail_ai_tryon_grants_token_unique` ON `retail_ai_tryon_grants` (`token`);--> statement-breakpoint
CREATE UNIQUE INDEX `retail_ai_tryon_grants_claim_id_unique` ON `retail_ai_tryon_grants` (`claim_id`);--> statement-breakpoint
CREATE INDEX `idx_retail_ai_tryon_token_expiry` ON `retail_ai_tryon_grants` (`token`,`expires_at`);