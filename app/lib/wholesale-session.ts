import { ensureDatabase, getD1 } from "../../db/runtime";
import type { WholesaleAccount } from "./types";

const COOKIE_NAME = "leshine_wholesale_session";

export function readSessionToken(cookieHeader: string | null) {
  if (!cookieHeader) return null;
  const item = cookieHeader.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${COOKIE_NAME}=`));
  return item ? decodeURIComponent(item.slice(COOKIE_NAME.length + 1)) : null;
}

export async function getWholesaleAccount(cookieHeader: string | null): Promise<WholesaleAccount | null> {
  const token = readSessionToken(cookieHeader);
  if (!token) return null;
  await ensureDatabase();
  const row = await getD1().prepare(`SELECT a.id, a.company_name AS companyName, a.phone, a.level,
    a.sales_person AS salesPerson, a.note FROM wholesale_sessions s
    JOIN wholesale_accounts a ON a.id = s.account_id
    WHERE s.token = ? AND s.expires_at > ? AND a.status = 'active' LIMIT 1`)
    .bind(token, new Date().toISOString()).first<WholesaleAccount>();
  return row ?? null;
}

export function sessionCookie(token: string, secure: boolean) {
  return `${COOKIE_NAME}=${encodeURIComponent(token)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800${secure ? "; Secure" : ""}`;
}

export function clearSessionCookie(secure: boolean) {
  return `${COOKIE_NAME}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0${secure ? "; Secure" : ""}`;
}
