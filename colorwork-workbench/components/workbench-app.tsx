'use client';

import { useCallback, useState } from 'react';
import { Users } from 'lucide-react';
import { FileLibrary } from '@/components/file-library';
import { InventoryBoard } from '@/components/inventory-board';
import { MasterEditor } from '@/components/master-editor';
import { TemplateImporter } from '@/components/template-importer';
import type { CatalogData } from '@/lib/catalog';

type User = { id: string; email: string; displayName: string; role: 'admin' | 'member' };
type View = 'inventory' | 'master' | 'library';

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

  // 页面导航与账号信息由方舟主站提供，工作台仅呈现当前业务视图。
  return (
    <main className="app-shell">
      {view === 'inventory' && assetsReady && views.includes('inventory') && <InventoryBoard catalog={catalog} user={user} />}
      {view === 'master' && views.includes('master') && (
        <div className="settings-view">
          {assetsReady && <MasterEditor catalog={catalog} />}
          <TemplateImporter catalog={catalog} runtimeReady={assetsReady} onRuntimeReady={handleRuntimeReady} />
        </div>
      )}
      {view === 'library' && assetsReady && views.includes('library') && <FileLibrary user={user} catalog={catalog} />}
      {!assetsReady && view !== 'master' && (
        <section className="setup-required"><Users size={28} /><h1>请先完成首次素材导入</h1><p>导入完成后，23 套母版和共享库存功能会自动开放。</p>{views.includes('master') && <button onClick={() => setView('master')}>前往原始库存图文件</button>}</section>
      )}
    </main>
  );
}
