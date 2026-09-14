import { env } from 'cloudflare:workers';
import {
  ALL_VIEWS,
  createArkSession,
  sessionCookie,
  type ArkSsoClaims,
  type WorkbenchView,
} from '@/app/chatgpt-auth';

const noStoreHeaders = { 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' };

function base64UrlDecode(value: string) {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function base64UrlEncode(bytes: ArrayBuffer) {
  const view = new Uint8Array(bytes);
  let binary = '';
  for (const byte of view) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function constantTimeEqual(left: string, right: string) {
  if (left.length !== right.length) return false;
  let diff = 0;
  for (let index = 0; index < left.length; index += 1) {
    diff |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return diff === 0;
}

/** 校验方舟签发的 HS256 SSO 令牌（aud=colorwork、exp 必填），通过则返回 claims。 */
async function verifyArkSsoToken(token: string, secret: string): Promise<ArkSsoClaims | null> {
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  const [head, body, signature] = parts;
  try {
    const key = await crypto.subtle.importKey(
      'raw',
      new TextEncoder().encode(secret),
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['sign'],
    );
    const expected = base64UrlEncode(
      await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`${head}.${body}`)),
    );
    if (!constantTimeEqual(expected, signature)) return null;

    const payload = JSON.parse(new TextDecoder().decode(base64UrlDecode(body))) as Record<string, unknown>;
    if (payload.aud !== 'colorwork') return null;
    if (typeof payload.exp !== 'number' || payload.exp * 1000 <= Date.now()) return null;
    const views = Array.isArray(payload.views)
      ? payload.views.filter((view): view is WorkbenchView =>
          typeof view === 'string' && (ALL_VIEWS as readonly string[]).includes(view))
      : [];
    if (!views.length) return null;
    return {
      sub: typeof payload.sub === 'string' ? payload.sub : '',
      username: typeof payload.username === 'string' ? payload.username : '',
      name: typeof payload.name === 'string' ? payload.name : '',
      views,
    };
  } catch {
    return null;
  }
}

/**
 * 方舟 SSO 入口：方舟后端按页面权限签发短命令牌 → 这里换站内会话 Cookie 并跳到目标视图。
 * 令牌 secret 与方舟后端 COLORWORK_SSO_SECRET 共享（本地经 .dev.vars 注入）。
 */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const token = url.searchParams.get('token') ?? '';
  const view = url.searchParams.get('view') ?? '';

  const secret = typeof env.ARK_SSO_SECRET === 'string' ? env.ARK_SSO_SECRET : '';
  const claims = secret && token ? await verifyArkSsoToken(token, secret) : null;
  if (!claims || !claims.views.includes(view as WorkbenchView)) {
    return Response.json({ error: '进入链接无效或已过期，请回到方舟平台重新进入。' }, {
      status: 401,
      headers: noStoreHeaders,
    });
  }

  const session = await createArkSession(claims);
  const secure = url.protocol === 'https:';
  return new Response(null, {
    status: 302,
    headers: {
      location: `/?view=${encodeURIComponent(view)}`,
      'set-cookie': sessionCookie(session.token, secure, session.maxAgeSeconds),
      ...noStoreHeaders,
    },
  });
}
