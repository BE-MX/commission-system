CREATE TABLE `products` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`name` text NOT NULL,
	`material` text DEFAULT '真人发' NOT NULL,
	`length` text DEFAULT '45cm' NOT NULL,
	`color` text DEFAULT '自然黑' NOT NULL,
	`retail_price` real NOT NULL,
	`price_a` real NOT NULL,
	`price_b` real NOT NULL,
	`min_level` text DEFAULT 'retail' NOT NULL,
	`stock` integer DEFAULT 0 NOT NULL,
	`status` text DEFAULT 'active' NOT NULL,
	`tone` text DEFAULT 'espresso' NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `wholesale_levels` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`code` text NOT NULL,
	`name` text NOT NULL,
	`threshold` real DEFAULT 0 NOT NULL,
	`rank` integer DEFAULT 0 NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `wholesale_levels_code_unique` ON `wholesale_levels` (`code`);