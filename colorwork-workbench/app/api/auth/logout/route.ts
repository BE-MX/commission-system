import { workbenchUrl } from '@/lib/workbench-url';
import {
  clearedSessionCookie,
  destroyLocalSession,
  sessionTokenFromCookieHeader,
} from '@/app/chatgpt-auth';

export async function GET(request: Request) {
  await destroyLocalSession(sessionTokenFromCookieHeader(request.headers.get('cookie')));
  const url = new URL(request.url);
  // Always return inside this module, never let a query redirect outside Ark.
  const location = workbenchUrl('/');
  const secure = url.protocol === 'https:' || request.headers.get('x-forwarded-proto') === 'https';
  return new Response(null, {
    status: 303,
    headers: { location, 'set-cookie': clearedSessionCookie(secure), 'cache-control': 'no-store' },
  });
}

export { GET as POST };
