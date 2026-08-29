import { env } from "cloudflare:workers";
import { featuredProducts } from "./product-data";

let ready: Promise<void> | null = null;

export function getD1() {
  if (!env.DB) throw new Error("数据库暂时不可用");
  return env.DB;
}

export function ensureDatabase() {
  if (!ready) ready = initialize();
  return ready;
}

async function initialize() {
  const db = getD1();
  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS wholesale_levels (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      code TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      threshold REAL NOT NULL DEFAULT 0,
      rank INTEGER NOT NULL DEFAULT 0
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS products (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      material TEXT NOT NULL DEFAULT '真人发',
      length TEXT NOT NULL DEFAULT '45cm',
      color TEXT NOT NULL DEFAULT '自然黑',
      retail_price REAL NOT NULL,
      price_a REAL NOT NULL,
      price_b REAL NOT NULL,
      min_level TEXT NOT NULL DEFAULT 'retail',
      stock INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'active',
      tone TEXT NOT NULL DEFAULT 'espresso',
      category TEXT NOT NULL DEFAULT '短发系列',
      sku TEXT NOT NULL DEFAULT '',
      construction TEXT NOT NULL DEFAULT '',
      hair_volume TEXT NOT NULL DEFAULT '',
      parting TEXT NOT NULL DEFAULT '',
      craft TEXT NOT NULL DEFAULT '',
      description TEXT NOT NULL DEFAULT '',
      highlights TEXT NOT NULL DEFAULT '[]',
      audience TEXT NOT NULL DEFAULT '[]',
      scenarios TEXT NOT NULL DEFAULT '[]',
      images TEXT NOT NULL DEFAULT '[]',
      video_url TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_products_status_level ON products(status, min_level)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS app_metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS wholesale_accounts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      company_name TEXT NOT NULL,
      phone TEXT NOT NULL UNIQUE,
      level TEXT NOT NULL DEFAULT 'a',
      sales_person TEXT NOT NULL DEFAULT '未分配',
      note TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'active',
      created_at TEXT NOT NULL
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS wholesale_sessions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      token TEXT NOT NULL UNIQUE,
      account_id INTEGER NOT NULL,
      expires_at TEXT NOT NULL,
      created_at TEXT NOT NULL
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_wholesale_sessions_account ON wholesale_sessions(account_id)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS wholesale_access_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      account_id INTEGER,
      phone TEXT NOT NULL,
      level TEXT,
      sales_person TEXT,
      result TEXT NOT NULL,
      access_at TEXT NOT NULL
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_wholesale_access_logs_time ON wholesale_access_logs(access_at)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS retail_sessions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      token TEXT NOT NULL UNIQUE,
      phone TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      created_at TEXT NOT NULL
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_retail_sessions_phone ON retail_sessions(phone)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS retail_access_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      phone TEXT NOT NULL,
      result TEXT NOT NULL,
      access_at TEXT NOT NULL
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_retail_access_logs_time ON retail_access_logs(access_at)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS customer_profiles (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      phone TEXT NOT NULL UNIQUE,
      channel TEXT NOT NULL DEFAULT 'retail',
      display_name TEXT NOT NULL DEFAULT '莱莎会员',
      store_name TEXT NOT NULL DEFAULT '',
      level TEXT NOT NULL DEFAULT 'retail',
      sales_person TEXT NOT NULL DEFAULT '林青',
      customer_service TEXT NOT NULL DEFAULT '小莱客服',
      note TEXT NOT NULL DEFAULT '',
      referral_code TEXT NOT NULL UNIQUE,
      status TEXT NOT NULL DEFAULT 'active',
      created_at TEXT NOT NULL,
      last_login_at TEXT
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_customer_profiles_channel_level ON customer_profiles(channel, level)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS sales_people (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      phone TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT '销售顾问',
      promo_code TEXT NOT NULL UNIQUE,
      store_code TEXT NOT NULL UNIQUE,
      customer_service TEXT NOT NULL DEFAULT '小莱客服',
      status TEXT NOT NULL DEFAULT 'active',
      created_at TEXT NOT NULL
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS orders (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      order_no TEXT NOT NULL UNIQUE,
      channel TEXT NOT NULL,
      customer_phone TEXT NOT NULL,
      customer_name TEXT NOT NULL,
      level TEXT NOT NULL DEFAULT 'retail',
      sales_person TEXT NOT NULL DEFAULT '未分配',
      status TEXT NOT NULL DEFAULT '待发货',
      payment_status TEXT NOT NULL DEFAULT '已支付',
      logistics_company TEXT NOT NULL DEFAULT '',
      tracking_no TEXT NOT NULL DEFAULT '',
      logistics_status TEXT NOT NULL DEFAULT '等待仓库发货',
      item_count INTEGER NOT NULL DEFAULT 0,
      amount REAL NOT NULL DEFAULT 0,
      commission_amount REAL NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      shipped_at TEXT
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_orders_customer_time ON orders(customer_phone, created_at)"),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_orders_status_time ON orders(status, created_at)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS order_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      order_id INTEGER NOT NULL,
      product_id INTEGER NOT NULL,
      product_name TEXT NOT NULL,
      unit_price REAL NOT NULL,
      quantity INTEGER NOT NULL
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS promotions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      audience TEXT NOT NULL DEFAULT 'new',
      benefit_type TEXT NOT NULL DEFAULT 'coupon',
      benefit_value REAL NOT NULL DEFAULT 0,
      description TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'active',
      ends_at TEXT,
      created_at TEXT NOT NULL
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS referrals (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      code TEXT NOT NULL,
      owner_name TEXT NOT NULL,
      visitor_phone TEXT NOT NULL DEFAULT '',
      order_no TEXT NOT NULL DEFAULT '',
      amount REAL NOT NULL DEFAULT 0,
      commission REAL NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT '已绑定',
      created_at TEXT NOT NULL
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_referrals_code_time ON referrals(code, created_at)"),
  ]);

  const productColumns = await db.prepare("PRAGMA table_info(products)").all<{ name: string }>();
  const productColumnNames = new Set(productColumns.results.map((item) => item.name));
  if (!productColumnNames.has("category")) await db.prepare("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT '短发系列'").run();
  if (!productColumnNames.has("sku")) await db.prepare("ALTER TABLE products ADD COLUMN sku TEXT NOT NULL DEFAULT ''").run();
  if (!productColumnNames.has("construction")) await db.prepare("ALTER TABLE products ADD COLUMN construction TEXT NOT NULL DEFAULT ''").run();
  if (!productColumnNames.has("hair_volume")) await db.prepare("ALTER TABLE products ADD COLUMN hair_volume TEXT NOT NULL DEFAULT ''").run();
  if (!productColumnNames.has("parting")) await db.prepare("ALTER TABLE products ADD COLUMN parting TEXT NOT NULL DEFAULT ''").run();
  if (!productColumnNames.has("craft")) await db.prepare("ALTER TABLE products ADD COLUMN craft TEXT NOT NULL DEFAULT ''").run();
  if (!productColumnNames.has("description")) await db.prepare("ALTER TABLE products ADD COLUMN description TEXT NOT NULL DEFAULT ''").run();
  if (!productColumnNames.has("highlights")) await db.prepare("ALTER TABLE products ADD COLUMN highlights TEXT NOT NULL DEFAULT '[]'").run();
  if (!productColumnNames.has("audience")) await db.prepare("ALTER TABLE products ADD COLUMN audience TEXT NOT NULL DEFAULT '[]'").run();
  if (!productColumnNames.has("scenarios")) await db.prepare("ALTER TABLE products ADD COLUMN scenarios TEXT NOT NULL DEFAULT '[]'").run();
  if (!productColumnNames.has("images")) await db.prepare("ALTER TABLE products ADD COLUMN images TEXT NOT NULL DEFAULT '[]'").run();
  if (!productColumnNames.has("video_url")) await db.prepare("ALTER TABLE products ADD COLUMN video_url TEXT NOT NULL DEFAULT ''").run();

  await db.prepare("PRAGMA optimize").run();

  const levelCount = await db.prepare("SELECT COUNT(*) AS total FROM wholesale_levels").first<{ total: number }>();
  if (!levelCount?.total) {
    await db.batch([
      db.prepare("INSERT INTO wholesale_levels (code, name, threshold, rank) VALUES (?, ?, ?, ?)").bind("retail", "零售会员", 0, 0),
      db.prepare("INSERT INTO wholesale_levels (code, name, threshold, rank) VALUES (?, ?, ?, ?)").bind("a", "批发 A", 5000, 1),
      db.prepare("INSERT INTO wholesale_levels (code, name, threshold, rank) VALUES (?, ?, ?, ?)").bind("b", "批发 B", 20000, 2),
    ]);
  }

  const catalogVersion = await db.prepare("SELECT value FROM app_metadata WHERE key = 'product_catalog_version'").first<{ value: string }>();
  if (catalogVersion?.value !== "12-styles-2026-08") {
    const now = new Date().toISOString();
    await db.prepare("DELETE FROM products").run();
    const inserts = featuredProducts.map((product) => db.prepare(`INSERT INTO products
      (name, material, length, color, retail_price, price_a, price_b, min_level, stock, status,
       tone, category, sku, construction, hair_volume, parting, craft, description, highlights,
       audience, scenarios, images, video_url, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(product.name, product.material, product.length, product.color, product.retailPrice,
        product.priceA, product.priceB, product.minLevel, product.stock, product.status, product.tone,
        product.category, product.sku, product.construction, product.hairVolume, product.parting,
        product.craft, product.description, JSON.stringify(product.highlights), JSON.stringify(product.audience),
        JSON.stringify(product.scenarios), JSON.stringify(product.images), product.videoUrl, now));
    await db.batch(inserts);
    await db.prepare("INSERT OR REPLACE INTO app_metadata (key, value) VALUES ('product_catalog_version', '12-styles-2026-08')").run();
  }

  const accountCount = await db.prepare("SELECT COUNT(*) AS total FROM wholesale_accounts").first<{ total: number }>();
  if (!accountCount?.total) {
    const now = new Date().toISOString();
    await db.batch([
      db.prepare("INSERT INTO wholesale_accounts (company_name, phone, level, sales_person, note, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)").bind("青岛尚美发制品", "13800132031", "b", "李娜", "长期客户", "active", now),
      db.prepare("INSERT INTO wholesale_accounts (company_name, phone, level, sales_person, note, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)").bind("济南悦己造型", "18600167712", "a", "王海", "关注短发款", "active", now),
    ]);
  }

  const salesCount = await db.prepare("SELECT COUNT(*) AS total FROM sales_people").first<{ total: number }>();
  if (!salesCount?.total) {
    const now = new Date().toISOString();
    await db.batch([
      db.prepare("INSERT INTO sales_people (name, phone, role, promo_code, store_code, customer_service, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)").bind("李娜", "18600001231", "大客户经理", "LINA88", "STORE-LN", "小莱客服", now),
      db.prepare("INSERT INTO sales_people (name, phone, role, promo_code, store_code, customer_service, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)").bind("王海", "18500006712", "渠道销售", "WANG66", "STORE-WH", "小美客服", now),
      db.prepare("INSERT INTO sales_people (name, phone, role, promo_code, store_code, customer_service, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)").bind("林青", "18900003821", "零售顾问", "LINQING", "STORE-LQ", "小莱客服", now),
    ]);
  }

  const profileCount = await db.prepare("SELECT COUNT(*) AS total FROM customer_profiles").first<{ total: number }>();
  if (!profileCount?.total) {
    const now = new Date().toISOString();
    await db.batch([
      db.prepare("INSERT INTO customer_profiles (phone, channel, display_name, store_name, level, sales_person, customer_service, note, referral_code, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)").bind("13800132031", "wholesale", "青岛尚美发制品", "尚美假发馆", "b", "李娜", "小莱客服", "长期合作客户", "D-2031", now),
      db.prepare("INSERT INTO customer_profiles (phone, channel, display_name, store_name, level, sales_person, customer_service, note, referral_code, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)").bind("18600167712", "wholesale", "济南悦己造型", "悦己造型", "a", "王海", "小美客服", "关注短发款", "D-7712", now),
      db.prepare("INSERT INTO customer_profiles (phone, channel, display_name, store_name, level, sales_person, customer_service, note, referral_code, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)").bind("13900001001", "retail", "莱莎新会员", "", "retail", "林青", "小莱客服", "演示零售账户", "D-1001", now),
    ]);
  }

  const promotionCount = await db.prepare("SELECT COUNT(*) AS total FROM promotions").first<{ total: number }>();
  if (!promotionCount?.total) {
    const now = new Date().toISOString();
    const endsAt = new Date(Date.now() + 90 * 24 * 60 * 60 * 1000).toISOString();
    await db.batch([
      db.prepare("INSERT INTO promotions (title, audience, benefit_type, benefit_value, description, status, ends_at, created_at) VALUES (?, 'new', 'coupon', ?, ?, 'active', ?, ?)").bind("新用户首单礼", 100, "首单满699元立减100元，每位新用户限领一次", endsAt, now),
      db.prepare("INSERT INTO promotions (title, audience, benefit_type, benefit_value, description, status, ends_at, created_at) VALUES (?, 'all', 'shipping', ?, ?, 'active', ?, ?)").bind("满额包邮", 999, "单笔订单满999元享全国包邮", endsAt, now),
    ]);
  }

  const orderCount = await db.prepare("SELECT COUNT(*) AS total FROM orders").first<{ total: number }>();
  if (!orderCount?.total) {
    const now = new Date();
    const earlier = new Date(now.getTime() - 3 * 24 * 60 * 60 * 1000).toISOString();
    await db.batch([
      db.prepare("INSERT INTO orders (order_no, channel, customer_phone, customer_name, level, sales_person, status, payment_status, logistics_company, tracking_no, logistics_status, item_count, amount, commission_amount, created_at, shipped_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").bind("LS202608260018", "wholesale", "13800132031", "尚美假发馆", "b", "李娜", "运输中", "已支付", "顺丰速运", "SF1420260826018", "已离开济南转运中心，运输中", 12, 7188, 215.64, earlier, earlier),
      db.prepare("INSERT INTO orders (order_no, channel, customer_phone, customer_name, level, sales_person, status, payment_status, logistics_company, tracking_no, logistics_status, item_count, amount, commission_amount, created_at, shipped_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").bind("LS202608290006", "wholesale", "18600167712", "悦己造型", "a", "王海", "待发货", "已支付", "", "", "山东仓正在配货", 6, 4194, 125.82, now.toISOString(), null),
    ]);
  }
}
