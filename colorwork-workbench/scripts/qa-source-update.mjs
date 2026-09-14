import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { writePsd } from 'ag-psd';
import sharp from 'sharp';

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const baseUrl = (process.argv.find((value) => value.startsWith('--base-url='))?.split('=')[1] || 'http://127.0.0.1:4173').replace(/\/$/, '');
const templateId = 'tape-hair-super';
const initialWidth = 1000;
const initialHeight = 1027;
const originalNames = {
  psd: 'Tape Hair-Super Double Drawn.psd',
  jpg: 'Tape Hair-Super Double Drawn.jpg',
};
function assert(condition, message, details) {
  if (!condition) throw new Error(`${message}${details === undefined ? '' : `：${JSON.stringify(details)}`}`);
}

function hash(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

async function api(urlPath, options = {}, expected = [200]) {
  const headers = { ...options.headers };
  let body = options.body;
  if (options.json !== undefined) {
    headers['content-type'] = 'application/json';
    body = JSON.stringify(options.json);
  }
  const response = await fetch(`${baseUrl}${urlPath}`, { ...options, headers, body });
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json')
    ? await response.json()
    : Buffer.from(await response.arrayBuffer());
  if (!expected.includes(response.status)) {
    throw new Error(`${options.method || 'GET'} ${urlPath} 返回 ${response.status}：${JSON.stringify(data)}`);
  }
  return { status: response.status, data, headers: response.headers };
}

async function expectApiError(urlPath, options, status, code) {
  const result = await api(urlPath, options, [status]);
  assert(result.data?.code === code, `${urlPath} 应返回 ${code}`, result.data);
  return result.data;
}

function makePsd(width, height, rgb) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let offset = 0; offset < data.length; offset += 4) {
    data[offset] = rgb[0];
    data[offset + 1] = rgb[1];
    data[offset + 2] = rgb[2];
    data[offset + 3] = 255;
  }
  return Buffer.from(writePsd({ width, height, imageData: { data, width, height }, children: [] }));
}

function makeJpg(width, height, background) {
  return sharp({ create: { width, height, channels: 3, background } }).jpeg({ quality: 88 }).toBuffer();
}

function makePng(width, height, background) {
  return sharp({ create: { width, height, channels: 4, background } }).png().toBuffer();
}

async function multipartPart(urlPath, bytes) {
  const uploaded = await api(urlPath, { method: 'PUT', body: bytes }, [200]);
  return { partNumber: uploaded.data.partNumber, etag: uploaded.data.etag };
}

async function firstImport(psd, jpg) {
  const started = await api(`/api/templates/${templateId}/psd-upload`, { method: 'POST' }, [200]);
  await api(`/api/templates/${templateId}/file/jpg?version=${encodeURIComponent(started.data.versionId)}`, {
    method: 'PUT', body: jpg,
  }, [200]);
  const part = await multipartPart(
    `/api/templates/${templateId}/psd-upload/${encodeURIComponent(started.data.uploadId)}/1?version=${encodeURIComponent(started.data.versionId)}`,
    psd,
  );
  await api(`/api/templates/${templateId}/psd-upload/${encodeURIComponent(started.data.uploadId)}/complete`, {
    method: 'POST',
    json: {
      parts: [part],
      sourcePsdName: originalNames.psd,
      referenceJpgName: originalNames.jpg,
      versionId: started.data.versionId,
    },
  }, [200]);
}

async function createSourceCandidate(psd, jpg, suffix) {
  const started = await api(`/api/template-sources/${templateId}`, {
    method: 'POST',
    json: {
      psdName: `Tape Hair-Super Double Drawn-${suffix}.psd`,
      jpgName: `Tape Hair-Super Double Drawn-${suffix}.jpg`,
      psdSize: psd.byteLength,
      jpgSize: jpg.byteLength,
    },
  }, [201]);
  const versionId = started.data.sourceVersion.id;
  await api(`/api/template-sources/${templateId}/${versionId}/file/jpg`, { method: 'PUT', body: jpg }, [200]);
  const part = await multipartPart(
    `/api/template-sources/${templateId}/${versionId}/psd-upload/${encodeURIComponent(started.data.uploadId)}/1`,
    psd,
  );
  return { ...started.data, versionId, parts: [part] };
}

async function completeSourceCandidate(candidate, expected = [200]) {
  return api(
    `/api/template-sources/${templateId}/${candidate.versionId}/psd-upload/${encodeURIComponent(candidate.uploadId)}/complete`,
    { method: 'POST', json: { parts: candidate.parts } },
    expected,
  );
}

function entryForCode(snapshot, code) {
  const color = snapshot.colors.find((item) => item.code.toUpperCase() === code.toUpperCase());
  const entry = color && snapshot.selection.find((item) => item.colorId === color.id);
  assert(color && entry, `找不到 ${code} 的当前母版条目`);
  return { color, entry };
}

function specFor(snapshot, code, length) {
  const { entry } = entryForCode(snapshot, code);
  const spec = snapshot.specs.find((item) => item.entryId === entry.entryId && item.length === length);
  assert(spec, `找不到 ${code} ${length}″ 规格`);
  return spec;
}

async function createReadyArtifact(name, snapshot, jpg) {
  const created = await api('/api/artifacts', {
    method: 'POST',
    json: {
      name,
      templateId,
      expectedMasterRevision: snapshot.masterRevision,
      expectedInventoryRevision: snapshot.inventoryRevision,
      expectedSourceVersionId: snapshot.sourceVersion.id,
    },
  }, [201]);
  const id = created.data.artifact.id;
  await api(`/api/artifacts/${id}/file/jpg`, { method: 'PUT', body: jpg }, [200]);
  await api(`/api/artifacts/${id}`, { method: 'PATCH', json: { jpgOnly: true } }, [200]);
  return id;
}

const report = { passed: false, templateId, checks: [], versions: {} };
const note = (name, details = true) => report.checks.push({ name, details });

const initialPsd = makePsd(initialWidth, initialHeight, [236, 232, 226]);
const initialJpg = await makeJpg(initialWidth, initialHeight, '#ece8e2');
await firstImport(initialPsd, initialJpg);
await expectApiError(`/api/templates/${templateId}/psd-upload`, { method: 'POST' }, 409, 'TEMPLATE_ALREADY_IMPORTED');
note('首次导入不可重复创建模板');

let baseline = (await api(`/api/inventory/${templateId}`, {}, [200])).data;
assert(baseline.sourceVersion.number === 1 && baseline.sourceVersion.status === 'active', '首次源文件版本未成为 S1');
const oldSourceId = baseline.sourceVersion.id;
const oldMasterVersionId = baseline.version.id;
report.versions.initialSource = { id: oldSourceId, number: baseline.sourceVersion.number };

const baselineChanges = [
  ['#1B', 18, 'restocking'],
  ['#1B', 22, 'out_of_stock'],
  ['#2B', 18, 'restocking'],
  ['#2B', 22, 'out_of_stock'],
  ['#1006', 18, 'out_of_stock'],
  ['#5ATP5A/1006', 22, 'out_of_stock'],
].map(([code, length, status]) => ({ specId: specFor(baseline, code, length).specId, status }));
baseline = (await api(`/api/inventory/${templateId}`, {
  method: 'PATCH',
  json: {
    expectedMasterRevision: baseline.masterRevision,
    expectedInventoryRevision: baseline.inventoryRevision,
    expectedSourceVersionId: baseline.sourceVersion.id,
    updates: baselineChanges,
  },
}, [200])).data;
note('建立缺货迁移基线', { inventoryRevision: baseline.inventoryRevision });

const oldArtifactId = await createReadyArtifact('QA-旧版母版导出', baseline, initialJpg);
const oldArtifactDownload = (await api(`/api/artifacts/${oldArtifactId}/download/jpg`, {}, [200])).data;
const oldArtifactHash = hash(oldArtifactDownload);

const nextWidth = 820;
const nextHeight = 620;
const nextPsd = makePsd(nextWidth, nextHeight, [218, 226, 234]);
const nextJpg = await makeJpg(nextWidth, nextHeight, '#dae2ea');
const candidate = await createSourceCandidate(nextPsd, nextJpg, 'QA-S2');
await completeSourceCandidate(candidate);
const sourceVersionId = candidate.versionId;
report.versions.candidateSource = { id: sourceVersionId, number: candidate.sourceVersion.number };

const byCode = Object.fromEntries(['#1B', '#2B', '#1006', '#5ATP5A/1006', '#62'].map((code) => [code, entryForCode(baseline, code)]));
const assetNames = {
  '#1006': 'colors/1006.png',
  '#1B': 'colors/1b.png',
  '#5ATP5A/1006': 'colors/5atp5a-1006.png',
  '#62': 'colors/62.png',
};
const palette = {
  '#1006': '#d8b594',
  '#1B': '#211d1d',
  '#5ATP5A/1006': '#c6a984',
  '#62': '#cc9e72',
};
await api(`/api/template-sources/${templateId}/${sourceVersionId}/assets/base.png`, {
  method: 'PUT', body: await makePng(nextWidth, nextHeight, '#f6f4f0'),
}, [200]);
for (const [code, assetName] of Object.entries(assetNames)) {
  await api(`/api/template-sources/${templateId}/${sourceVersionId}/assets/${assetName}`, {
    method: 'PUT', body: await makePng(140, 140, palette[code]),
  }, [200]);
}

const cardInput = [
  { code: '#1006', candidateId: 'candidate-1006', lengths: [18, 22], matchState: 'exact' },
  { code: '#1B', candidateId: 'candidate-1b', lengths: [18, 24], matchState: 'exact' },
  { code: '#5ATP5A/1006', candidateId: 'candidate-blend', lengths: [18, 22], matchState: 'exact' },
  { code: '#62', candidateId: 'candidate-62', lengths: [18, 24], matchState: 'unresolved' },
];
const nextCards = cardInput.map((item, index) => {
  const { color, entry } = byCode[item.code];
  const left = 55 + index * 185;
  const exact = item.matchState === 'exact';
  return {
    candidateId: item.candidateId,
    entryId: `parsed-${item.candidateId}`,
    colorId: color.id,
    colorCode: color.code,
    lengths: item.lengths,
    hot: item.code === '#5ATP5A/1006',
    section: null,
    order: index,
    geometry: {
      swatch: [left, 210, left + 140, 350],
      colorLabel: [left + 25, 372, left + 115, 396],
      sizeLabel: [left + 15, 410, left + 125, 438],
      hotBadge: item.code === '#5ATP5A/1006' ? [left + 105, 190, left + 150, 214] : null,
    },
    matchState: item.matchState,
    matchedEntryId: exact ? entry.entryId : null,
    matchReason: exact ? 'QA：唯一规范色号匹配' : 'QA：模拟无法可靠识别，需人工确认',
  };
});
const nextColors = Object.entries(assetNames).map(([code, assetName]) => {
  const { color } = byCode[code];
  return {
    ...color,
    image: `/api/template-source-assets/${sourceVersionId}/${assetName}`,
    sourceVersionId,
  };
});
const parsedConfig = {
  schemaVersion: 1,
  template: {
    ...baseline.template,
    width: nextWidth,
    height: nextHeight,
    sourcePsdName: 'Tape Hair-Super Double Drawn-QA-S2.psd',
    referenceJpgName: 'Tape Hair-Super Double Drawn-QA-S2.jpg',
    referenceUrl: `/api/template-source-assets/${sourceVersionId}/reference.jpg`,
    baseUrl: `/api/template-source-assets/${sourceVersionId}/base.png`,
    hotUrl: undefined,
    dynamicBounds: [45, 180, 780, 470],
    availableLengths: [18, 22, 24],
    sourceVersionId,
    sections: [],
    initialCards: nextCards,
    initialColorCount: nextCards.length,
    legacyColors: [],
    warnings: ['#62 需要管理员人工确认。'],
  },
  colors: nextColors,
  availableLengths: [18, 22, 24],
  parseIssues: [{
    issueId: 'qa-unreliable-62',
    code: 'UNRELIABLE_LAYER',
    message: '#62 的图层结构无法可靠识别，请人工确认映射。',
    candidateId: 'candidate-62',
    blocking: true,
  }],
  parseSummary: {
    layerCount: 18,
    parsedColorCount: nextCards.length,
    parsedSpecCount: nextCards.reduce((sum, card) => sum + card.lengths.length, 0),
    sectionCount: 0,
    documentWidth: nextWidth,
    documentHeight: nextHeight,
  },
};
const parsed = (await api(`/api/template-sources/${templateId}/${sourceVersionId}/parse`, {
  method: 'POST', json: parsedConfig,
}, [200])).data;
assert(parsed.status === 'needs_review', '包含无法可靠识别项时应进入待确认状态', parsed);
assert(parsed.diff.added.some((item) => item.colorCode === '#62'), '变化清单缺少新增 #62', parsed.diff);
assert(parsed.diff.removed.some((item) => item.colorCode === '#2B'), '变化清单缺少移除 #2B', parsed.diff);
assert(parsed.diff.resized.some((item) => item.colorCode === '#1B'), '变化清单缺少 #1B 尺寸调整', parsed.diff);
assert(parsed.diff.reordered.some((item) => item.colorCode === '#1006'), '变化清单缺少重新排列 #1006', parsed.diff);
assert(parsed.diff.dimensionsChanged?.after.width === nextWidth, '变化清单缺少画布尺寸调整', parsed.diff);
note('解析变化清单包含新增、移除、重排与尺寸调整', parsed.diff);

const beforeActivation = (await api(`/api/inventory/${templateId}`, {}, [200])).data;
assert(beforeActivation.sourceVersion.id === oldSourceId, '管理员确认前不应切换当前源文件');

const brokenPsd = makePsd(620, 420, [240, 220, 220]);
const brokenJpg = await makeJpg(621, 420, '#f0dcdc');
const broken = await createSourceCandidate(brokenPsd, brokenJpg, 'QA-BROKEN');
const brokenResult = await completeSourceCandidate(broken, [422]);
assert(typeof brokenResult.data?.error === 'string', '损坏候选应明确返回失败原因', brokenResult.data);
const afterBroken = (await api(`/api/inventory/${templateId}`, {}, [200])).data;
assert(afterBroken.sourceVersion.id === oldSourceId, '解析失败不得影响原有效版本');
note('PSD/JPG 尺寸不一致时失败且原版本继续使用');

const activationBase = {
  expectedMasterRevision: beforeActivation.masterRevision,
  mappings: [{
    candidateId: 'candidate-62', entryId: null, treatAsNew: true, lengths: [18, 24], section: null,
  }],
  acknowledgedIssues: ['qa-unreliable-62'],
  initialStatuses: [
    { candidateId: 'candidate-1b', length: 24, status: 'out_of_stock' },
    { candidateId: 'candidate-62', length: 18, status: 'restocking' },
    { candidateId: 'candidate-62', length: 24, status: 'normal' },
  ],
};
await expectApiError(`/api/template-sources/${templateId}/${sourceVersionId}/activate`, {
  method: 'POST', json: { ...activationBase, acknowledgedIssues: [] },
}, 422, 'SOURCE_ISSUES_NOT_ACKNOWLEDGED');
await expectApiError(`/api/template-sources/${templateId}/${sourceVersionId}/activate`, {
  method: 'POST', json: { ...activationBase, mappings: [] },
}, 422, 'SOURCE_MAPPING_REQUIRED');
await expectApiError(`/api/template-sources/${templateId}/${sourceVersionId}/activate`, {
  method: 'POST', json: { ...activationBase, initialStatuses: [] },
}, 422, 'INITIAL_STATUS_MISMATCH');
note('未确认识别问题、未映射或未填写新增规格状态时均阻止启用');

let activated = (await api(`/api/template-sources/${templateId}/${sourceVersionId}/activate`, {
  method: 'POST', json: activationBase,
}, [201])).data;
assert(activated.sourceVersion.id === sourceVersionId, '启用后当前源文件不是候选 S2', activated.sourceVersion);
assert(activated.version.action === 'source_update', '启用没有建立 source_update 母版版本', activated.version);
assert(activated.template.width === nextWidth && activated.template.height === nextHeight, '启用后画布尺寸未更新');
report.versions.activatedMaster = { id: activated.version.id, number: activated.version.number };

for (const [code, length] of [['#1B', 18], ['#1006', 18], ['#5ATP5A/1006', 22]]) {
  const before = specFor(baseline, code, length);
  const after = specFor(activated, code, length);
  assert(after.specId === before.specId && after.status === before.status, `${code} ${length}″ 未保留原规格身份和缺货状态`, { before, after });
}
assert(!activated.specs.some((spec) => spec.colorId === byCode['#2B'].color.id), '被移除 #2B 仍出现在新版业务规格');
assert(!activated.specs.some((spec) => spec.entryId === byCode['#1B'].entry.entryId && spec.length === 22), '#1B 22″ 应随新版移除');
assert(specFor(activated, '#1B', 24).status === 'out_of_stock', '#1B 24″ 初始状态未按管理员确认值写入');
assert(specFor(activated, '#62', 18).status === 'restocking', '#62 18″ 初始状态未按管理员确认值写入');
assert(specFor(activated, '#62', 24).status === 'normal', '#62 24″ 初始状态未按管理员确认值写入');
note('启用后按语义保留旧状态，并显式初始化新增规格');

for (const [urlPath, method, json, expectedCode] of [
  [`/api/inventory/${templateId}`, 'PATCH', {
    expectedMasterRevision: beforeActivation.masterRevision,
    expectedInventoryRevision: beforeActivation.inventoryRevision,
    expectedSourceVersionId: oldSourceId,
    updates: [{ specId: specFor(beforeActivation, '#1B', 18).specId, status: 'normal' }],
  }, 'SOURCE_VERSION_CHANGED'],
  [`/api/inventory/${templateId}/validate`, 'POST', {
    expectedMasterRevision: beforeActivation.masterRevision,
    expectedInventoryRevision: beforeActivation.inventoryRevision,
    expectedSourceVersionId: oldSourceId,
    specIds: [specFor(beforeActivation, '#1B', 18).specId],
  }, 'SOURCE_VERSION_CHANGED'],
  ['/api/artifacts', 'POST', {
    name: 'QA-旧页面禁止导出', templateId,
    expectedMasterRevision: beforeActivation.masterRevision,
    expectedInventoryRevision: beforeActivation.inventoryRevision,
    expectedSourceVersionId: oldSourceId,
  }, 'ARTIFACT_REVISION_CONFLICT'],
]) {
  await expectApiError(urlPath, { method, json }, 409, expectedCode);
}
note('旧页面在保存、校验和新建导出前均被版本冲突拦截');

const retainedBefore = specFor(activated, '#1B', 18);
activated = (await api(`/api/inventory/${templateId}`, {
  method: 'PATCH',
  json: {
    expectedMasterRevision: activated.masterRevision,
    expectedInventoryRevision: activated.inventoryRevision,
    expectedSourceVersionId: activated.sourceVersion.id,
    updates: [{ specId: retainedBefore.specId, status: 'normal' }],
  },
}, [200])).data;
const oldHistorical = (await api(`/api/master/${templateId}/versions/${oldMasterVersionId}`, {}, [200])).data;
assert(specFor({ ...oldHistorical, specs: oldHistorical.inventory }, '#1B', 18).status === 'restocking', '旧母版库存快照被新版库存修改覆盖');
assert(specFor({ ...oldHistorical, specs: oldHistorical.inventory }, '#2B', 18).status === 'restocking', '被移除规格的旧状态未保留');
note('旧版母版库存快照保持不可变');

const newArtifactId = await createReadyArtifact('QA-新版母版导出', activated, nextJpg);
const [oldArtifact, newArtifact] = await Promise.all([
  api(`/api/artifacts/${oldArtifactId}`, {}, [200]),
  api(`/api/artifacts/${newArtifactId}`, {}, [200]),
]);
assert(oldArtifact.data.artifact.config.sourceVersion.id === oldSourceId, '旧导出丢失原源版本关联');
assert(newArtifact.data.artifact.config.sourceVersion.id === sourceVersionId, '新导出没有关联新版源文件');
const oldAfterActivation = (await api(`/api/artifacts/${oldArtifactId}/download/jpg`, {}, [200])).data;
assert(hash(oldAfterActivation) === oldArtifactHash, '源版本切换后历史导出图片发生变化');
note('历史导出图片及其母版版本关联保持原样');

const sourcesAfterEnable = (await api(`/api/template-sources/${templateId}`, {}, [200])).data;
const source1 = sourcesAfterEnable.versions.find((item) => item.id === oldSourceId);
const source2 = sourcesAfterEnable.versions.find((item) => item.id === sourceVersionId);
const failedSource = sourcesAfterEnable.versions.find((item) => item.id === broken.versionId);
assert(source1?.status === 'superseded' && source2?.status === 'active' && failedSource?.status === 'failed', '源版本生命周期状态不正确', sourcesAfterEnable.versions);
for (const id of [oldSourceId, sourceVersionId]) {
  await api(`/api/template-sources/${templateId}/${id}/download/psd`, {}, [200]);
  await api(`/api/template-sources/${templateId}/${id}/download/jpg`, {}, [200]);
}
note('旧、新 PSD/JPG 均保留并可由管理员下载');

const currentKeys = new Set(activated.specs.map((spec) => `${spec.entryId}\u001f${spec.length}`));
const rollbackInitialStatuses = oldHistorical.inventory
  .filter((spec) => !currentKeys.has(`${spec.entryId}\u001f${spec.length}`))
  .map((spec) => ({ entryId: spec.entryId, length: spec.length, status: spec.status }));
const rolledBack = (await api(`/api/master/${templateId}/restore`, {
  method: 'POST',
  json: {
    versionId: oldMasterVersionId,
    expectedRevision: activated.masterRevision,
    initialStatuses: rollbackInitialStatuses,
    note: 'QA：回退到旧源文件母版',
  },
}, [201])).data;
assert(rolledBack.sourceVersion.id === oldSourceId, '回退没有恢复旧源文件版本');
assert(rolledBack.template.width === initialWidth && rolledBack.template.height === initialHeight, '回退没有恢复旧母版配置');
assert(rolledBack.version.action === 'restore' && rolledBack.version.restoredFromVersionId === oldMasterVersionId, '回退未形成可追溯版本');
assert(specFor(rolledBack, '#2B', 18).status === 'restocking', '回退后被移除规格没有按旧快照恢复');
const oldAfterRollback = (await api(`/api/artifacts/${oldArtifactId}/download/jpg`, {}, [200])).data;
assert(hash(oldAfterRollback) === oldArtifactHash, '回退后历史导出图片发生变化');
note('旧源文件、母版配置和被移除规格状态可回退');

const finalSources = (await api(`/api/template-sources/${templateId}`, {}, [200])).data;
assert(finalSources.currentVersionId === oldSourceId, '回退后的当前源版本指针错误');
assert(finalSources.versions.filter((item) => item.status === 'active').length === 1, '同一模板必须且只能有一个活动源版本');
report.versions.rollbackMaster = { id: rolledBack.version.id, number: rolledBack.version.number };
report.artifacts = { oldArtifactId, newArtifactId, oldArtifactHash };
report.final = {
  currentSourceVersionId: rolledBack.sourceVersion.id,
  masterRevision: rolledBack.masterRevision,
  inventoryRevision: rolledBack.inventoryRevision,
  sourceStatuses: finalSources.versions.map(({ id, number, status }) => ({ id, number, status })),
};
report.passed = true;

await mkdir(path.join(projectDir, 'outputs'), { recursive: true });
const reportPath = path.join(projectDir, 'outputs', 'qa-source-update.json');
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
process.stdout.write(`${JSON.stringify({ passed: true, reportPath, checks: report.checks.length }, null, 2)}\n`);
