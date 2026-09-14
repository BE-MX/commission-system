'use client';

import { useCallback, useEffect, useState } from 'react';
import { Check, Download, FileType2, FolderOpen, RefreshCw, Trash2, X } from 'lucide-react';
import type { TemplateSummary } from '@/lib/catalog';

type Artifact = {
  id: string;
  name: string;
  templateId: string;
  ownerName: string;
  createdAt: string;
  jpgSize: number;
  psdSize: number;
  masterVersion?: number;
  inventoryRevision?: number;
  sourceVersion?: number;
};

function fileSize(value: number) {
  if (!value) return '—';
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function FileLibrary({ userRole, templates }: { userRole: 'admin' | 'member'; templates: TemplateSummary[] }) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [preview, setPreview] = useState<{ src: string; name: string } | null>(null);
  const templateKey = (id: string) => `template:${id}`;
  const artifactKey = (id: string) => `artifact:${id}`;

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/artifacts?scope=shared', { cache: 'no-store' });
      const data = await response.json() as { artifacts?: Artifact[]; error?: string };
      if (!response.ok) throw new Error(data.error || '历史成品读取失败。');
      setArtifacts(data.artifacts ?? []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '历史成品读取失败。');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const archiveArtifact = async (id: string) => {
    if (!window.confirm('确认从当前下载列表移除这张业务图片吗？历史文件仍会保留。')) return;
    const response = await fetch(`/api/artifacts/${id}`, { method: 'DELETE' });
    if (!response.ok) {
      const data = await response.json().catch(() => ({})) as { error?: string };
      setError(data.error || '移除失败，请刷新后重试。');
      return;
    }
    setArtifacts((items) => items.filter((item) => item.id !== id));
  };

  const toggle = (key: string) => setSelected((items) => items.includes(key) ? items.filter((item) => item !== key) : [...items, key]);
  const batchDownload = async (keys: string[], filename: string) => {
    if (!keys.length) return;
    const items = keys.map((key) => { const [kind, id] = key.split(':'); return { kind: kind === 'template' ? 'template' : 'artifact', id }; });
    const response = await fetch('/api/downloads/zip', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ items }) });
    if (!response.ok) { setError('批量下载失败，请刷新后重试。'); return; }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url);
  };
  const businessKeys = artifacts.map((item) => artifactKey(item.id));
  const originalKeys = templates.map((item) => templateKey(item.id));
  const businessSelected = businessKeys.length > 0 && businessKeys.every((key) => selected.includes(key));
  const originalSelected = originalKeys.length > 0 && originalKeys.every((key) => selected.includes(key));
  const selectGroup = (keys: string[], isSelected: boolean) => setSelected((items) => isSelected ? items.filter((item) => !keys.includes(item)) : [...new Set([...items, ...keys])]);

  return (
    <section className="library-view">
      <header className="view-heading">
        <div><span>DOWNLOAD CENTER</span><h1>库存图直接下载</h1><p>管理员和业务账号看到同一套最新业务库存图；业务修改库存状态后，下载图会自动更新。</p></div>
        <button onClick={() => void load()} disabled={loading}><RefreshCw size={16} />刷新</button>
      </header>

      <div className="library-section-heading"><div><span>BUSINESS OUTPUT</span><h2>业务修改图</h2></div><p>每个产品／Radio 只显示最新版本</p></div>
      <div className="download-toolbar section-toolbar"><label><input type="checkbox" checked={businessSelected} onChange={() => selectGroup(businessKeys, businessSelected)} disabled={!businessKeys.length} />全选业务修改图</label><button type="button" onClick={() => void batchDownload(selected.filter((key) => key.startsWith('artifact:')), '业务修改图.zip')} disabled={!selected.some((key) => key.startsWith('artifact:'))}><Download size={15} />批量下载业务修改图{selected.filter((key) => key.startsWith('artifact:')).length ? `（${selected.filter((key) => key.startsWith('artifact:')).length}）` : ''}</button></div>
      {loading && <p className="empty-state">正在读取历史成品…</p>}
      {!loading && error && <p className="error" role="alert">{error}</p>}
      {!loading && !error && !artifacts.length && <p className="empty-state"><FolderOpen size={20} />还没有业务修改图片，当前请下载下方原始 JPG。</p>}
      <div className="artifact-list">
        {artifacts.map((item) => (
          <article className="artifact-row" key={item.id}>
            <label className="select-box"><input type="checkbox" checked={selected.includes(artifactKey(item.id))} onChange={() => toggle(artifactKey(item.id))} /><span>{selected.includes(artifactKey(item.id)) ? <Check size={14} /> : null}</span></label>
            <button type="button" className="thumbnail-button" onClick={() => setPreview({ src: `/api/artifacts/${item.id}/download/jpg?inline=1`, name: `${item.name}.jpg` })}><img src={`/api/artifacts/${item.id}/download/jpg?inline=1`} alt={item.name} loading="lazy" /></button>
            <div><h2>{item.name}.jpg</h2><p>{item.ownerName} · {new Date(item.createdAt).toLocaleDateString('zh-CN')}</p></div>
            <span>JPG {fileSize(item.jpgSize)}{item.masterVersion ? <><br />源 S{item.sourceVersion ?? '—'} · 母版 v{item.masterVersion} · 状态 r{item.inventoryRevision}</> : null}</span>
            <div className="artifact-actions"><a href={`/api/artifacts/${item.id}/download/jpg`}><Download size={15} />下载 JPG</a><button type="button" onClick={() => void archiveArtifact(item.id)}><Trash2 size={15} />移除</button></div>
          </article>
        ))}
      </div>

      <div className="library-section-heading generated-heading"><div><span>ORIGINAL JPG</span><h2>原始库存图 JPG</h2></div><p>当前母版的原始参考图，所有账号均可下载</p></div>
      <div className="download-toolbar section-toolbar"><label><input type="checkbox" checked={originalSelected} onChange={() => selectGroup(originalKeys, originalSelected)} disabled={!originalKeys.length} />全选原始库存图</label><button type="button" onClick={() => void batchDownload(selected.filter((key) => key.startsWith('template:')), '原始库存图.zip')} disabled={!selected.some((key) => key.startsWith('template:'))}><Download size={15} />批量下载原始库存图{selected.filter((key) => key.startsWith('template:')).length ? `（${selected.filter((key) => key.startsWith('template:')).length}）` : ''}</button></div>
      <div className="source-template-list">
        {templates.map((item) => (
          <article key={item.id}><label className="select-box"><input type="checkbox" checked={selected.includes(templateKey(item.id))} onChange={() => toggle(templateKey(item.id))} /><span>{selected.includes(templateKey(item.id)) ? <Check size={14} /> : null}</span></label><button type="button" className="thumbnail-button" onClick={() => setPreview({ src: `/api/templates/${item.id}/download/jpg?inline=1`, name: `${item.productName}-${item.radio}.jpg` })}><img src={`/api/templates/${item.id}/download/jpg?inline=1`} alt={`${item.productName}-${item.radio}`} loading="lazy" /></button><div><strong>{item.productName}-{item.radio}.jpg</strong><span>原始库存图</span></div><a href={`/api/templates/${item.id}/download/jpg`}><Download size={15} />下载 JPG</a></article>
        ))}
      </div>
      {userRole === 'admin' && <p className="source-note"><FileType2 size={15} />PSD 请在“原始库存图文件”中管理和下载。</p>}
      {preview && <dialog open className="image-lightbox" aria-label={preview.name}><button type="button" className="lightbox-close" onClick={() => setPreview(null)} aria-label="关闭"><X size={22} /></button><figure><img src={preview.src} alt={preview.name} /><figcaption>{preview.name}</figcaption></figure></dialog>}
    </section>
  );
}
