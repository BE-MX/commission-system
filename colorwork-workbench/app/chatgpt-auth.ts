import { env } from 'cloudflare:workers';
import { headers } from 'next/headers';
import { LOCAL_ACCOUNTS, type LocalAccountDefinition } from '@/lib/local-accounts';

export { LOCAL_ACCOUNTS } from '@/lib/local-accounts';

export type WorkbenchView = 'library' | 'inventory' | 'master';
export const ALL_VIEWS: readonly WorkbenchView[] = ['library', 'inventory', 'master'];

export type ChatGPTUser = LocalAccountDefinition & {
  userId: string;
  fullName: string;
  /** 方舟页面权限下发的可见视图；旧本地会话按角色推导（admin=全部，member=下载+修改）。 */
  views: WorkbenchView[];
};

const SESSION_COOKIE = 'inventory_workbench_session';
const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;
/** 方舟 SSO 会话 12 小时：权限撤销后最迟次日失效，不再依赖 30 天长会话。 */
const ARK_SESSION_MAX_AGE_SECONDS = 60 * 60 * 12;

function normalizeUsername(value: string) {
  return value.trim().toLowerCase();
}

export function localAccountForUsername(value: unknown) {
  if (typeof value !== 'string') return null;
  const normalized = normalizeUsername(value);
  return LOCAL_ACCOUNTS.find((account) => normalizeUsername(account.username) === normalized) ?? null;
}

export async function ensureLocalAccounts() {
  const now = new Date().toISOString();
  await env.DB.batch(LOCAL_ACCOUNTS.map((account) => env.DB.prepare(`
    INSERT OR IGNORE INTO allowed_accounts
      (email, display_name, role, enabled, added_by, created_at, updated_at)
    VALUES (?, ?, ?, 1, 'local-auth', ?, ?)
  `).bind(account.email, account.displayName, account.role, now, now)));
}

function cookieValue(cookieHeader: string | null, name: string) {
  if (!cookieHeader) return null;
  for (const part of cookieHeader.split(';')) {
    const [key, ...value] = part.trim().split('=');
    if (key === name) return value.join('=') || null;
  }
  return null;
}

export function sessionTokenFromCookieHeader(cookieHeader: string | null) {
  return cookieValue(cookieHeader, SESSION_COOKIE);
}

function viewsFromJson(viewsJson: string | null, role: 'admin' | 'member'): WorkbenchView[] {
  if (viewsJson) {
    try {
      const parsed = JSON.parse(viewsJson) as unknown;
      if (Array.isArray(parsed)) {
        const views = parsed.filter((view): view is WorkbenchView =>
          typeof view === 'string' && (ALL_VIEWS as readonly string[]).includes(view));
        if (views.length) return views;
      }
    } catch {
      // 非法 JSON 回落角色推导
    }
  }
  return role === 'admin' ? [...ALL_VIEWS] : ['library', 'inventory'];
}

export async function getChatGPTUser(): Promise<ChatGPTUser | null> {
  const token = sessionTokenFromCookieHeader((await headers()).get('cookie'));
  if (!token) return null;
  const now = new Date().toISOString();
  const row = await env.DB.prepare(`
    SELECT s.username, s.views_json AS viewsJson, a.email, a.display_name AS displayName, a.role
    FROM local_sessions s
    JOIN allowed_accounts a ON a.email = CASE LOWER(s.username)
      WHEN 'design-ljc' THEN 'design-ljc@inventory.local'
      WHEN 'sales' THEN 'sales@inventory.local'
      ELSE LOWER(s.username)
    END
    WHERE s.token = ? AND s.expires_at > ? AND a.enabled = 1
  `).bind(token, now).first<{
    username: string;
    viewsJson: string | null;
    email: string;
    displayName: string;
    role: 'admin' | 'member';
  }>();
  if (!row) return null;
  const account = localAccountForUsername(row.username);
  return {
    username: account?.username ?? row.username,
    email: row.email,
    displayName: row.displayName,
    role: row.role,
    userId: account ? `local:${normalizeUsername(row.username)}` : `ark:${row.username}`,
    fullName: row.displayName,
    views: viewsFromJson(row.viewsJson, row.role),
  };
}

function randomToken() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
}

async function insertSession(username: string, views: WorkbenchView[] | null, maxAgeSeconds = SESSION_MAX_AGE_SECONDS) {
  const now = new Date();
  const expiresAt = new Date(now.getTime() + maxAgeSeconds * 1000).toISOString();
  const token = randomToken();
  await env.DB.batch([
    env.DB.prepare('DELETE FROM local_sessions WHERE expires_at <= ?').bind(now.toISOString()),
    env.DB.prepare('INSERT INTO local_sessions (token, username, created_at, expires_at, views_json) VALUES (?, ?, ?, ?, ?)')
      .bind(token, username, now.toISOString(), expiresAt, views ? JSON.stringify(views) : null),
  ]);
  return { token, expiresAt, maxAgeSeconds };
}

export async function createLocalSession(username: string) {
  const account = localAccountForUsername(username);
  if (!account) return null;
  await ensureLocalAccounts();
  const { token, expiresAt } = await insertSession(account.username, null);
  return { account, token, expiresAt };
}

export type ArkSsoClaims = {
  sub: string;
  username: string;
  name: string;
  views: WorkbenchView[];
};

/**
 * 方舟 SSO 落座：以方舟用户 id（claims.sub，稳定唯一）为站内账号键自动开通/刷新账号
 * （持有 master 视图即管理员），再建立带视图清单的站内会话。账号管理已收归方舟角色权限，
 * 站内不再维护账号。用户名只作展示，不参与键值，避免中文名/改名导致撞号或孤儿账号。
 */
export async function createArkSession(claims: ArkSsoClaims) {
  const subKey = normalizeUsername(claims.sub || claims.username || 'user')
    .replace(/[^a-z0-9._-]/g, '') || 'user';
  const email = `ark-${subKey}@ark.local`;
  const displayName = (claims.name || claims.username || '方舟用户').slice(0, 40);
  const role: 'admin' | 'member' = claims.views.includes('master') ? 'admin' : 'member';
  const now = new Date().toISOString();
  await env.DB.prepare(`
    INSERT INTO allowed_accounts (email, display_name, role, enabled, added_by, created_at, updated_at)
    VALUES (?, ?, ?, 1, 'ark-sso', ?, ?)
    ON CONFLICT(email) DO UPDATE SET
      display_name = excluded.display_name,
      role = excluded.role,
      enabled = 1,
      updated_at = excluded.updated_at
  `).bind(email, displayName, role, now, now).run();
  const { token, expiresAt } = await insertSession(email, claims.views, ARK_SESSION_MAX_AGE_SECONDS);
  return { token, expiresAt, email, displayName, role, maxAgeSeconds: ARK_SESSION_MAX_AGE_SECONDS };
}

export async function destroyLocalSession(token: string | null) {
  if (token) await env.DB.prepare('DELETE FROM local_sessions WHERE token = ?').bind(token).run();
}

export function sessionCookie(token: string, secure: boolean, maxAgeSeconds = SESSION_MAX_AGE_SECONDS) {
  // SameSite=Lax：与主站同 eTLD+1（子域名）时 iframe 内请求属 same-site，Cookie 正常携带
  return `${SESSION_COOKIE}=${token}; Path=/; Max-Age=${maxAgeSeconds}; HttpOnly; SameSite=Lax${secure ? '; Secure' : ''}`;
}

export function clearedSessionCookie(secure: boolean) {
  return `${SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax${secure ? '; Secure' : ''}`;
}

export function localSignOutPath(returnTo = '/') {
  const safeReturnTo = returnTo.startsWith('/') && !returnTo.startsWith('//') ? returnTo : '/';
  return `/api/auth/logout?return_to=${encodeURIComponent(safeReturnTo)}`;
}
