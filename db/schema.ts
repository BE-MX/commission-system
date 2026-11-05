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
  category: text("category").notNull().default("短发系列"),
  sku: text("sku").notNull().default(""),
  construction: text("construction").notNull().default(""),
  hairVolume: text("hair_volume").notNull().default(""),
  parting: text("parting").notNull().default(""),
  craft: text("craft").notNull().default(""),
  description: text("description").notNull().default(""),
  highlights: text("highlights").notNull().default("[]"),
  audience: text("audience").notNull().default("[]"),
  scenarios: text("scenarios").notNull().default("[]"),
  images: text("images").notNull().default("[]"),
  videoUrl: text("video_url").notNull().default(""),
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

export const retailTryonEntitlements = sqliteTable("retail_tryon_entitlements", {
  phone: text("phone").primaryKey(),
  grantToken: text("grant_token").notNull().unique(),
  grantExpiresAt: text("grant_expires_at").notNull(),
  generationClaim: text("generation_claim"),
  usedAt: text("used_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [index("idx_retail_tryon_grant").on(table.grantToken)]);

export const customerProfiles = sqliteTable("customer_profiles", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  phone: text("phone").notNull().unique(),
  channel: text("channel").notNull().default("retail"),
  displayName: text("display_name").notNull().default("莱莎会员"),
  storeName: text("store_name").notNull().default(""),
  level: text("level").notNull().default("retail"),
  salesPerson: text("sales_person").notNull().default("林青"),
  customerService: text("customer_service").notNull().default("小莱客服"),
  note: text("note").notNull().default(""),
  referralCode: text("referral_code").notNull().unique(),
  status: text("status").notNull().default("active"),
  createdAt: text("created_at").notNull(),
  lastLoginAt: text("last_login_at"),
}, (table) => [index("idx_customer_profiles_channel_level").on(table.channel, table.level)]);

export const salesPeople = sqliteTable("sales_people", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  name: text("name").notNull(),
  phone: text("phone").notNull(),
  role: text("role").notNull().default("销售顾问"),
  promoCode: text("promo_code").notNull().unique(),
  storeCode: text("store_code").notNull().unique(),
  customerService: text("customer_service").notNull().default("小莱客服"),
  status: text("status").notNull().default("active"),
  createdAt: text("created_at").notNull(),
});

export const orders = sqliteTable("orders", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  orderNo: text("order_no").notNull().unique(),
  channel: text("channel").notNull(),
  customerPhone: text("customer_phone").notNull(),
  customerName: text("customer_name").notNull(),
  level: text("level").notNull().default("retail"),
  salesPerson: text("sales_person").notNull().default("未分配"),
  status: text("status").notNull().default("待发货"),
  paymentStatus: text("payment_status").notNull().default("已支付"),
  logisticsCompany: text("logistics_company").notNull().default(""),
  trackingNo: text("tracking_no").notNull().default(""),
  logisticsStatus: text("logistics_status").notNull().default("等待仓库发货"),
  itemCount: integer("item_count").notNull().default(0),
  amount: real("amount").notNull().default(0),
  commissionAmount: real("commission_amount").notNull().default(0),
  createdAt: text("created_at").notNull(),
  shippedAt: text("shipped_at"),
}, (table) => [
  index("idx_orders_customer_time").on(table.customerPhone, table.createdAt),
  index("idx_orders_status_time").on(table.status, table.createdAt),
]);

export const orderItems = sqliteTable("order_items", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  orderId: integer("order_id").notNull(),
  productId: integer("product_id").notNull(),
  productName: text("product_name").notNull(),
  unitPrice: real("unit_price").notNull(),
  quantity: integer("quantity").notNull(),
}, (table) => [index("idx_order_items_order").on(table.orderId)]);

export const promotions = sqliteTable("promotions", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  title: text("title").notNull(),
  audience: text("audience").notNull().default("new"),
  benefitType: text("benefit_type").notNull().default("coupon"),
  benefitValue: real("benefit_value").notNull().default(0),
  description: text("description").notNull().default(""),
  status: text("status").notNull().default("active"),
  endsAt: text("ends_at"),
  createdAt: text("created_at").notNull(),
});

export const referrals = sqliteTable("referrals", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  code: text("code").notNull(),
  ownerName: text("owner_name").notNull(),
  visitorPhone: text("visitor_phone").notNull().default(""),
  orderNo: text("order_no").notNull().default(""),
  amount: real("amount").notNull().default(0),
  commission: real("commission").notNull().default(0),
  status: text("status").notNull().default("已绑定"),
  createdAt: text("created_at").notNull(),
}, (table) => [index("idx_referrals_code_time").on(table.code, table.createdAt)]);
