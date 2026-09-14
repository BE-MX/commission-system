'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, Download, FileImage, RefreshCw, Save,
  Search, ShieldCheck,
} from 'lucide-react';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  activeMasterSelection, colorForId, productNames, radiosFor, templateById, templateFor,
  type CatalogData, type SelectionEntry,
} from '@/lib/catalog';
import {
  INVENTORY_SELECTABLE_STATUSES, STATUS_LABELS, inventoryMapsEqual, specMap, statusMapForSpecs,
  type InventoryStatus, type InventoryStatusMap, type TemplateState,
} from '@/lib/inventory';
import { paintPoster } from '@/lib/poster';

type InventoryBoardProps = {
  catalog: CatalogData;
  user: { role: 'admin' | 'member'; displayName: string };
};

async function responseJson<T>(response: Response): Promise<T> {
  const data = await response.json() as T & { error?: string };
  if (!response.ok) {
    const error = new Error(data.error || '操作失败。') as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return data;
}

function canvasBlob(canvas: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('JPG 生成失败。')), 'image/jpeg', .96);
  });
}

function saveLocal(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

function safeFileName(value: string) {
  return value.replace(/[\\/:*?"<>|]/g, '-').trim() || '库存提示图';
}

function currentStatusBySpec(state: TemplateState) {
  return Object.fromEntries(state.specs.map((spec) => [spec.specId, spec.status])) as Record<string, InventoryStatus>;
}

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '尚未修改';
}

export function InventoryBoard({ catalog, user }: InventoryBoardProps) {
  const { colors: catalogColors, templates } = catalog;
  const products = useMemo(() => productNames(templates), [templates]);
  const [templateId, setTemplateId] = useState(templates[0].id);
  const [state, setState] = useState<TemplateState | null>(null);
  const [draft, setDraft] = useState<Record<string, InventoryStatus>>({});
  const [query, setQuery] = useState('');
  const [bulkLength, setBulkLength] = useState(18);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [conflict, setConflict] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderRevision = useRef(0);
  const loadSeq = useRef(0);
  const dirtyRef = useRef(false);
  const staticItem = useMemo(() => templateById(templates, templateId), [templates, templateId]);
  const item = state?.template ?? staticItem;
  const colors = state?.colors ?? catalogColors;
  const availableLengths = useMemo(
    () => state?.availableLengths?.length ? state.availableLengths : [16, 18, 20, 22, 24],
    [state?.availableLengths],
  );

  const load = useCallback(async (id = templateId, silent = false) => {
    const seq = ++loadSeq.current;
    if (!silent) {
      setLoading(true);
      setError('');
      setNotice('');
      setConflict(false);
    }
    try {
      const next = await responseJson<TemplateState>(await fetch(`/api/inventory/${id}`, { cache: 'no-store' }));
      // 过期响应丢弃：用户已切换模板/Radio；静默轮询响应落地时若已有未保存修改也不覆盖草稿
      if (seq !== loadSeq.current) return;
      if (silent && dirtyRef.current) return;
      setState(next);
      setDraft(currentStatusBySpec(next));
    } catch (reason) {
      // 静默轮询失败不打断当前页面；主动刷新才提示错误
      if (seq !== loadSeq.current || silent) return;
      setError(reason instanceof Error ? reason.message : '库存状态读取失败。');
    } finally {
      if (!silent && seq === loadSeq.current) setLoading(false);
    }
  }, [templateId]);

  useEffect(() => { void load(templateId); }, [load, templateId]);

  useEffect(() => {
    if (!availableLengths.includes(bulkLength)) setBulkLength(availableLengths[0]);
  }, [availableLengths, bulkLength]);

  useEffect(() => {
    if (!state) return;
    const checkVersion = async () => {
      try {
        const latest = await responseJson<TemplateState>(await fetch(`/api/inventory/${state.templateId}`, { cache: 'no-store' }));
        if (latest.sourceVersion.id !== state.sourceVersion.id) {
          setConflict(true);
          setError(`源文件已从 S${state.sourceVersion.number ?? '旧'} 更新为 S${latest.sourceVersion.number ?? '新'}。本页未保存修改不会自动覆盖新版。`);
        }
      } catch {
        // 保存和导出接口仍会再次做强制版本校验。
      }
    };
    window.addEventListener('focus', checkVersion);
    return () => window.removeEventListener('focus', checkVersion);
  }, [state]);

  const masterSelection = useMemo(
    () => activeMasterSelection(state?.selection ?? []),
    [state?.selection],
  );
  const specsByKey = useMemo(() => specMap(state?.specs ?? []), [state?.specs]);
  const statusMap = useMemo<InventoryStatusMap>(() => {
    if (!state) return {};
    const map: InventoryStatusMap = {};
    for (const spec of state.specs) {
      map[spec.entryId] ??= {};
      map[spec.entryId][spec.length] = draft[spec.specId] ?? spec.status;
    }
    return map;
  }, [draft, state]);
  const persistedMap = useMemo(() => statusMapForSpecs(state?.specs ?? []), [state?.specs]);
  const dirty = Boolean(state && !inventoryMapsEqual(statusMap, persistedMap, masterSelection));
  useEffect(() => { dirtyRef.current = dirty; }, [dirty]);

  // okki 实时库存自动生效：每 30 秒静默同步一次（快照接口已按 enable_count 覆盖状态）；
  // 有未保存修改或页面不可见时跳过，不打断编辑。
  useEffect(() => {
    if (!state) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'visible' || dirty) return;
      void load(state.templateId, true);
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [state, dirty, load]);

  const visibleEntries = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return masterSelection.filter((entry) => {
      const color = colorForId(colors, item, entry.colorId);
      const section = item.sections.find((value) => value.key === entry.section)?.label || '';
      return !keyword || color?.code.toLowerCase().includes(keyword) || section.toLowerCase().includes(keyword);
    });
  }, [colors, item, masterSelection, query]);

  useEffect(() => {
    if (!state) return;
    const target = canvasRef.current;
    if (!target) return;
    const revision = ++renderRevision.current;
    setReady(false);
    void paintPoster(colors, item, masterSelection, statusMap).then((poster) => {
      if (revision !== renderRevision.current) return;
      target.width = poster.width;
      target.height = poster.height;
      const context = target.getContext('2d');
      if (!context) throw new Error('当前浏览器无法显示预览。');
      context.clearRect(0, 0, target.width, target.height);
      context.drawImage(poster, 0, 0);
      setReady(true);
    }).catch((reason: Error) => {
      if (revision === renderRevision.current) setError(reason.message);
    });
  }, [colors, item, masterSelection, state, statusMap]);

  function chooseTemplate(nextId: string) {
    setTemplateId(nextId);
    setState(null);
    setDraft({});
    setError('');
    setNotice('');
  }

  function chooseProduct(product: string) {
    chooseTemplate(templateFor(templates, product, radiosFor(templates, product)[0]).id);
  }

  function chooseRadio(radio: string) {
    chooseTemplate(templateFor(templates, item.productName, radio).id);
  }

  function updateStatus(specId: string, status: InventoryStatus) {
    setDraft((current) => ({ ...current, [specId]: status }));
    setNotice('');
  }

  function updateEntry(entry: SelectionEntry, status: InventoryStatus) {
    setDraft((current) => {
      const next = { ...current };
      for (const length of entry.lengths) {
        const spec = specsByKey.get(`${entry.entryId}\u001f${length}`);
        if (spec) next[spec.specId] = status;
      }
      return next;
    });
    setNotice('');
  }

  function updateWholeLength(status: InventoryStatus) {
    if (!state) return;
    setDraft((current) => {
      const next = { ...current };
      for (const spec of state.specs) if (spec.length === bulkLength) next[spec.specId] = status;
      return next;
    });
    setNotice('');
  }

  function restoreAll() {
    if (!state) return;
    setDraft(Object.fromEntries(state.specs.map((spec) => [spec.specId, 'normal'])) as Record<string, InventoryStatus>);
    setNotice('');
  }

  async function saveStatuses() {
    if (!state || !dirty) return;
    setSaving(true);
    setError('');
    setNotice('');
    setConflict(false);
    const updates = state.specs
      .filter((spec) => (draft[spec.specId] ?? spec.status) !== spec.status)
      .map((spec) => ({ specId: spec.specId, status: draft[spec.specId] ?? spec.status }));
    try {
      const next = await responseJson<TemplateState>(await fetch(`/api/inventory/${item.id}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          expectedMasterRevision: state.masterRevision,
          expectedInventoryRevision: state.inventoryRevision,
          expectedSourceVersionId: state.sourceVersion.id,
          updates,
        }),
      }));
      setState(next);
      setDraft(currentStatusBySpec(next));
      setNotice('共享库存状态已保存，其他账号刷新后会看到此版本。');
    } catch (reason) {
      const requestError = reason as Error & { status?: number };
      if (requestError.status === 409) setConflict(true);
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function validateCurrent(snapshot: TemplateState, snapshotTemplateId: string) {
    if (dirty) throw new Error('请先保存库存状态，再导出图片。');
    await responseJson(await fetch(`/api/inventory/${snapshotTemplateId}/validate`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        expectedMasterRevision: snapshot.masterRevision,
        expectedInventoryRevision: snapshot.inventoryRevision,
        expectedSourceVersionId: snapshot.sourceVersion.id,
        specIds: snapshot.specs.map((spec) => spec.specId),
      }),
    }));
  }

  async function exportJpg(saveHistory: boolean) {
    if (!ready || !state) return;
    const exportState = state;
    const exportItem = item;
    setExporting(true);
    setError('');
    setNotice('');
    setConflict(false);
    try {
      await validateCurrent(exportState, exportItem.id);
      const exportPoster = await paintPoster(
        colors,
        exportItem,
        activeMasterSelection(exportState.selection),
        statusMapForSpecs(exportState.specs),
      );
      const jpg = await canvasBlob(exportPoster);
      await validateCurrent(exportState, exportItem.id);
      const dateParts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
      const dateStamp = `${dateParts.find((part) => part.type === 'year')?.value}${dateParts.find((part) => part.type === 'month')?.value}${dateParts.find((part) => part.type === 'day')?.value}`;
      const name = safeFileName(`${exportItem.productName}-${exportItem.radio}-${dateStamp}`);
      if (saveHistory) {
        const created = await responseJson<{
          artifact: { id: string };
          upload: { jpg: string; finalize: string };
        }>(await fetch('/api/artifacts', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            name,
            templateId: exportItem.id,
            expectedMasterRevision: exportState.masterRevision,
            expectedInventoryRevision: exportState.inventoryRevision,
            expectedSourceVersionId: exportState.sourceVersion.id,
          }),
        }));
        await responseJson(await fetch(created.upload.jpg, { method: 'PUT', body: jpg }));
        await responseJson(await fetch(created.upload.finalize, {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ jpgOnly: true }),
        }));
        saveLocal(jpg, `${name}.jpg`);
        setNotice('JPG 已保存到历史成品并开始下载。');
      } else {
        saveLocal(jpg, `${name}.jpg`);
        setNotice('最新 JPG 已开始下载。');
      }
    } catch (reason) {
      const requestError = reason as Error & { status?: number };
      if (requestError.status === 409) setConflict(true);
      setError(requestError.message);
    } finally {
      setExporting(false);
    }
  }

  const counts = useMemo(() => {
    const result: Record<InventoryStatus, number> = { normal: 0, out_of_stock: 0, restocking: 0 };
    if (state) for (const spec of state.specs) result[draft[spec.specId] ?? spec.status] += 1;
    return result;
  }, [draft, state]);

  return (
    <div className="inventory-workspace">
      <section className="inventory-controls" aria-label="共享库存状态">
        <header className="panel-intro">
          <span>SHARED INVENTORY STATUS</span>
          <h1>维护当前库存与补货状态</h1>
          <p>{user.role === 'admin' ? '管理员也可以在这里执行与业务相同的库存操作。' : '业务只修改标准母版中已经存在的规格。'} 所有账号共享同一份状态，保存后再导出最新图片。库存状态每 30 秒与小满实时库存自动同步：有可用库存为「到货正常」，无库存自动转「正在补货」。</p>
        </header>

        <div className="template-fields">
          <div className="select-field"><span>产品名</span><Select value={item.productName} disabled={loading || saving || exporting} onValueChange={(value) => value && chooseProduct(value)}><SelectTrigger className="field-trigger"><SelectValue /></SelectTrigger><SelectContent>{products.map((product) => <SelectItem key={product} value={product}>{product}</SelectItem>)}</SelectContent></Select></div>
          <div className="select-field"><span>Radio</span><Select value={item.radio} disabled={loading || saving || exporting} onValueChange={(value) => value && chooseRadio(value)}><SelectTrigger className="field-trigger"><SelectValue /></SelectTrigger><SelectContent>{radiosFor(templates, item.productName).map((radio) => <SelectItem key={radio} value={radio}>{radio}</SelectItem>)}</SelectContent></Select></div>
        </div>

        {state && (
          <div className="revision-strip">
            <span><ShieldCheck size={15} />源 S{state.sourceVersion.number ?? '—'} · 标准母版 v{state.version.number}</span>
            <span>库存状态 r{state.inventoryRevision}</span>
            <span>最后修改：{state.inventoryUpdatedBy?.displayName || state.version.createdBy.displayName} · {formatTime(state.inventoryUpdatedAt || state.version.createdAt)}</span>
          </div>
        )}

        <div className="inventory-summary">
          <span className="normal">正常 {counts.normal}</span>
          <span className="restocking">正在补货 {counts.restocking}</span>
        </div>

        <div className="inventory-toolbar">
          <div className="search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索色号或分区" aria-label="搜索色号或分区" /></div>
          <div className="bulk-size">
            <select value={bulkLength} disabled={saving || exporting || conflict} onChange={(event) => setBulkLength(Number(event.target.value))} aria-label="批量尺寸">{availableLengths.map((length) => <option key={length} value={length}>{length}″</option>)}</select>
            <button disabled={saving || exporting || conflict} onClick={() => updateWholeLength('restocking')}>整尺寸补货中</button>
            <button disabled={saving || exporting || conflict} onClick={() => updateWholeLength('normal')}>整尺寸恢复</button>
          </div>
          <button className="restore-all" disabled={saving || exporting || conflict} onClick={restoreAll}>全部恢复到货</button>
        </div>

        {loading && <p className="empty-state">正在读取当前标准母版与共享库存状态…</p>}
        {!loading && error && <div className="state-error" role="alert"><AlertTriangle size={17} /><span>{error}</span>{conflict && <button onClick={() => void load(item.id)}><RefreshCw size={15} />放弃本页修改并载入新版</button>}</div>}
        {!loading && state && (
          <div className="inventory-color-list">
            {visibleEntries.map((entry) => {
              const color = colorForId(colors, item, entry.colorId);
              if (!color) return null;
              const section = item.sections.find((value) => value.key === entry.section)?.label;
              return (
                <article className="inventory-color-row" key={entry.entryId}>
                  <img src={color.image} alt={`${color.code} 色块`} />
                  <div className="inventory-color-title"><strong>{color.code}</strong>{section && <span>{section}</span>}{color.legacy && <span>历史色</span>}</div>
                  <div className="spec-statuses">
                    {entry.lengths.map((length) => {
                      const spec = specsByKey.get(`${entry.entryId}\u001f${length}`);
                      if (!spec) return null;
                      const value = draft[spec.specId] ?? spec.status;
                      return (
                        <label key={spec.specId} className={`spec-status ${value}`}>
                          <span>{length}″</span>
                          <select value={value} disabled={saving || exporting || conflict} onChange={(event) => updateStatus(spec.specId, event.target.value as InventoryStatus)} aria-label={`${color.code} ${length} 英寸状态`}>
                            {INVENTORY_SELECTABLE_STATUSES.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}
                          </select>
                        </label>
                      );
                    })}
                  </div>
                  <div className="whole-color-actions">
                    <button disabled={saving || exporting || conflict} onClick={() => updateEntry(entry, 'restocking')}>整色补货中</button>
                    <button disabled={saving || exporting || conflict} onClick={() => updateEntry(entry, 'normal')}>整色恢复</button>
                  </div>
                </article>
              );
            })}
          </div>
        )}

        <div className="inventory-save-bar">
          <div>{dirty ? <><AlertTriangle size={16} />有尚未保存的共享状态修改</> : <><CheckCircle2 size={16} />当前页面与已保存状态一致</>}</div>
          <button onClick={() => void saveStatuses()} disabled={!dirty || saving || conflict}><Save size={17} />{saving ? '正在保存…' : '保存共享状态'}</button>
        </div>
        {notice && <output className="success inventory-notice">{notice}</output>}
      </section>

      <aside className="inventory-preview" aria-label="库存提示图预览">
        <div className="preview-heading"><div><span>LIVE PREVIEW</span><h2>{item.productName}</h2><p>{item.radio}</p></div><span className={ready ? 'render-ready' : ''}>{ready ? dirty ? '未保存预览' : '最新预览' : '正在更新'}</span></div>
        <div className="canvas-frame" style={{ aspectRatio: `${item.width} / ${item.height}` }}><canvas ref={canvasRef} width={item.width} height={item.height} aria-label="库存提示图预览" /></div>
        <div className="static-image-note"><FileImage size={17} /><p><strong>下载的是静态 JPG</strong><span>恢复到货后，需要重新导出并发送给客户。</span></p></div>
        <button className="primary-action" onClick={() => void exportJpg(true)} disabled={!state || !ready || dirty || exporting || conflict}><Download size={18} />{exporting ? '正在核对并生成…' : '保存成品并下载 JPG'}</button>
        <button className="secondary-action" onClick={() => void exportJpg(false)} disabled={!state || !ready || dirty || exporting || conflict}><Download size={16} />只下载最新 JPG</button>
        <button className="secondary-action" onClick={() => void load(item.id)} disabled={loading || dirty || saving || exporting}><RefreshCw size={16} />刷新服务器最新状态</button>
      </aside>
    </div>
  );
}
