import { index, integer, real, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const wholesaleLevels = sqliteTable("wholesale_levels", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  code: text("code").notNull().unique(),
  name: text("name").notNull(),
  threshold: real("threshold").notNull().default(0),
  rank: integer("rank").notNull().default(0),
});

export const products = sqliteTable("products", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  name: text("name").notNull(),
  material: text("material").notNull().default("真人发"),
  length: text("length").notNull().default("45cm"),
  color: text("color").notNull().default("自然黑"),
  retailPrice: real("retail_price").notNull(),
  priceA: real("price_a").notNull(),
  priceB: real("price_b").notNull(),
  minLevel: text("min_level").notNull().default("retail"),
  stock: integer("stock").notNull().default(0),
  status: text("status").notNull().default("active"),
  tone: text("tone").notNull().default("espresso"),
  createdAt: text("created_at").notNull(),
}, (table) => [index("idx_products_status_level").on(table.status, table.minLevel)]);
