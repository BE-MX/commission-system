import {
  clearedSessionCookie,
  destroyLocalSession,
  sessionTokenFromCookieHeader,
} from '@/app/chatgpt-auth';

export async function GET(request: Request) {
  await destroyLocalSession(sessionTokenFromCookieHeader(request.headers.get('cookie')));
  const url = new URL(request.url);
  const returnTo = url.searchParams.get('return_to');
  const location = returnTo?.startsWith('/') && !returnTo.startsWith('//') ? returnTo : '/';
  const secure = url.protocol === 'https:';
  return new Response(null, {
    status: 303,
    headers: { location, 'set-cookie': clearedSessionCookie(secure), 'cache-control': 'no-store' },
  });
}

export { GET as POST };
