import { env } from "cloudflare:workers";

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
      created_at TEXT NOT NULL
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_products_status_level ON products(status, min_level)"),
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
  ]);

  await db.prepare("PRAGMA optimize").run();

  const levelCount = await db.prepare("SELECT COUNT(*) AS total FROM wholesale_levels").first<{ total: number }>();
  if (!levelCount?.total) {
    await db.batch([
      db.prepare("INSERT INTO wholesale_levels (code, name, threshold, rank) VALUES (?, ?, ?, ?)").bind("retail", "零售会员", 0, 0),
      db.prepare("INSERT INTO wholesale_levels (code, name, threshold, rank) VALUES (?, ?, ?, ?)").bind("a", "批发 A", 5000, 1),
      db.prepare("INSERT INTO wholesale_levels (code, name, threshold, rank) VALUES (?, ?, ?, ?)").bind("b", "批发 B", 20000, 2),
    ]);
  }

  const productCount = await db.prepare("SELECT COUNT(*) AS total FROM products").first<{ total: number }>();
  if (!productCount?.total) {
    const now = new Date().toISOString();
    await db.batch([
      db.prepare("INSERT INTO products (name, material, length, color, retail_price, price_a, price_b, min_level, stock, status, tone, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").bind("法式轻盈波浪", "真人发", "45cm", "蜜茶棕", 899, 699, 599, "retail", 86, "active", "honey", now),
      db.prepare("INSERT INTO products (name, material, length, color, retail_price, price_a, price_b, min_level, stock, status, tone, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").bind("自然头皮直发", "真人发", "55cm", "自然黑", 1299, 999, 849, "a", 42, "active", "espresso", now),
      db.prepare("INSERT INTO products (name, material, length, color, retail_price, price_a, price_b, min_level, stock, status, tone, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").bind("高定蕾丝卷发", "真人发", "60cm", "栗棕色", 1899, 1499, 1299, "b", 18, "active", "chestnut", now),
      db.prepare("INSERT INTO products (name, material, length, color, retail_price, price_a, price_b, min_level, stock, status, tone, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").bind("空气感短发", "高温丝", "30cm", "自然黑", 499, 359, 299, "retail", 120, "active", "charcoal", now),
    ]);
  }

  const accountCount = await db.prepare("SELECT COUNT(*) AS total FROM wholesale_accounts").first<{ total: number }>();
  if (!accountCount?.total) {
    const now = new Date().toISOString();
    await db.batch([
      db.prepare("INSERT INTO wholesale_accounts (company_name, phone, level, sales_person, note, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)").bind("青岛尚美发制品", "13800132031", "b", "李娜", "长期客户", "active", now),
      db.prepare("INSERT INTO wholesale_accounts (company_name, phone, level, sales_person, note, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)").bind("济南悦己造型", "18600167712", "a", "王海", "关注短发款", "active", now),
    ]);
  }
}
