import { env } from 'cloudflare:workers';
import { ensureLocalAccounts, getChatGPTUser, type WorkbenchView } from '@/app/chatgpt-auth';

export type AuthorizedUser = {
  id: string;
  email: string;
  displayName: string;
  role: 'admin' | 'member';
  /** 方舟页面权限下发的可见视图（library / inventory / master）。 */
  views: WorkbenchView[];
};

type AllowedAccountRow = {
  email: string;
  display_name: string;
  role: 'admin' | 'member';
  enabled: number;
  user_email: string | null;
  user_display_name: string | null;
  user_role: 'admin' | 'member' | null;
  last_seen_at: string | null;
};

const LAST_SEEN_WRITE_INTERVAL = 15 * 60 * 1000;

function normalizeEmail(email: string) {
  return email.trim().toLowerCase();
}

export async function getAuthorizedUser(): Promise<AuthorizedUser | null> {
  const identity = await getChatGPTUser();
  if (!identity) return null;

  // Local username sessions use synthetic emails so the existing account and
  // audit tables can continue to enforce the same server-side role checks.
  await ensureLocalAccounts();

  const email = normalizeEmail(identity.email);
  const now = new Date().toISOString();
  const countRow = await env.DB.prepare('SELECT COUNT(*) AS total FROM allowed_accounts').first<{ total: number }>();

  if (!countRow?.total) {
    const configuredAdmin = typeof env.BOOTSTRAP_ADMIN_EMAIL === 'string'
      ? normalizeEmail(env.BOOTSTRAP_ADMIN_EMAIL)
      : '';
    const bootstrapEmail = configuredAdmin || (process.env.NODE_ENV === 'development' ? email : '');
    if (!bootstrapEmail || email !== bootstrapEmail) return null;
    const bootstrapName = '加程';
    await env.DB.batch([
      env.DB.prepare(`
        INSERT OR IGNORE INTO allowed_accounts
          (email, display_name, role, enabled, added_by, created_at, updated_at)
        VALUES (?, ?, 'admin', 1, ?, ?, ?)
      `).bind(bootstrapEmail, bootstrapName, bootstrapEmail, now, now),
      env.DB.prepare(`
        INSERT OR IGNORE INTO users
          (id, email, display_name, role, last_seen_at, created_at)
        VALUES (?, ?, ?, 'admin', ?, ?)
      `).bind(identity.userId, bootstrapEmail, bootstrapName, now, now),
    ]);
  }

  const allowed = await env.DB.prepare(`
    SELECT a.email, a.display_name, a.role, a.enabled,
      u.email AS user_email, u.display_name AS user_display_name,
      u.role AS user_role, u.last_seen_at
    FROM allowed_accounts a
    LEFT JOIN users u ON u.id = ?
    WHERE a.email = ?
  `).bind(identity.userId, email).first<AllowedAccountRow>();

  if (!allowed || !allowed.enabled) return null;

  const displayName = allowed.display_name || identity.displayName;
  const lastSeen = allowed.last_seen_at ? Date.parse(allowed.last_seen_at) : 0;
  if (
    !lastSeen ||
    Date.now() - lastSeen >= LAST_SEEN_WRITE_INTERVAL ||
    allowed.user_email !== email ||
    allowed.user_display_name !== displayName ||
    allowed.user_role !== allowed.role
  ) {
    await env.DB.prepare(`
      INSERT INTO users (id, email, display_name, role, last_seen_at, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        email = excluded.email,
        display_name = excluded.display_name,
        role = excluded.role,
        last_seen_at = excluded.last_seen_at
    `).bind(identity.userId, email, displayName, allowed.role, now, now).run();
  }

  return {
    id: identity.userId,
    email,
    displayName,
    role: allowed.role,
    views: identity.views,
  };
}

export async function requireApiUser(): Promise<AuthorizedUser> {
  const user = await getAuthorizedUser();
  if (!user) throw new Error('UNAUTHORIZED');
  return user;
}

export async function requireAdmin(): Promise<AuthorizedUser> {
  const user = await requireApiUser();
  if (user.role !== 'admin') throw new Error('FORBIDDEN');
  return user;
}

/** 逐视图校验（方舟页面权限映射）：无该视图权限抛 VIEW_FORBIDDEN。 */
export async function requireView(view: WorkbenchView): Promise<AuthorizedUser> {
  const user = await requireApiUser();
  if (!user.views.includes(view)) throw new Error('VIEW_FORBIDDEN');
  return user;
}

export function authErrorResponse(error: unknown) {
  const headers = { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' };
  if (error instanceof Error && error.message === 'UNAUTHORIZED') {
    return Response.json({ error: '请从方舟平台进入本工作台。' }, { status: 401, headers });
  }
  if (error instanceof Error && error.message === 'VIEW_FORBIDDEN') {
    return Response.json({ error: '当前方舟账号没有这个页面的访问权限。' }, { status: 403, headers });
  }
  if (error instanceof Error && error.message === 'FORBIDDEN') {
    return Response.json({ error: '只有管理员可以执行此操作。' }, { status: 403, headers });
  }
  return Response.json({ error: '操作失败，请稍后重试。' }, { status: 500, headers });
}
