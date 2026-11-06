import { ensureDatabase, getD1 } from "../../db/runtime";

const GRANT_TTL_MS = 4 * 60 * 60 * 1000;
const CLAIMED_RECOVERY_TTL_MS = 15 * 24 * 60 * 60 * 1000;
const TOKEN_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export type RetailTryonGrant = {
  phone: string;
  token: string;
  expires_at: string;
  claim_id: string | null;
  claimed_at: string | null;
};

export function readTryonToken(request: Request) {
  const [scheme, token = ""] = (request.headers.get("authorization") ?? "").trim().split(/\s+/, 2);
  return scheme?.toLowerCase() === "tryon" && TOKEN_RE.test(token) ? token : null;
}

export async function issueTryonGrant(phone: string): Promise<RetailTryonGrant> {
  await ensureDatabase();
  const db = getD1();
  const now = new Date().toISOString();
  const expiresAt = new Date(Date.now() + GRANT_TTL_MS).toISOString();
  const token = crypto.randomUUID();

  // An unexpired grant is stable so simultaneous clicks cannot invalidate each other.
  await db.prepare(`INSERT OR IGNORE INTO retail_ai_tryon_grants
    (phone, token, expires_at, claim_id, claimed_at, created_at, updated_at)
    VALUES (?, ?, ?, NULL, NULL, ?, ?)`)
    .bind(phone, token, expiresAt, now, now).run();
  await db.prepare(`UPDATE retail_ai_tryon_grants
    SET token = ?, expires_at = ?, updated_at = ?
    WHERE phone = ? AND claim_id IS NULL AND expires_at <= ?`)
    .bind(token, expiresAt, now, phone, now).run();

  const grant = await db.prepare(`SELECT phone, token, expires_at, claim_id, claimed_at
    FROM retail_ai_tryon_grants WHERE phone = ? LIMIT 1`)
    .bind(phone).first<RetailTryonGrant>();
  if (!grant) throw new Error("无法创建 AI 试戴临时授权");
  return grant;
}

export async function findActiveTryonGrant(token: string) {
  await ensureDatabase();
  return getD1().prepare(`SELECT phone, token, expires_at, claim_id, claimed_at
    FROM retail_ai_tryon_grants WHERE token = ? AND expires_at > ? LIMIT 1`)
    .bind(token, new Date().toISOString()).first<RetailTryonGrant>();
}

export async function claimTryonGrant(token: string, claimId: string) {
  await ensureDatabase();
  const db = getD1();
  const now = new Date().toISOString();
  const recoveryExpiresAt = new Date(Date.now() + CLAIMED_RECOVERY_TTL_MS).toISOString();
  await db.prepare(`UPDATE retail_ai_tryon_grants
    SET claim_id = ?, claimed_at = ?, expires_at = ?, updated_at = ?
    WHERE token = ? AND expires_at > ? AND claim_id IS NULL`)
    .bind(claimId, now, recoveryExpiresAt, now, token, now).run();
  return findActiveTryonGrant(token);
}
