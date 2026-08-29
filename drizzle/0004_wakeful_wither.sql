CREATE TABLE `customer_profiles` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`phone` text NOT NULL,
	`channel` text DEFAULT 'retail' NOT NULL,
	`display_name` text DEFAULT '莱莎会员' NOT NULL,
	`store_name` text DEFAULT '' NOT NULL,
	`level` text DEFAULT 'retail' NOT NULL,
	`sales_person` text DEFAULT '林青' NOT NULL,
	`customer_service` text DEFAULT '小莱客服' NOT NULL,
	`note` text DEFAULT '' NOT NULL,
	`referral_code` text NOT NULL,
	`status` text DEFAULT 'active' NOT NULL,
	`created_at` text NOT NULL,
	`last_login_at` text
);
--> statement-breakpoint
CREATE UNIQUE INDEX `customer_profiles_phone_unique` ON `customer_profiles` (`phone`);--> statement-breakpoint
CREATE UNIQUE INDEX `customer_profiles_referral_code_unique` ON `customer_profiles` (`referral_code`);--> statement-breakpoint
CREATE INDEX `idx_customer_profiles_channel_level` ON `customer_profiles` (`channel`,`level`);--> statement-breakpoint
CREATE TABLE `order_items` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`order_id` integer NOT NULL,
	`product_id` integer NOT NULL,
	`product_name` text NOT NULL,
	`unit_price` real NOT NULL,
	`quantity` integer NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_order_items_order` ON `order_items` (`order_id`);--> statement-breakpoint
CREATE TABLE `orders` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`order_no` text NOT NULL,
	`channel` text NOT NULL,
	`customer_phone` text NOT NULL,
	`customer_name` text NOT NULL,
	`level` text DEFAULT 'retail' NOT NULL,
	`sales_person` text DEFAULT '未分配' NOT NULL,
	`status` text DEFAULT '待发货' NOT NULL,
	`payment_status` text DEFAULT '已支付' NOT NULL,
	`logistics_company` text DEFAULT '' NOT NULL,
	`tracking_no` text DEFAULT '' NOT NULL,
	`logistics_status` text DEFAULT '等待仓库发货' NOT NULL,
	`item_count` integer DEFAULT 0 NOT NULL,
	`amount` real DEFAULT 0 NOT NULL,
	`commission_amount` real DEFAULT 0 NOT NULL,
	`created_at` text NOT NULL,
	`shipped_at` text
);
--> statement-breakpoint
CREATE UNIQUE INDEX `orders_order_no_unique` ON `orders` (`order_no`);--> statement-breakpoint
CREATE INDEX `idx_orders_customer_time` ON `orders` (`customer_phone`,`created_at`);--> statement-breakpoint
CREATE INDEX `idx_orders_status_time` ON `orders` (`status`,`created_at`);--> statement-breakpoint
CREATE TABLE `promotions` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`title` text NOT NULL,
	`audience` text DEFAULT 'new' NOT NULL,
	`benefit_type` text DEFAULT 'coupon' NOT NULL,
	`benefit_value` real DEFAULT 0 NOT NULL,
	`description` text DEFAULT '' NOT NULL,
	`status` text DEFAULT 'active' NOT NULL,
	`ends_at` text,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `referrals` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`code` text NOT NULL,
	`owner_name` text NOT NULL,
	`visitor_phone` text DEFAULT '' NOT NULL,
	`order_no` text DEFAULT '' NOT NULL,
	`amount` real DEFAULT 0 NOT NULL,
	`commission` real DEFAULT 0 NOT NULL,
	`status` text DEFAULT '已绑定' NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_referrals_code_time` ON `referrals` (`code`,`created_at`);--> statement-breakpoint
CREATE TABLE `sales_people` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`name` text NOT NULL,
	`phone` text NOT NULL,
	`role` text DEFAULT '销售顾问' NOT NULL,
	`promo_code` text NOT NULL,
	`store_code` text NOT NULL,
	`customer_service` text DEFAULT '小莱客服' NOT NULL,
	`status` text DEFAULT 'active' NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `sales_people_promo_code_unique` ON `sales_people` (`promo_code`);--> statement-breakpoint
CREATE UNIQUE INDEX `sales_people_store_code_unique` ON `sales_people` (`store_code`);--> statement-breakpoint
ALTER TABLE `products` ADD `category` text DEFAULT '短发系列' NOT NULL;--> statement-breakpoint
ALTER TABLE `products` ADD `sku` text DEFAULT '' NOT NULL;