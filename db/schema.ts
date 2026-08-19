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

export const wholesaleAccounts = sqliteTable("wholesale_accounts", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  companyName: text("company_name").notNull(),
  phone: text("phone").notNull().unique(),
  level: text("level").notNull().default("a"),
  salesPerson: text("sales_person").notNull().default("未分配"),
  note: text("note").notNull().default(""),
  status: text("status").notNull().default("active"),
  createdAt: text("created_at").notNull(),
});

export const wholesaleSessions = sqliteTable("wholesale_sessions", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  token: text("token").notNull().unique(),
  accountId: integer("account_id").notNull(),
  expiresAt: text("expires_at").notNull(),
  createdAt: text("created_at").notNull(),
}, (table) => [index("idx_wholesale_sessions_account").on(table.accountId)]);

export const wholesaleAccessLogs = sqliteTable("wholesale_access_logs", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  accountId: integer("account_id"),
  phone: text("phone").notNull(),
  level: text("level"),
  salesPerson: text("sales_person"),
  result: text("result").notNull(),
  accessAt: text("access_at").notNull(),
}, (table) => [index("idx_wholesale_access_logs_time").on(table.accessAt)]);

export const retailSessions = sqliteTable("retail_sessions", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  token: text("token").notNull().unique(),
  phone: text("phone").notNull(),
  expiresAt: text("expires_at").notNull(),
  createdAt: text("created_at").notNull(),
}, (table) => [index("idx_retail_sessions_phone").on(table.phone)]);

export const retailAccessLogs = sqliteTable("retail_access_logs", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  phone: text("phone").notNull(),
  result: text("result").notNull(),
  accessAt: text("access_at").notNull(),
}, (table) => [index("idx_retail_access_logs_time").on(table.accessAt)]);
