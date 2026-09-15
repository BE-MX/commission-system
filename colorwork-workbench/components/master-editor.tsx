'use client';

import { workbenchFetch, workbenchUrl } from '@/lib/workbench-url';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, ArrowDown, ArrowUp, CheckCircle2, Flame, History,
  RefreshCw, RotateCcw, Save, Search, ShieldCheck, Trash2,
} from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { SourceVersionManager } from '@/components/source-version-manager';
import {
  activeMasterSelection, colorForId, productNames, radiosFor, selectionFromMaster,
  templateById, templateFor, type CatalogData, type Selection, type SelectionEntry,
} from '@/lib/catalog';
import {
  INVENTORY_SELECTABLE_STATUSES, STATUS_LABELS, specKey, type InventoryStatus, type MasterVersion,
  type TemplateState,
} from '@/lib/inventory';
import { paintPoster } from '@/lib/poster';

type VersionWithSelection = MasterVersion & { selection?: Selection };
type PreviewDefinition = Pick<TemplateState, 'template' | 'colors' | 'availableLengths' | 'sourceVersion'>;

async function responseJson<T>(response: Response): Promise<T> {
  const data = await response.json() as T & { error?: string };
  if (!response.ok) {
    const error = new Error(data.error || '操作失败。') as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return data;
}

function comparable(selection: Selection) {
  return JSON.stringify(activeMasterSelection(selection).map((entry, index) => ({
    entryId: entry.entryId,
    lengths: entry.lengths,
    hot: entry.hot,
    section: entry.section,
    order: index,
  })));
}

export function MasterEditor({ catalog }: { catalog: CatalogData }) {
  const { colors: catalogColors, templates } = catalog;
  const products = useMemo(() => productNames(templates), [templates]);
  const [templateId, setTemplateId] = useState(templates[0].id);
  const [state, setState] = useState<TemplateState | null>(null);
  const [draft, setDraft] = useState<Selection>(() => selectionFromMaster(catalogColors, templates[0], []));
  const [versions, setVersions] = useState<MasterVersion[]>([]);
  const [restoreTarget, setRestoreTarget] = useState<VersionWithSelection | null>(null);
  const [initialStatuses, setInitialStatuses] = useState<Record<string, InventoryStatus | ''>>({});
  const [query, setQuery] = useState('');
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [conflict, setConflict] = useState(false);
  const [previewDefinition, setPreviewDefinition] = useState<PreviewDefinition | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderRevision = useRef(0);
  const staticItem = useMemo(() => templateById(templates, templateId), [templates, templateId]);
  const item = previewDefinition?.template ?? state?.template ?? staticItem;
  const colors = previewDefinition?.colors ?? state?.colors ?? catalogColors;
  const availableLengths = previewDefinition?.availableLengths ?? state?.availableLengths ?? [16, 18, 20, 22, 24];

  const load = useCallback(async (id = templateId) => {
    setLoading(true);
    setError('');
    setNotice('');
    setConflict(false);
    try {
      const [current, history] = await Promise.all([
        responseJson<TemplateState>(await workbenchFetch(`/api/master/${id}/current`, { cache: 'no-store' })),
        responseJson<{ versions: MasterVersion[] }>(await workbenchFetch(`/api/master/${id}/versions`, { cache: 'no-store' })),
      ]);
      setState(current);
      setDraft(selectionFromMaster(current.colors, current.template, current.selection));
      setVersions(history.versions ?? []);
      setPreviewDefinition(null);
      setInitialStatuses({});
      setRestoreTarget(null);
      setNote('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '标准母版读取失败。');
    } finally {
      setLoading(false);
    }
  }, [templateId]);

  useEffect(() => { void load(templateId); }, [load, templateId]);

  const activeDraft = useMemo(() => activeMasterSelection(draft), [draft]);
  const baseKeys = useMemo(() => new Set((state?.specs ?? []).map((spec) => specKey(spec.entryId, spec.length))), [state?.specs]);
  const addedKeys = useMemo(() => activeDraft.flatMap((entry) => entry.lengths
    .map((length) => specKey(entry.entryId, length))
    .filter((key) => !baseKeys.has(key))), [activeDraft, baseKeys]);
  const unresolved = addedKeys.filter((key) => !initialStatuses[key]);
  const dirty = Boolean(state && comparable(draft) !== comparable(state.selection));
  const rows = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return [...draft]
      .filter((entry) => {
        const color = colorForId(colors, item, entry.colorId);
        const section = item.sections.find((value) => value.key === entry.section)?.label || '';
        return !keyword || color?.code.toLowerCase().includes(keyword) || section.toLowerCase().includes(keyword);
      })
      .sort((a, b) => Number(!a.lengths.length) - Number(!b.lengths.length) || a.order - b.order || a.entryId.localeCompare(b.entryId));
  }, [colors, draft, item, query]);

  useEffect(() => {
    const target = canvasRef.current;
    if (!target || !activeDraft.length) { setReady(false); return; }
    const revision = ++renderRevision.current;
    setReady(false);
    void paintPoster(colors, item, activeDraft, {}).then((poster) => {
      if (revision !== renderRevision.current) return;
      target.width = poster.width;
      target.height = poster.height;
      const context = target.getContext('2d');
      if (!context) throw new Error('当前浏览器无法显示母版预览。');
      context.clearRect(0, 0, target.width, target.height);
      context.drawImage(poster, 0, 0);
      setReady(true);
    }).catch((reason: Error) => {
      if (revision === renderRevision.current) setError(reason.message);
    });
  }, [activeDraft, colors, item]);

  function chooseTemplate(nextId: string) {
    setTemplateId(nextId);
    setState(null);
    setPreviewDefinition(null);
    setDraft(selectionFromMaster(catalogColors, templateById(templates, nextId), []));
  }

  function changeEntry(entryId: string, updater: (entry: SelectionEntry) => SelectionEntry) {
    setDraft((current) => current.map((entry) => entry.entryId === entryId ? updater(entry) : entry));
    setRestoreTarget(null);
    setNotice('');
  }

  function toggleLength(entry: SelectionEntry, length: number, enabled: boolean) {
    changeEntry(entry.entryId, (current) => ({
      ...current,
      lengths: enabled
        ? [...new Set([...current.lengths, length])].sort((a, b) => a - b)
        : current.lengths.filter((value) => value !== length),
      hot: enabled || current.lengths.length > 1 ? current.hot : false,
    }));
    const key = specKey(entry.entryId, length);
    if (!enabled) setInitialStatuses((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function removeEntry(entry: SelectionEntry) {
    changeEntry(entry.entryId, (current) => ({ ...current, lengths: [], hot: false }));
    setInitialStatuses((current) => {
      const next = { ...current };
      for (const length of entry.lengths) delete next[specKey(entry.entryId, length)];
      return next;
    });
  }

  function moveEntry(entry: SelectionEntry, direction: -1 | 1) {
    const active = activeMasterSelection(draft);
    const index = active.findIndex((candidate) => candidate.entryId === entry.entryId);
    const other = active[index + direction];
    if (!other) return;
    setDraft((current) => current.map((candidate) => {
      if (candidate.entryId === entry.entryId) return { ...candidate, order: other.order };
      if (candidate.entryId === other.entryId) return { ...candidate, order: entry.order };
      return candidate;
    }));
    setRestoreTarget(null);
  }

  function discardChanges() {
    if (!state) return;
    setPreviewDefinition(null);
    setDraft(selectionFromMaster(state.colors, state.template, state.selection));
    setInitialStatuses({});
    setRestoreTarget(null);
    setNote('');
    setNotice('');
    setError('');
  }

  function initialStatusPayload() {
    return addedKeys.map((key) => {
      const separator = key.lastIndexOf('\u001f');
      return {
        entryId: key.slice(0, separator),
        length: Number(key.slice(separator + 1)),
        status: initialStatuses[key],
      };
    });
  }

  async function saveMaster() {
    if (!state || !dirty || unresolved.length) return;
    setSaving(true);
    setError('');
    setNotice('');
    setConflict(false);
    try {
      await responseJson(await workbenchFetch(`/api/master/${item.id}/versions`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          expectedRevision: state.masterRevision,
          note: note.trim(),
          selection: draft.map((entry) => {
            const activeIndex = activeDraft.findIndex((candidate) => candidate.entryId === entry.entryId);
            return { ...entry, order: activeIndex >= 0 ? activeIndex : entry.order };
          }),
          initialStatuses: initialStatusPayload(),
        }),
      }));
      await load(item.id);
      setNotice('新的标准母版已生效；业务端下次打开或刷新会调用这一版本。');
    } catch (reason) {
      const requestError = reason as Error & { status?: number };
      if (requestError.status === 409) setConflict(true);
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function loadHistoricalVersion(version: MasterVersion) {
    setError('');
    setNotice('');
    try {
      const data = await responseJson<PreviewDefinition & {
        version: VersionWithSelection;
        selection?: Selection;
        inventory?: TemplateState['specs'];
      }>(
        await workbenchFetch(`/api/master/${item.id}/versions/${version.id}`, { cache: 'no-store' }),
      );
      const historical = data.version;
      const selection = data.selection ?? historical.selection;
      if (!selection) throw new Error('历史版本没有可恢复的母版内容。');
      setPreviewDefinition({
        template: data.template,
        colors: data.colors,
        availableLengths: data.availableLengths,
        sourceVersion: data.sourceVersion,
      });
      setDraft(selectionFromMaster(data.colors, data.template, selection));
      setRestoreTarget({ ...historical, selection });
      const currentKeys = new Set((state?.specs ?? []).map((spec) => specKey(spec.entryId, spec.length)));
      setInitialStatuses(Object.fromEntries(
        (data.inventory ?? [])
          .filter((spec) => !currentKeys.has(specKey(spec.entryId, spec.length)))
          .map((spec) => [specKey(spec.entryId, spec.length), spec.status]),
      ));
      setNote(`恢复自 v${version.number}`);
      setNotice(`已载入 v${version.number} 作为恢复预览，尚未改变当前母版。`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '历史版本读取失败。');
    }
  }

  async function restoreVersion() {
    if (!state || !restoreTarget || unresolved.length) return;
    setSaving(true);
    setError('');
    setConflict(false);
    try {
      await responseJson(await workbenchFetch(`/api/master/${item.id}/restore`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          expectedRevision: state.masterRevision,
          versionId: restoreTarget.id,
          note: note.trim(),
          initialStatuses: initialStatusPayload(),
        }),
      }));
      await load(item.id);
      setNotice(`历史 v${restoreTarget.number} 已恢复为一个新的当前版本。`);
    } catch (reason) {
      const requestError = reason as Error & { status?: number };
      if (requestError.status === 409) setConflict(true);
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="master-workspace">
      <section className="master-controls">
        <header className="panel-intro"><span>ADMIN MASTER</span><h1>标准母版管理</h1><p>这里的颜色、尺寸、顺序、分区和 Hot 设置决定业务端当前可用的规格。每次保存都会创建新版本。</p></header>
        <div className="template-fields">
          <div className="select-field"><span>产品名</span><Select value={item.productName} onValueChange={(value) => value && chooseTemplate(templateFor(templates, value, radiosFor(templates, value)[0]).id)}><SelectTrigger className="field-trigger"><SelectValue /></SelectTrigger><SelectContent>{products.map((product) => <SelectItem key={product} value={product}>{product}</SelectItem>)}</SelectContent></Select></div>
          <div className="select-field"><span>Radio</span><Select value={item.radio} onValueChange={(value) => value && chooseTemplate(templateFor(templates, item.productName, value).id)}><SelectTrigger className="field-trigger"><SelectValue /></SelectTrigger><SelectContent>{radiosFor(templates, item.productName).map((radio) => <SelectItem key={radio} value={radio}>{radio}</SelectItem>)}</SelectContent></Select></div>
        </div>
        {state && <div className="revision-strip"><span><ShieldCheck size={15} />源 S{previewDefinition?.sourceVersion.number ?? state.sourceVersion.number ?? '—'} · {previewDefinition ? '历史预览' : `当前标准母版 v${state.version.number}`}</span><span>母版修订 {state.masterRevision}</span><span>{state.version.createdBy.displayName} · {new Date(state.version.createdAt).toLocaleString('zh-CN')}</span></div>}
        {state && !previewDefinition && <SourceVersionManager state={state} disabled={saving || dirty} onActivated={() => load(state.templateId)} />}

        <div className="master-toolbar"><div className="search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 38 色、历史色或分区" /></div><span>当前 {activeDraft.length} 个颜色 · {activeDraft.reduce((sum, entry) => sum + entry.lengths.length, 0)} 个规格</span></div>
        {loading && <p className="empty-state">正在读取标准母版…</p>}
        {!loading && error && <div className="state-error" role="alert"><AlertTriangle size={17} /><span>{error}</span>{conflict && <button onClick={() => void load(item.id)}><RefreshCw size={15} />刷新当前版本</button>}</div>}
        {!loading && state && (
          <div className="master-color-list">
            {rows.map((entry) => {
              const color = colorForId(colors, item, entry.colorId);
              if (!color) return null;
              const activeIndex = activeDraft.findIndex((candidate) => candidate.entryId === entry.entryId);
              return (
                <article className={entry.lengths.length ? 'master-color-row active' : 'master-color-row'} key={entry.entryId}>
                  <img src={workbenchUrl(color.image)} alt={`${color.code} 色块`} />
                  <div className="master-color-title"><strong>{color.code}</strong>{color.legacy && <span>历史色</span>}</div>
                  <div className="master-lengths">
                    {availableLengths.map((length) => {
                      const enabled = entry.lengths.includes(length);
                      const key = specKey(entry.entryId, length);
                      const isAdded = enabled && !baseKeys.has(key);
                      return (
                        <div className={isAdded ? 'master-length new' : 'master-length'} key={length}>
                          <label><Checkbox checked={enabled} onCheckedChange={(checked) => toggleLength(entry, length, Boolean(checked))} />{length}″</label>
                          {isAdded && <select value={initialStatuses[key] || ''} onChange={(event) => setInitialStatuses((current) => ({ ...current, [key]: event.target.value as InventoryStatus }))} aria-label={`${color.code} ${length} 英寸初始库存状态`}><option value="">选择初始状态</option>{INVENTORY_SELECTABLE_STATUSES.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}</select>}
                        </div>
                      );
                    })}
                  </div>
                  <div className="master-entry-options">
                    {item.sections.length > 0 && <select value={entry.section || item.sections.at(-1)!.key} disabled={!entry.lengths.length} onChange={(event) => changeEntry(entry.entryId, (current) => ({ ...current, section: event.target.value }))}>{item.sections.map((section) => <option key={section.key} value={section.key}>{section.label}</option>)}</select>}
                    <button className={entry.hot ? 'hot on' : 'hot'} disabled={!entry.lengths.length} onClick={() => changeEntry(entry.entryId, (current) => ({ ...current, hot: !current.hot }))}><Flame size={14} />Hot</button>
                    <button disabled={activeIndex <= 0} onClick={() => moveEntry(entry, -1)} title="前移"><ArrowUp size={14} /></button>
                    <button disabled={activeIndex < 0 || activeIndex >= activeDraft.length - 1} onClick={() => moveEntry(entry, 1)} title="后移"><ArrowDown size={14} /></button>
                    <button disabled={!entry.lengths.length} onClick={() => removeEntry(entry)} title="从当前母版移除"><Trash2 size={14} /></button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
        <div className="master-save-panel">
          <label htmlFor="master-version-note">版本说明（选填）<Input id="master-version-note" value={note} maxLength={180} onChange={(event) => setNote(event.target.value)} placeholder="例如：增加某个颜色的 22 英寸" /></label>
          {addedKeys.length > 0 && <p className={unresolved.length ? 'new-spec-warning' : 'new-spec-ready'}>{unresolved.length ? `还有 ${unresolved.length} 个新增规格需要选择初始库存状态。` : `已明确设置 ${addedKeys.length} 个新增规格的初始状态。`}</p>}
          <div><button className="secondary-action" onClick={discardChanges} disabled={(!dirty && !restoreTarget) || saving}><RotateCcw size={16} />放弃本次修改</button>{restoreTarget ? <button className="primary-action" onClick={() => void restoreVersion()} disabled={saving || unresolved.length > 0}><History size={17} />{saving ? '正在恢复…' : `恢复 v${restoreTarget.number} 为新版本`}</button> : <button className="primary-action" onClick={() => void saveMaster()} disabled={!dirty || saving || unresolved.length > 0}><Save size={17} />{saving ? '正在保存…' : '保存为当前标准母版'}</button>}</div>
          {notice && <output className="success">{notice}</output>}
        </div>
      </section>

      <aside className="master-side">
        <section className="master-preview-card"><header><div><span>MASTER PREVIEW</span><h2>母版预览</h2></div><span>{ready ? '预览已更新' : '正在排版'}</span></header><div className="canvas-frame" style={{ aspectRatio: `${item.width} / ${item.height}` }}><canvas ref={canvasRef} width={item.width} height={item.height} /></div><p>预览只显示母版内容，不带业务缺货状态。保存后请到“共享库存状态”查看最终图片。</p></section>
        <section className="version-card"><header><History size={18} /><div><span>VERSION HISTORY</span><h2>母版版本记录</h2></div></header>{versions.map((version) => <article key={version.id} className={state?.version.id === version.id ? 'current' : ''}><div><strong>v{version.number}</strong><span>源 S{version.sourceVersionNumber ?? '—'} · {version.action === 'restore' ? '恢复版本' : version.action === 'source_update' ? '源文件更新' : version.action === 'initial' ? '源文件初始版' : '管理员修改'}</span></div><p>{version.note || '未填写版本说明'}</p><small>{version.createdBy.displayName} · {new Date(version.createdAt).toLocaleString('zh-CN')}</small>{state?.version.id !== version.id && <button onClick={() => void loadHistoricalVersion(version)}>载入并预览恢复</button>}{state?.version.id === version.id && <span className="current-badge"><CheckCircle2 size={13} />当前使用</span>}</article>)}</section>
      </aside>
    </div>
  );
}
