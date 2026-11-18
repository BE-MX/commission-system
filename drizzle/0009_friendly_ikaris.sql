CREATE TABLE `logistics_query_budget` (
	`name` text PRIMARY KEY NOT NULL,
	`window_key` text NOT NULL,
	`used` integer DEFAULT 0 NOT NULL
);
--> statement-breakpoint
CREATE TABLE `order_logistics` (
	`order_id` integer PRIMARY KEY NOT NULL,
	`tracking_no` text DEFAULT '' NOT NULL,
	`phone_last4` text DEFAULT '' NOT NULL,
	`revision` text NOT NULL,
	`events` text DEFAULT '[]' NOT NULL,
	`state` text DEFAULT 'pending' NOT NULL,
	`checked_at` text,
	`next_check_at` text,
	`lease_token` text,
	`last_error` text DEFAULT '' NOT NULL,
	`failures` integer DEFAULT 0 NOT NULL,
	`sandbox` integer DEFAULT 0 NOT NULL,
	FOREIGN KEY (`order_id`) REFERENCES `orders`(`id`) ON UPDATE no action ON DELETE cascade
);
