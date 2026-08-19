import { ensureDatabase, getD1 } from "../../../db/runtime";

export const dynamic = "force-dynamic";

export async function GET() {
  await ensureDatabase();
  const rows = await getD1().prepare(`SELECT l.id, a.company_name AS companyName, l.phone, l.level,
    l.sales_person AS salesPerson, l.result, l.access_at AS accessAt
    FROM wholesale_access_logs l LEFT JOIN wholesale_accounts a ON a.id = l.account_id
    ORDER BY l.access_at DESC LIMIT 100`).all();
  return Response.json({ logs: rows.results });
}
