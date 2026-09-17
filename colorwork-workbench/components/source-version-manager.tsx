'use client';

import { workbenchFetch, workbenchUrl } from '@/lib/workbench-url';

import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileSearch,
  RefreshCw,
  UploadCloud,
} from 'lucide-react';
import { activeMasterSelection, colorForId, type StockColor } from '@/lib/catalog';
import {
  INVENTORY_SELECTABLE_STATUSES,
  STATUS_LABELS,
  type InventoryStatus,
  type TemplateState,
} from '@/lib/inventory';
import { paintPoster } from '@/lib/poster';
import { computeSourceChanges } from '@/lib/source-diff';
import { sourceIssueKey, type SourceCard, type SourceVersionSummary } from '@/lib/source-versions';

type SourceList = {
  currentVersionId: string | null;
  versions: SourceVersionSummary[];
};

type MappingDraft = {
  mode: '' | 'existing' | 'new' | 'ignore';
  entryId: string;
  lengthText: string;
  section: string;
};

type ApiError = Error & { status?: number; code?: string; details?: unknown };

async function responseJson<T>(response: Response): Promise<T> {
  const data = await response.json() as T & { error?: string; code?: string; details?: unknown };
  if (!response.ok) {
    const error = new Error(data.error || '操作失败。') as ApiError;
    error.status = response.status;
    error.code = data.code;
    error.details = data.details;
    throw error;
  }
  return data;
}

function parseLengths(value: string) {
  const values = value.trim().split(/[，,、\s/]+/).map(Number);
  if (values.some((length) => !Number.isInteger(length) || length <= 0 || length > 100)) return [];
  return [...new Set(values)].sort((a, b) => a - b);
}

function mergeColors(current: StockColor[], next: StockColor[]) {
  const merged = new Map(current.map((color) => [color.id, color]));
  for (const color of next) merged.set(color.id, color);
  return [...merged.values()];
}

function statusText(status: SourceVersionSummary['status']) {
  return {
    uploading: '上传中',
    parsing: '解析中',
    needs_review: '需要确认',
    ready: '可启用',
    active: '当前使用',
    superseded: '历史版本',
    failed: '解析失败',
  }[status];
}

export function SourceVersionManager({
  state,
  disabled = false,
  onActivated,
}: {
  state: TemplateState;
  disabled?: boolean;
  onActivated: () => Promise<void> | void;
}) {
  const [psd, setPsd] = useState<File | null>(null);
  const [jpg, setJpg] = useState<File | null>(null);
  const [versions, setVersions] = useState<SourceVersionSummary[]>([]);
  const [candidate, setCandidate] = useState<SourceVersionSummary | null>(null);
  const [mappings, setMappings] = useState<Record<string, MappingDraft>>({});
  const [initialStatuses, setInitialStatuses] = useState<Record<string, InventoryStatus | ''>>({});
  const [acknowledged, setAcknowledged] = useState<Record<string, boolean>>({});
  const [running, setRunning] = useState(false);
  const [activating, setActivating] = useState(false);
  const [progress, setProgress] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [previewState, setPreviewState] = useState<'idle' | 'rendering' | 'ready' | 'failed'>('idle');
  const previewRef = useRef<HTMLCanvasElement>(null);
  const config = candidate?.config ?? null;
  const reviewConfig = useMemo(() => {
    if (!config) return null;
    const cards = config.template.initialCards.flatMap((card) => {
      const mapping = mappings[card.candidateId];
      if (mapping?.mode === 'ignore') return [];
      const lengths = parseLengths(mapping?.lengthText ?? '');
      const existing = mapping?.mode === 'existing' && mapping.entryId;
      return [{
        ...card,
        entryId: existing ? mapping.entryId : card.entryId,
        lengths: lengths.length ? lengths : card.lengths,
        section: mapping ? mapping.section || null : card.section,
        matchState: existing ? 'exact' as const : mapping?.mode === 'new' ? 'new' as const : card.matchState,
        matchedEntryId: existing ? mapping.entryId : mapping?.mode === 'new' ? null : card.matchedEntryId,
      }];
    }).map((card, order) => ({ ...card, order }));
    const availableLengths = config.availableLengths;
    const usedSections = new Set(cards.map((card) => card.section).filter(Boolean));
    const sections = config.template.sections.filter((section) => usedSections.has(section.key));
    const usedColorIds = new Set(cards.map((card) => card.colorId));
    return {
      ...config,
      colors: config.colors.filter((color) => usedColorIds.has(color.id)),
      availableLengths,
      template: { ...config.template, availableLengths, initialCards: cards, initialColorCount: cards.length, sections },
    };
  }, [config, mappings]);
  const reviewDiff = useMemo(
    () => reviewConfig
      ? computeSourceChanges(state.template, state.colors, state.selection, reviewConfig)
      : null,
    [reviewConfig, state.colors, state.selection, state.template],
  );

  const loadVersions = useCallback(async () => {
    try {
      const data = await responseJson<SourceList>(await workbenchFetch(`/api/template-sources/${state.templateId}`, { cache: 'no-store' }));
      setVersions(data.versions);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '源文件版本读取失败。');
    }
  }, [state.templateId]);

  useEffect(() => { void loadVersions(); }, [loadVersions]);
  useEffect(() => {
    setCandidate(null);
    setMappings({});
    setInitialStatuses({});
    setAcknowledged({});
    setPsd(null);
    setJpg(null);
    setError('');
    setNotice('');
    setProgress('');
    setPreviewState('idle');
  }, [state.templateId]);

  useEffect(() => {
    const config = candidate?.config;
    if (!config) return;
    const next: Record<string, MappingDraft> = {};
    for (const card of config.template.initialCards) {
      next[card.candidateId] = {
        mode: card.matchState === 'exact' ? 'existing' : '',
        entryId: card.matchedEntryId ?? '',
        lengthText: card.lengths.join(', '),
        section: card.section ?? '',
      };
    }
    setMappings(next);
    setInitialStatuses({});
    setAcknowledged({});
  }, [candidate]);

  useEffect(() => {
    const canvas = previewRef.current;
    if (!reviewConfig || !canvas) {
      setPreviewState('idle');
      return;
    }
    let cancelled = false;
    setPreviewState('rendering');
    const colors = mergeColors(state.colors, reviewConfig.colors);
    void paintPoster(colors, reviewConfig.template, activeMasterSelection(reviewConfig.template.initialCards), {})
      .then((poster) => {
        if (cancelled) return;
        canvas.width = poster.width;
        canvas.height = poster.height;
        const context = canvas.getContext('2d');
        if (!context) return;
        context.clearRect(0, 0, canvas.width, canvas.height);
        context.drawImage(poster, 0, 0);
        setPreviewState('ready');
      })
      .catch((reason: Error) => {
        if (cancelled) return;
        setPreviewState('failed');
        setError(`新版预览失败：${reason.message}`);
      });
    return () => { cancelled = true; };
  }, [reviewConfig, state.colors]);

  function chooseFile(kind: 'psd' | 'jpg', event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    if (kind === 'psd') setPsd(file);
    else setJpg(file);
    setError('');
    setNotice('');
  }

  async function uploadAndParse() {
    if (!psd || !jpg || running || disabled) return;
    if (!psd.name.toLowerCase().endsWith('.psd') || !jpg.name.toLowerCase().endsWith('.jpg')) {
      setError('请选择一份 PSD 和一份对应 JPG。');
      return;
    }
    let versionId = '';
    setRunning(true);
    setError('');
    setNotice('');
    setCandidate(null);
    try {
      setProgress('步骤 1／4：正在建立新版上传草稿…');
      const started = await responseJson<{
        sourceVersion: { id: string; number: number };
        uploadId: string;
        partSize: number;
      }>(await workbenchFetch(`/api/template-sources/${state.templateId}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ psdName: psd.name, jpgName: jpg.name, psdSize: psd.size, jpgSize: jpg.size }),
      }));
      versionId = started.sourceVersion.id;
      await responseJson(await workbenchFetch(`/api/template-sources/${state.templateId}/${versionId}/file/jpg`, {
        method: 'PUT',
        headers: { 'content-type': 'image/jpeg' },
        body: jpg,
      }));

      const parts: Array<{ partNumber: number; etag: string }> = [];
      const totalParts = Math.ceil(psd.size / started.partSize);
      for (let index = 0; index < totalParts; index += 1) {
        const partNumber = index + 1;
        setProgress(`步骤 1／4：正在上传 PSD ${partNumber}／${totalParts}…`);
        const chunk = psd.slice(index * started.partSize, Math.min(psd.size, partNumber * started.partSize));
        parts.push(await responseJson<{ partNumber: number; etag: string }>(await workbenchFetch(
          `/api/template-sources/${state.templateId}/${versionId}/psd-upload/${encodeURIComponent(started.uploadId)}/${partNumber}`,
          { method: 'PUT', headers: { 'content-type': 'application/octet-stream' }, body: chunk },
        )));
      }
      await responseJson(await workbenchFetch(
        `/api/template-sources/${state.templateId}/${versionId}/psd-upload/${encodeURIComponent(started.uploadId)}/complete`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ parts }),
        },
      ));

      setProgress('步骤 2／4：正在解析 PSD 图层、颜色、尺寸、分区与底图…');
      const { parseTemplateSource } = await import('@/lib/source-template-parser');
      const parsed = await parseTemplateSource({
        psdFile: psd,
        jpgFile: jpg,
        sourceVersionId: versionId,
        currentTemplate: state.template,
        currentColors: state.colors,
        currentSelection: state.selection,
      });
      for (const [index, asset] of parsed.assets.entries()) {
        setProgress(`步骤 2／4：正在保存解析素材 ${index + 1}／${parsed.assets.length}…`);
        const path = asset.name.split('/').map(encodeURIComponent).join('/');
        await responseJson(await workbenchFetch(`/api/template-sources/${state.templateId}/${versionId}/assets/${path}`, {
          method: 'PUT',
          headers: { 'content-type': 'image/png' },
          body: asset.blob,
        }));
      }
      const detail = await responseJson<SourceVersionSummary>(await workbenchFetch(
        `/api/template-sources/${state.templateId}/${versionId}/parse`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(parsed.config),
        },
      ));
      setCandidate(detail);
      setProgress('步骤 3／4：请查看新版预览、变化和无法可靠识别的内容。');
      setNotice(`源文件 S${detail.number} 已完成解析；确认启用前，业务继续使用 S${state.sourceVersion.number ?? '—'}。`);
      await loadVersions();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '新版源文件解析失败。';
      setError(`${message} 原有效版本保持不变。`);
      setProgress('解析失败：原有效版本仍可正常使用。');
      if (versionId) {
        await workbenchFetch(`/api/template-sources/${state.templateId}/${versionId}`, {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ failureReason: message }),
        }).catch(() => undefined);
        await loadVersions();
      }
    } finally {
      setRunning(false);
    }
  }

  const currentSpecKeys = useMemo(
    () => new Set(state.specs.map((spec) => `${spec.entryId}\u001f${spec.length}`)),
    [state.specs],
  );
  const requiredStatuses = useMemo(() => {
    if (!config) return [] as Array<{ candidateId: string; length: number; label: string }>;
    const result: Array<{ candidateId: string; length: number; label: string }> = [];
    for (const card of config.template.initialCards) {
      const mapping = mappings[card.candidateId];
      if (!mapping?.mode || mapping.mode === 'ignore') continue;
      const entryId = mapping.mode === 'existing' ? mapping.entryId : `new:${card.candidateId}`;
      const sectionLabel = config.template.sections.find((section) => section.key === mapping.section)?.label;
      for (const length of parseLengths(mapping.lengthText)) {
        if (!entryId || !currentSpecKeys.has(`${entryId}\u001f${length}`)) {
          result.push({ candidateId: card.candidateId, length, label: `${card.colorCode}${sectionLabel ? ` · ${sectionLabel}` : ''} · ${length}″` });
        }
      }
    }
    return result;
  }, [config, currentSpecKeys, mappings]);
  const blockingIssues = config?.parseIssues.filter((issue) => issue.blocking) ?? [];
  const mappingsReady = Boolean(config && config.template.initialCards.every((card) => {
    const mapping = mappings[card.candidateId];
    return mapping?.mode === 'ignore' || (mapping?.mode && parseLengths(mapping.lengthText).length > 0 &&
      parseLengths(mapping.lengthText).every((length) => config.availableLengths.includes(length)) &&
      (mapping.mode === 'new' || Boolean(mapping.entryId)) &&
      (!config.template.sections.length || Boolean(mapping.section)));
  }));
  const statusesReady = requiredStatuses.every((item) => initialStatuses[`${item.candidateId}\u001f${item.length}`]);
  const issuesReady = blockingIssues.every((issue) => acknowledged[sourceIssueKey(issue)]);

  function updateMapping(candidateId: string, patch: Partial<MappingDraft>) {
    setMappings((current) => ({
      ...current,
      [candidateId]: { ...current[candidateId], ...patch },
    }));
    setInitialStatuses({});
  }

  async function activate() {
    if (!candidate || !config || !mappingsReady || !statusesReady || !issuesReady || previewState !== 'ready' || activating || disabled) return;
    setActivating(true);
    setError('');
    setNotice('');
    try {
      const payloadMappings = config.template.initialCards.map((card) => {
        const mapping = mappings[card.candidateId];
        return {
          candidateId: card.candidateId,
          entryId: mapping.mode === 'existing' ? mapping.entryId : null,
          treatAsNew: mapping.mode === 'new',
          ignore: mapping.mode === 'ignore',
          lengths: mapping.mode === 'ignore' ? [] : parseLengths(mapping.lengthText),
          section: mapping.mode === 'ignore' ? null : mapping.section || null,
        };
      });
      await responseJson(await workbenchFetch(`/api/template-sources/${state.templateId}/${candidate.id}/activate`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          expectedMasterRevision: state.masterRevision,
          mappings: payloadMappings,
          acknowledgedIssues: blockingIssues.map(sourceIssueKey),
          initialStatuses: requiredStatuses.map((item) => ({
            candidateId: item.candidateId,
            length: item.length,
            status: initialStatuses[`${item.candidateId}\u001f${item.length}`],
          })),
          note: `启用源文件 S${candidate.number}：${candidate.psdName}`,
        }),
      }));
      setProgress('步骤 4／4：新版已启用。');
      setNotice(`源文件 S${candidate.number} 已启用；新打开页面与新导出将使用新版。`);
      setCandidate(null);
      await onActivated();
      await loadVersions();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '启用新版失败。');
    } finally {
      setActivating(false);
    }
  }

  function eligibleEntries(card: SourceCard) {
    return activeMasterSelection(state.selection).filter((entry) => entry.colorId === card.colorId);
  }

  async function continueReview(version: SourceVersionSummary) {
    setError('');
    try {
      const detail = await responseJson<SourceVersionSummary>(await workbenchFetch(
        `/api/template-sources/${state.templateId}/${version.id}`,
        { cache: 'no-store' },
      ));
      setCandidate(detail);
      setProgress('步骤 3／4：已重新载入候选，请继续查看变化并完成人工确认。');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '候选版本读取失败。');
    }
  }

  async function markStalledFailed(version: SourceVersionSummary) {
    setError('');
    try {
      await responseJson(await workbenchFetch(`/api/template-sources/${state.templateId}/${version.id}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ failureReason: '上传或解析未完成，管理员已结束本次候选。' }),
      }));
      await loadVersions();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '候选状态更新失败。');
    }
  }

  return (
    <section className="source-update-card" aria-label="更新现有模板源文件">
      <header>
        <div><span>SOURCE VERSION</span><h2>更新现有模板源文件</h2></div>
        <button onClick={() => void loadVersions()} disabled={running || activating}><RefreshCw size={15} />刷新版本</button>
      </header>
      <p>固定更新当前产品与 Radio，不新建重复模板。流程完成前，业务继续使用源 S{state.sourceVersion.number ?? '—'}。</p>

      <div className="source-steps" aria-label="更新流程">
        {['上传 PSD＋JPG', '解析与校验', '预览变化与人工确认', '确认启用'].map((label, index) => (
          <span key={label} className={candidate ? (index < 3 ? 'done' : 'current') : running ? (index === 1 ? 'current' : index === 0 ? 'done' : '') : index === 0 ? 'current' : ''}>{index + 1}<small>{label}</small></span>
        ))}
      </div>

      <div className="source-upload-grid">
        <label><strong>新版 PSD</strong><input type="file" accept=".psd,image/vnd.adobe.photoshop" onChange={(event) => chooseFile('psd', event)} disabled={running || activating || disabled} /><small>{psd?.name || '保留可解析图层结构'}</small></label>
        <label><strong>对应 JPG</strong><input type="file" accept=".jpg,image/jpeg" onChange={(event) => chooseFile('jpg', event)} disabled={running || activating || disabled} /><small>{jpg?.name || '必须与 PSD 画布尺寸一致'}</small></label>
        <button onClick={() => void uploadAndParse()} disabled={!psd || !jpg || running || activating || disabled}><UploadCloud size={17} />{running ? '正在上传并解析…' : '上传并解析新版'}</button>
      </div>
      {progress && <output className="source-progress"><FileSearch size={15} />{progress}</output>}
      {error && <div className="source-error" role="alert"><AlertTriangle size={16} />{error}</div>}
      {notice && <output className="source-notice"><CheckCircle2 size={16} />{notice}</output>}

      {candidate && config && (
        <div className="source-review">
          <div className="source-candidate-preview">
            <h3>新版母版实际预览</h3>
            <div className="canvas-frame" style={{ aspectRatio: `${config.template.width} / ${config.template.height}` }}>
              <canvas ref={previewRef} width={config.template.width} height={config.template.height} />
            </div>
            <p>{config.template.width}×{config.template.height} px · {reviewConfig?.template.initialCards.length ?? 0} 个颜色 · {reviewConfig?.template.initialCards.reduce((sum, card) => sum + card.lengths.length, 0) ?? 0} 个规格</p>
          </div>

          <div className="source-diff">
            <h3>主要变化</h3><p>移除项目仅影响新版画面与规格，历史库存状态、母版版本和导出记录仍保留。</p>
            <div className="diff-groups">
              <article><strong>新增 {reviewDiff?.added.length ?? 0}</strong><p>{reviewDiff?.added.map((item) => item.colorCode).join('、') || '无'}</p></article>
              <article><strong>移除 {reviewDiff?.removed.length ?? 0}</strong><p>{reviewDiff?.removed.map((item) => `${item.colorCode}（${item.lengths.join('／')}″）`).join('、') || '无'}</p></article>
              <article><strong>保持不变 {reviewDiff?.unchanged.length ?? 0}</strong><p>{reviewDiff?.unchanged.map((item) => item.colorCode).join('、') || '无'}</p></article>
              <article><strong>重新排列 {reviewDiff?.reordered.length ?? 0}</strong><p>{reviewDiff?.reordered.map((item) => item.colorCode).join('、') || '无'}</p></article>
              <article><strong>分区调整 {reviewDiff?.resectioned.length ?? 0}</strong><p>{reviewDiff?.resectioned.map((item) => item.colorCode).join('、') || '无'}</p></article>
            </div>
            {(reviewDiff?.resized.length ?? 0) > 0 && <div className="size-changes"><strong>尺寸变化</strong>{reviewDiff!.resized.map((item) => <p key={item.candidateId}>{item.colorCode}：{item.previousLengths.join('／')} → {item.nextLengths.join('／')}</p>)}</div>}
            <p className="asset-change">新版底图与相关素材已独立生成，像素差异需对照预览人工确认；{reviewDiff?.dimensionsChanged ? `画布由 ${reviewDiff.dimensionsChanged.before.width}×${reviewDiff.dimensionsChanged.before.height} 调整为 ${reviewDiff.dimensionsChanged.after.width}×${reviewDiff.dimensionsChanged.after.height}` : '画布尺寸保持不变'}。</p>
          </div>

          <div className="source-mapping">
            <h3>人工映射与尺寸确认</h3>
            <p>只允许按色号业务身份人工对应；系统不会按位置、排列序号或文件名迁移库存。尺寸仅限旧母版 S1：{config.availableLengths.join("／")}″；超出时请修改或排除该颜色。</p>
            {config.template.initialCards.map((card) => {
              const mapping = mappings[card.candidateId];
              const eligible = eligibleEntries(card);
              return (
                <article key={card.candidateId} className={card.matchState === 'unresolved' ? 'needs-review' : ''}>
                  <img src={workbenchUrl(colorForId(mergeColors(state.colors, config.colors), config.template, card.colorId)?.image)} alt="" />
                  <div><strong>{card.colorCode}</strong><small>{card.matchReason}</small></div>
                  <select value={mapping?.mode || ''} onChange={(event) => updateMapping(card.candidateId, { mode: event.target.value as MappingDraft['mode'], entryId: '' })}>
                    <option value="">请选择对应方式</option>
                    {eligible.length > 0 && <option value="existing">映射到现有颜色</option>}
                    <option value="new">确认为新增颜色</option>
                    <option value="ignore">从画面与业务中排除</option>
                  </select>
                  {mapping?.mode === 'existing' && <select value={mapping.entryId} onChange={(event) => updateMapping(card.candidateId, { entryId: event.target.value })}><option value="">选择现有条目</option>{eligible.map((entry) => <option key={entry.entryId} value={entry.entryId}>{card.colorCode} · {state.template.sections.find((section) => section.key === entry.section)?.label || '未分区'}</option>)}</select>}
                  {mapping?.mode !== 'ignore' && <label>尺寸（英寸，逗号分隔）<input value={mapping?.lengthText || ''} onChange={(event) => updateMapping(card.candidateId, { lengthText: event.target.value })} /></label>}
                  {mapping?.mode !== 'ignore' && (!parseLengths(mapping?.lengthText || '').length || parseLengths(mapping?.lengthText || '').some((length) => !config.availableLengths.includes(length))) && <small role="alert">尺寸不在 S1 允许集合内，请修改或排除该颜色。</small>}
                  {mapping?.mode !== 'ignore' && config.template.sections.length > 0 && <label>分区<select value={mapping?.section || ''} onChange={(event) => updateMapping(card.candidateId, { section: event.target.value })}><option value="">请选择分区</option>{config.template.sections.map((section) => <option key={section.key} value={section.key}>{section.label}</option>)}</select></label>}
                </article>
              );
            })}
          </div>

          {config.parseIssues.length > 0 && (
            <div className="source-issues">
              <h3>无法可靠识别／需要核对</h3>
              {config.parseIssues.map((issue) => (
                <label key={sourceIssueKey(issue)} className={issue.blocking ? 'blocking' : ''}>
                  {issue.blocking ? <input type="checkbox" checked={Boolean(acknowledged[sourceIssueKey(issue)])} onChange={(event) => setAcknowledged((current) => ({ ...current, [sourceIssueKey(issue)]: event.target.checked }))} /> : <CheckCircle2 size={15} />}
                  <span><strong>{issue.code}</strong>{issue.message}{issue.blocking && <small>我已对照 PSD／JPG，确认该项处理方式无误后才可勾选</small>}</span>
                </label>
              ))}
            </div>
          )}

          {requiredStatuses.length > 0 && (
            <div className="source-statuses">
              <h3>新增规格初始缺货状态</h3>
              <p>可准确对应且规格未改变的项目会自动保留原状态；以下新增规格必须由管理员核实。</p>
              {requiredStatuses.map((item) => {
                const key = `${item.candidateId}\u001f${item.length}`;
                return <label key={key}><span>{item.label}</span><select value={initialStatuses[key] || ''} onChange={(event) => setInitialStatuses((current) => ({ ...current, [key]: event.target.value as InventoryStatus }))}><option value="">选择初始状态</option>{INVENTORY_SELECTABLE_STATUSES.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}</select></label>;
              })}
            </div>
          )}

          <div className="source-activate-bar">
            <p>{!mappingsReady ? '还有颜色对应或尺寸待确认。' : !issuesReady ? '还有解析问题待逐项确认。' : !statusesReady ? '还有新增规格待设置初始状态。' : previewState === 'rendering' ? '正在验证新版实际预览。' : previewState === 'failed' ? '新版预览失败，不能启用。' : '已满足启用条件；原版本仍保留并可从母版历史回退。'}</p>
            <button onClick={() => void activate()} disabled={!mappingsReady || !issuesReady || !statusesReady || previewState !== 'ready' || activating || disabled}><CheckCircle2 size={17} />{activating ? '正在启用…' : `确认启用源 S${candidate.number}`}</button>
          </div>
        </div>
      )}

      <details className="source-history">
        <summary>源文件版本记录（{versions.length}）</summary>
        {versions.map((version) => (
          <article key={version.id} className={version.id === state.sourceVersion.id ? 'current' : ''}>
            <div><strong>源 S{version.number}</strong><span>{statusText(version.status)}</span></div>
            <p>{version.psdName}<br />{version.jpgName}</p>
            {version.failureReason && <small>{version.failureReason}</small>}
            <nav>
              {(version.status === 'ready' || version.status === 'needs_review') && <button onClick={() => void continueReview(version)}>继续审阅</button>}
              {(version.status === 'uploading' || version.status === 'parsing') && <button onClick={() => void markStalledFailed(version)}>结束未完成候选</button>}
              <a href={workbenchUrl(`/api/template-sources/${state.templateId}/${version.id}/download/psd`)}><Download size={13} />PSD</a>
              <a href={workbenchUrl(`/api/template-sources/${state.templateId}/${version.id}/download/jpg`)}><Download size={13} />JPG</a>
            </nav>
          </article>
        ))}
      </details>
    </section>
  );
}
