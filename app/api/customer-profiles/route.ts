import { ensureDatabase, getD1 } from "../../../db/runtime";

export const dynamic = "force-dynamic";

export async function GET() {
  await ensureDatabase();
  const rows = await getD1().prepare(`SELECT id, phone, channel, display_name AS displayName, store_name AS storeName,
    level, sales_person AS salesPerson, customer_service AS customerService, note, referral_code AS referralCode,
    status, created_at AS createdAt, last_login_at AS lastLoginAt FROM customer_profiles ORDER BY id DESC`).all();
  return Response.json({ customers: rows.results });
}
