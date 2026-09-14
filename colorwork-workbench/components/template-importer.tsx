'use client';

import { ChangeEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { CheckCircle2, FolderInput, HardDriveUpload, RefreshCw, TriangleAlert } from 'lucide-react';
import type { CatalogData, RuntimeAsset, TemplateSummary } from '@/lib/catalog';

type ImportedTemplate = { templateId: string; psdName: string; jpgName: string; updatedAt: string };
type SourcePair = { template: TemplateSummary; jpg: File; psd: File };
type RuntimePair = { asset: RuntimeAsset; file: File };

async function responseJson<T>(response: Response): Promise<T> {
  const data = await response.json() as T & { error?: string };
  if (!response.ok) throw new Error(data.error || '上传失败。');
  return data;
}

function apiAssetPath(key: string) {
  return `/api/runtime-assets/${key.split('/').map(encodeURIComponent).join('/')}`;
}

function selectedPath(file: File) {
  return (file.webkitRelativePath || file.name).replaceAll('\\', '/').toLowerCase();
}

async function uploadRuntimeAsset(pair: RuntimePair) {
  await responseJson(await fetch(apiAssetPath(pair.asset.key), {
    method: 'PUT',
    headers: { 'content-type': pair.asset.contentType },
    body: pair.file,
  }));
}

async function uploadPair(pair: SourcePair, onProgress: (value: number) => void) {
  if (pair.psd.size > 256 * 1024 * 1024) throw new Error(`${pair.psd.name} 超过 256 MB。`);
  const start = await responseJson<{ uploadId: string; versionId: string; partSize: number }>(
    await fetch(`/api/templates/${pair.template.id}/psd-upload`, { method: 'POST' }),
  );
  await responseJson(await fetch(
    `/api/templates/${pair.template.id}/file/jpg?version=${encodeURIComponent(start.versionId)}`,
    { method: 'PUT', headers: { 'content-type': 'image/jpeg' }, body: pair.jpg },
  ));

  const parts: Array<{ partNumber: number; etag: string }> = [];
  const totalParts = Math.ceil(pair.psd.size / start.partSize);
  for (let index = 0; index < totalParts; index += 1) {
    const partNumber = index + 1;
    const chunk = pair.psd.slice(index * start.partSize, Math.min(pair.psd.size, partNumber * start.partSize));
    const uploaded = await responseJson<{ partNumber: number; etag: string }>(await fetch(
      `/api/templates/${pair.template.id}/psd-upload/${encodeURIComponent(start.uploadId)}/${partNumber}?version=${encodeURIComponent(start.versionId)}`,
      { method: 'PUT', headers: { 'content-type': 'application/octet-stream' }, body: chunk },
    ));
    parts.push(uploaded);
    onProgress(Math.round(partNumber / totalParts * 100));
  }

  await responseJson(await fetch(
    `/api/templates/${pair.template.id}/psd-upload/${encodeURIComponent(start.uploadId)}/complete`,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        versionId: start.versionId,
        parts,
        sourcePsdName: pair.psd.name,
        referenceJpgName: pair.jpg.name,
      }),
    },
  ));
}

export function TemplateImporter({
  catalog,
  runtimeReady,
  onRuntimeReady,
}: {
  catalog: CatalogData;
  runtimeReady: boolean;
  onRuntimeReady: () => void;
}) {
  const { templates, runtimeAssets } = catalog;
  const [files, setFiles] = useState<File[]>([]);
  const [imported, setImported] = useState<ImportedTemplate[]>([]);
  const [uploadedRuntimeKeys, setUploadedRuntimeKeys] = useState<string[]>([]);
  const [runtimeIsReady, setRuntimeIsReady] = useState(runtimeReady);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState('');
  const [errors, setErrors] = useState<string[]>([]);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      const [templateData, runtimeData] = await Promise.all([
        fetch('/api/templates/status', { cache: 'no-store' }).then(responseJson<{ templates: ImportedTemplate[] }>),
        fetch('/api/runtime-assets/status', { cache: 'no-store' }).then(responseJson<{ ready: boolean; assets: Array<{ key: string }> }>),
      ]);
      setImported(templateData.templates);
      setUploadedRuntimeKeys(runtimeData.assets.map((asset) => asset.key));
      setRuntimeIsReady(runtimeData.ready);
      if (runtimeData.ready && !runtimeReady) onRuntimeReady();
    } catch (reason) {
      setErrors([reason instanceof Error ? reason.message : '导入状态读取失败。']);
    } finally {
      setLoading(false);
    }
  }, [onRuntimeReady, runtimeReady]);

  useEffect(() => { void loadStatus(); }, [loadStatus]);

  const importedIds = useMemo(() => new Set(imported.map((item) => item.templateId)), [imported]);
  const uploadedKeys = useMemo(() => new Set(uploadedRuntimeKeys), [uploadedRuntimeKeys]);
  const pairs = useMemo(() => {
    const byName = new Map(files.map((file) => [file.name.trim().toLowerCase(), file]));
    return templates.map((template) => {
      const jpg = byName.get(template.referenceJpgName.toLowerCase());
      const psd = byName.get(template.sourcePsdName.toLowerCase());
      return jpg && psd ? { template, jpg, psd } : null;
    }).filter((value): value is SourcePair => Boolean(value));
  }, [files, templates]);
  const runtimePairs = useMemo(() => {
    const selected = files.map((file) => ({ file, path: selectedPath(file) }));
    return runtimeAssets.map((asset) => {
      const suffix = asset.relativePath.toLowerCase();
      const match = selected.find(({ path }) => path === suffix || path.endsWith(`/${suffix}`));
      return match ? { asset, file: match.file } : null;
    }).filter((value): value is RuntimePair => Boolean(value));
  }, [files, runtimeAssets]);

  const templateQueue = pairs.filter((pair) => !importedIds.has(pair.template.id));
  const runtimeQueue = runtimePairs.filter((pair) => !uploadedKeys.has(pair.asset.key));
  const missingFileTemplates = files.length
    ? templates.filter((template) => !importedIds.has(template.id) && !pairs.some((pair) => pair.template.id === template.id))
    : [];
  const missingRuntimeAssets = files.length
    ? runtimeAssets.filter((asset) => !uploadedKeys.has(asset.key) && !runtimePairs.some((pair) => pair.asset.key === asset.key))
    : [];
  const queueCount = runtimeQueue.length + templateQueue.length;
  const selectionComplete = files.length > 0 && !missingFileTemplates.length && !missingRuntimeAssets.length;

  function chooseFiles(event: ChangeEvent<HTMLInputElement>) {
    setFiles(Array.from(event.target.files || []));
    setErrors([]);
    setProgress('');
  }

  async function importMissing() {
    if (!queueCount || running || !selectionComplete) return;
    setRunning(true);
    setErrors([]);
    const failures: string[] = [];
    for (let index = 0; index < runtimeQueue.length; index += 1) {
      const pair = runtimeQueue[index];
      try {
        setProgress(`工作台素材 ${index + 1}／${runtimeQueue.length} · ${pair.asset.key}`);
        await uploadRuntimeAsset(pair);
      } catch (reason) {
        failures.push(`工作台素材 ${pair.asset.key}：${reason instanceof Error ? reason.message : '上传失败'}`);
      }
    }

    if (!failures.length && !runtimeIsReady) {
      try {
        setProgress('正在核对工作台素材完整性…');
        await responseJson(await fetch('/api/runtime-assets/complete', { method: 'POST' }));
        setRuntimeIsReady(true);
        onRuntimeReady();
      } catch (reason) {
        failures.push(reason instanceof Error ? reason.message : '工作台素材启用失败。');
      }
    }

    for (let index = 0; index < templateQueue.length; index += 1) {
      const pair = templateQueue[index];
      try {
        setProgress(`源文件 ${index + 1}／${templateQueue.length} · ${pair.template.productName} · 0%`);
        await uploadPair(pair, (value) => setProgress(
          `源文件 ${index + 1}／${templateQueue.length} · ${pair.template.productName} · ${value}%`,
        ));
      } catch (reason) {
        failures.push(`${pair.template.productName} · ${pair.template.radio}：${reason instanceof Error ? reason.message : '上传失败'}`);
      }
    }

    setErrors(failures);
    setProgress(failures.length ? '导入结束。重新选择同一文件夹后会只补传缺少的内容。' : '工作台素材和 23 套源文件已经全部导入。');
    await loadStatus();
    setRunning(false);
  }

  const directoryProps = { webkitdirectory: '', directory: '' } as Record<string, string>;

  return (
    <section className="import-card">
      <header>
        <div><span>WORKBENCH SETUP</span><h2>首次上线导入</h2></div>
        <button onClick={loadStatus} disabled={loading || running}><RefreshCw size={15} />刷新状态</button>
      </header>
      <p>首次上线时选择准备好的“首次上线导入包”一次。系统会上传登录后才能读取的工作台素材，并匹配 23 组 JPG 与 PSD；中断后重新选择同一文件夹即可续传。</p>
      <div className="import-summary">
        <span><CheckCircle2 size={18} />工作台素材 <strong>{uploadedRuntimeKeys.length}／{runtimeAssets.length}</strong></span>
        <span><CheckCircle2 size={18} />源文件 <strong>{imported.length}／{templates.length}</strong></span>
        <span><FolderInput size={18} />当前匹配 <strong>{runtimePairs.length + pairs.length} 项</strong></span>
      </div>
      <label className="folder-picker">
        <FolderInput size={20} />
        <span><strong>选择首次上线导入包</strong><small>浏览器只读取其中的 87 个工作台素材和 23 组 JPG／PSD</small></span>
        <input type="file" multiple {...directoryProps} onChange={chooseFiles} disabled={running} />
      </label>
      {(missingFileTemplates.length > 0 || missingRuntimeAssets.length > 0) && (
        <p className="warning"><TriangleAlert size={15} />所选文件夹还缺 {missingRuntimeAssets.length} 个工作台素材、{missingFileTemplates.length} 组源文件，请选择完整的“首次上线导入包”。</p>
      )}
      {runtimeIsReady && <p className="source-note"><CheckCircle2 size={15} />登录后素材已启用。</p>}
      {progress && <output className="import-progress">{progress}</output>}
      {errors.map((error) => <p className="error" key={error}>{error}</p>)}
      <button className="import-action" onClick={importMissing} disabled={running || !queueCount || !selectionComplete}>
        <HardDriveUpload size={17} />
        {running ? '正在导入，请保持页面打开' : queueCount ? `导入剩余 ${queueCount} 项` : runtimeIsReady && imported.length === templates.length ? '首次导入已完成' : '请选择完整导入包'}
      </button>
    </section>
  );
}
