import { ensureDatabase, getD1 } from "../../db/runtime";

const COOKIE_NAME = "leshine_retail_session";

export function readRetailToken(cookieHeader: string | null) {
  if (!cookieHeader) return null;
  const item = cookieHeader.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${COOKIE_NAME}=`));
  return item ? decodeURIComponent(item.slice(COOKIE_NAME.length + 1)) : null;
}

export async function getRetailPhone(cookieHeader: string | null) {
  const token = readRetailToken(cookieHeader);
  if (!token) return null;
  await ensureDatabase();
  const row = await getD1().prepare("SELECT phone FROM retail_sessions WHERE token = ? AND expires_at > ? LIMIT 1")
    .bind(token, new Date().toISOString()).first<{ phone: string }>();
  return row?.phone ?? null;
}

export function retailCookie(token: string, secure: boolean) {
  return `${COOKIE_NAME}=${encodeURIComponent(token)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800${secure ? "; Secure" : ""}`;
}

export function clearRetailCookie(secure: boolean) {
  return `${COOKIE_NAME}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0${secure ? "; Secure" : ""}`;
}
