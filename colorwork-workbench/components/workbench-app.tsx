'use client';

import { useCallback, useState } from 'react';
import {
  Boxes, ChevronRight, FileImage, FolderOpen, Layers3, ShieldCheck, Users,
} from 'lucide-react';
import { FileLibrary } from '@/components/file-library';
import { InventoryBoard } from '@/components/inventory-board';
import { MasterEditor } from '@/components/master-editor';
import { TemplateImporter } from '@/components/template-importer';
import type { CatalogData } from '@/lib/catalog';

type User = { id: string; email: string; displayName: string; role: 'admin' | 'member' };
type View = 'inventory' | 'master' | 'library';

function initials(name: string) {
  const value = name.trim();
  if (!value) return 'U';
  if (value.split('').every((character) => character.charCodeAt(0) < 128)) {
    return value.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase();
  }
  return value.slice(-2);
}

export function WorkbenchApp({
  user,
  catalog,
  runtimeReady,
  views,
  initialView,
}: {
  user: User;
  catalog: CatalogData;
  runtimeReady: boolean;
  views: View[];
  initialView: View;
}) {
  const [assetsReady, setAssetsReady] = useState(runtimeReady);
  const [view, setView] = useState<View>(initialView);
  const handleRuntimeReady = useCallback(() => {
    setAssetsReady(true);
    setView(views.includes('inventory') ? 'inventory' : views[0]);
  }, [views]);

  // 账号与设置已收归方舟平台（页面权限 + SSO），站内只保留三个业务视图
  const navItems: Array<{ id: View; label: string; icon: typeof FileImage }> = [
    { id: 'library', label: '库存图直接下载', icon: FolderOpen },
    { id: 'inventory', label: '实时库存图修改', icon: Boxes },
    { id: 'master', label: '原始库存图文件', icon: Layers3 },
  ];
  const visibleNav = navItems.filter((item) => views.includes(item.id));
  const viewLabel = visibleNav.find((item) => item.id === view)?.label ?? visibleNav[0]?.label ?? '';

  return (
    <main className="app-shell">
      <header className="topbar">
        <button className="brand" onClick={() => assetsReady && views.includes('inventory') && setView('inventory')}>
          <span className="brand-mark"><Layers3 size={21} /></span>
          <span><strong>库存色块图调整台</strong><small>STOCK STATUS WORKBENCH</small></span>
        </button>
        <nav aria-label="主导航">
          {visibleNav.map(({ id, label, icon: Icon }) => (
            <button key={id} className={view === id ? 'nav-active' : ''} disabled={!assetsReady && id !== 'master'} onClick={() => setView(id)}><Icon size={17} />{label}</button>
          ))}
        </nav>
        <div className="account"><span>{user.displayName}</span><i>{initials(user.displayName)}</i></div>
      </header>

      <section className="context-bar">
        <div><span className="status-dot" />{user.role === 'admin' ? `${user.displayName} · 管理员` : `${user.displayName} · 业务账号`}</div>
        <ChevronRight size={14} />
        <span>{viewLabel}</span>
        <p><ShieldCheck size={15} />页面访问由方舟平台权限控制 · 母版与共享库存状态由后台校验</p>
      </section>

      {view === 'inventory' && assetsReady && views.includes('inventory') && <InventoryBoard catalog={catalog} user={user} />}
      {view === 'master' && views.includes('master') && (
        <div className="settings-view">
          {assetsReady && <MasterEditor catalog={catalog} />}
          <TemplateImporter catalog={catalog} runtimeReady={assetsReady} onRuntimeReady={handleRuntimeReady} />
        </div>
      )}
      {view === 'library' && assetsReady && views.includes('library') && <FileLibrary userRole={user.role} templates={catalog.templates} />}
      {!assetsReady && view !== 'master' && (
        <section className="setup-required"><Users size={28} /><h1>请先完成首次素材导入</h1><p>导入完成后，23 套母版和共享库存功能会自动开放。</p>{views.includes('master') && <button onClick={() => setView('master')}>前往原始库存图文件</button>}</section>
      )}
    </main>
  );
}
