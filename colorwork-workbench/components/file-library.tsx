'use client';

import { useEffect, useRef, useState } from 'react';
import { Check, Download, FileType2, X } from 'lucide-react';
import { InventoryBoard } from '@/components/inventory-board';
import { workbenchFetch, workbenchUrl } from '@/lib/workbench-url';
import type { CatalogData, TemplateSummary } from '@/lib/catalog';

type LibraryUser = { role: 'admin' | 'member'; displayName: string };
type Preview = { kind: 'original' | 'live'; template: TemplateSummary };

function StockImageDialog({ preview, catalog, user, onClose }: {
  preview: Preview; catalog: CatalogData; user: LibraryUser; onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  const item = preview.template;
  return (
    <dialog ref={dialogRef} className="stock-image-dialog" aria-label={preview.kind === 'live' ? '实时库存图预览' : '原始库存图预览'}
      onCancel={onClose} onClose={onClose} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <button type="button" className="stock-dialog-close" onClick={onClose} aria-label="关闭预览" autoFocus><X size={22} /></button>
      {preview.kind === 'live'
        ? <InventoryBoard catalog={catalog} user={user} previewOnly initialTemplateId={item.id} />
        : <figure><img src={workbenchUrl(`/api/templates/${item.id}/download/jpg?inline=1`)} alt={`${item.productName}-${item.radio}`} /><figcaption>{item.productName}-{item.radio}</figcaption></figure>}
    </dialog>
  );
}

export function FileLibrary({ user, catalog }: { user: LibraryUser; catalog: CatalogData }) {
  const { templates } = catalog;
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const allSelected = templates.length > 0 && templates.every((item) => selected.includes(item.id));
  const toggle = (id: string) => setSelected((items) => items.includes(id) ? items.filter((item) => item !== id) : [...items, id]);

  async function batchDownload() {
    if (!selected.length || downloading) return;
    setDownloading(true);
    setError('');
    try {
      const response = await workbenchFetch('/api/downloads/zip', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ items: selected.map((id) => ({ kind: 'template', id })) }),
      });
      if (!response.ok) throw new Error('批量下载失败，请重试。');
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = '原始库存图.zip';
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '批量下载失败，请重试。');
    } finally {
      setDownloading(false);
    }
  }

  return (
    <section className="library-view">
      <header className="view-heading"><div><span>DOWNLOAD CENTER</span><h1>库存图直接下载</h1><p>下载原始库存图，或预览并下载当前库存与补货状态生成的实时库存图。</p></div></header>
      <div className="library-section-heading"><div><span>STOCK JPG</span><h2>库存图JPG</h2></div><p>按产品与 Radio 选择，实时图使用当前共享库存状态</p></div>
      <div className="download-toolbar section-toolbar">
        <label><input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? [] : templates.map((item) => item.id))} disabled={!templates.length} />全选原始库存图</label>
        <button type="button" onClick={() => void batchDownload()} disabled={!selected.length || downloading}><Download size={15} />{downloading ? '正在打包…' : `批量下载原始库存图${selected.length ? `（${selected.length}）` : ''}`}</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="source-template-list">
        {templates.map((item) => (
          <article key={item.id}>
            <label className="select-box"><input type="checkbox" aria-label={`选择 ${item.productName}-${item.radio}`} checked={selected.includes(item.id)} onChange={() => toggle(item.id)} /><span>{selected.includes(item.id) ? <Check size={14} /> : null}</span></label>
            <button type="button" className="thumbnail-button" onClick={() => setPreview({ kind: 'original', template: item })}><img src={workbenchUrl(`/api/templates/${item.id}/download/jpg?inline=1`)} alt={`${item.productName}-${item.radio}`} loading="lazy" /></button>
            <div><strong>{item.productName}-{item.radio}.jpg</strong><span>原始库存图 / 实时库存图</span></div>
            <div className="stock-download-actions">
              <a href={workbenchUrl(`/api/templates/${item.id}/download/jpg`)}><Download size={15} />下载原始库存图JPG</a>
              <button type="button" onClick={() => setPreview({ kind: 'live', template: item })}><Download size={15} />下载实时库存图JPG</button>
            </div>
          </article>
        ))}
      </div>
      {user.role === 'admin' && <p className="source-note"><FileType2 size={15} />PSD 请在“原始库存图文件”中管理和下载。</p>}
      {preview && <StockImageDialog key={`${preview.kind}:${preview.template.id}`} preview={preview} catalog={catalog} user={user} onClose={() => setPreview(null)} />}
    </section>
  );
}
