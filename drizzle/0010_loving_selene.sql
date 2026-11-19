ALTER TABLE `order_items` ADD `variant_key` text DEFAULT '' NOT NULL;--> statement-breakpoint
ALTER TABLE `order_items` ADD `variant_label` text DEFAULT '' NOT NULL;--> statement-breakpoint
ALTER TABLE `orders` ADD `checkout_key` text;--> statement-breakpoint
ALTER TABLE `orders` ADD `checkout_hash` text;--> statement-breakpoint
CREATE UNIQUE INDEX `idx_orders_checkout_key` ON `orders` (`checkout_key`);--> statement-breakpoint
ALTER TABLE `products` ADD `variants` text DEFAULT '[]' NOT NULL;
--> statement-breakpoint
CREATE TRIGGER IF NOT EXISTS order_item_stock_guard BEFORE INSERT ON order_items BEGIN
  SELECT CASE WHEN NEW.quantity<=0 OR NEW.quantity<>CAST(NEW.quantity AS INTEGER)
    OR NOT EXISTS(SELECT 1 FROM products WHERE id=NEW.product_id AND status='active' AND stock>=NEW.quantity)
    THEN RAISE(ABORT,'INSUFFICIENT_STOCK') END;
END;
--> statement-breakpoint
CREATE TRIGGER IF NOT EXISTS order_item_stock_deduct AFTER INSERT ON order_items BEGIN
  UPDATE products SET stock=stock-NEW.quantity WHERE id=NEW.product_id;
END;
