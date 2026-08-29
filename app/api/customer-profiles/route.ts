import { ensureDatabase, getD1 } from "../../../db/runtime";
import { requireAdminApi } from "../../lib/admin-auth";

export const dynamic = "force-dynamic";

export async function GET() {
  const unauthorized = await requireAdminApi();
  if (unauthorized) return unauthorized;
  await ensureDatabase();
  const rows = await getD1().prepare(`SELECT id, phone, channel, display_name AS displayName, store_name AS storeName,
    level, sales_person AS salesPerson, customer_service AS customerService, note, referral_code AS referralCode,
    status, created_at AS createdAt, last_login_at AS lastLoginAt FROM customer_profiles ORDER BY id DESC`).all();
  return Response.json({ customers: rows.results });
}
