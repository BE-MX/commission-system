import { WorkbenchApp } from '@/components/workbench-app';
import { localSignOutPath } from '@/app/chatgpt-auth';
import { getAuthorizedUser } from '@/lib/server/auth';
import { CATALOG } from '@/lib/server/catalog';
import { runtimeAssetsReady } from '@/lib/server/runtime-assets';
import { ALL_VIEWS, type WorkbenchView } from '@/app/chatgpt-auth';

export const dynamic = 'force-dynamic';

function sanitizeView(value: unknown, allowed: WorkbenchView[]): WorkbenchView {
  return typeof value === 'string' && (allowed as string[]).includes(value)
    ? (value as WorkbenchView)
    : allowed[0] ?? 'library';
}

export default async function Home({ searchParams }: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = searchParams ? await searchParams : {};
  const identity = await getAuthorizedUser();
  if (!identity) {
    return (
      <main className="auth-shell">
        <section className="auth-card">
          <div className="auth-mark">SC</div>
          <span>STOCK COLOR WORKBENCH</span>
          <h1>库存色块图调整台</h1>
          <p>请从方舟平台「库存色块图」菜单进入；需要开通页面权限请联系管理员。</p>
        </section>
      </main>
    );
  }

  const assetsReady = await runtimeAssetsReady();
  if (!assetsReady && identity.role !== 'admin') {
    return (
      <main className="auth-shell">
        <section className="auth-card denied-card">
          <div className="auth-mark">SC</div>
          <span>SETUP IN PROGRESS</span>
          <h1>工作台正在完成首次设置</h1>
          <p>请稍后再进入。加程完成素材导入后，你就可以正常生成和下载文件。</p>
          <a className="auth-action secondary" href={localSignOutPath('/')}>清除会话并重新进入</a>
        </section>
      </main>
    );
  }

  const views = identity.views.length ? identity.views : [...ALL_VIEWS];
  return (
    <WorkbenchApp
      user={identity}
      catalog={CATALOG}
      runtimeReady={assetsReady}
      views={views}
      initialView={sanitizeView(params?.view, views)}
    />
  );
}
