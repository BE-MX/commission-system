import { getFiles } from '@/lib/server/storage';
import { sourceReviewIssues } from '@/lib/source-review';
import { env } from 'cloudflare:workers';
import {
  colorsForTemplate,
  lengthsForTemplate,
  type Selection,
  type StockColor,
  type TemplateSummary,
} from '@/lib/catalog';
import { computeSourceChanges } from '@/lib/source-diff';
import {
  sourceAssetUrl,
  type SourceCard,
  type SourceIssueDetails,
  type SourceParseIssue,
  type SourceTemplateConfig,
  type SourceVersionStatus,
  type SourceVersionSummary,
} from '@/lib/source-versions';
import type { AuthorizedUser } from '@/lib/server/auth';
import { CATALOG, serverTemplateById } from '@/lib/server/catalog';
import { psdDimensions, JPG_LIMIT, PSD_LIMIT, PSD_PART_SIZE } from '@/lib/server/uploads';

type SqlValue = string | number | null;

type SourceAssetManifestItem = {
  name: string;
  size: number;
  sha256: string;
};

type SourceStateRow = {
  templateId: string;
  revision: number;
  currentVersionId: string | null;
  nextVersionNumber: number;
};

export type StoredSourceVersion = {
  id: string;
  templateId: string;
  versionNumber: number;
  basedOnSourceVersionId: string | null;
  comparedMasterVersionId: string | null;
  status: SourceVersionStatus;
  sourcePsdKey: string;
  referenceJpgKey: string;
  sourcePsdName: string;
  referenceJpgName: string;
  sourcePsdSize: number;
  referenceJpgSize: number;
  configJson: string | null;
  assetManifestJson: string;
  diffJson: string | null;
  unresolvedJson: string;
  failureReason: string | null;
  createdByUserId: string;
  createdByEmail: string;
  createdByDisplayName: string;
  createdAt: string;
  updatedAt: string;
  activatedAt: string | null;
};

type InitialFilesRow = {
  sourcePsdKey: string;
  referenceJpgKey: string;
  sourcePsdName: string;
  referenceJpgName: string;
  importedBy: string;
  createdAt: string;
};

export class TemplateSourceError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'TemplateSourceError';
  }
}

export function templateSourceErrorResponse(error: unknown) {
  if (!(error instanceof TemplateSourceError)) return null;
  return Response.json(
    { error: error.message, code: error.code, ...(error.details ? { details: error.details } : {}) },
    {
      status: error.status,
      headers: { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' },
    },
  );
}

function fail(status: number, code: string, message: string, details?: Record<string, unknown>): never {
  throw new TemplateSourceError(status, code, message, details);
}

function requireTemplate(templateId: string) {
  const template = serverTemplateById(templateId);
  if (!template) fail(404, 'TEMPLATE_NOT_FOUND', '没有找到这个产品与 Radio 母版。');
  return template;
}

function parseJson<T>(value: string | null, fallback: T): T {
  if (!value) return fallback;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

function hex(bytes: ArrayBuffer) {
  return [...new Uint8Array(bytes)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

async function assetFingerprint(key: string, name: string): Promise<SourceAssetManifestItem | null> {
  const object = await getFiles().head(key);
  if (!object) return null;
  let sha256 = object.customMetadata?.sha256 ?? '';
  if (!/^[a-f0-9]{64}$/.test(sha256)) {
    const body = await getFiles().get(key);
    if (!body) return null;
    sha256 = hex(await crypto.subtle.digest('SHA-256', await body.arrayBuffer()));
  }
  return { name, size: object.size, sha256 };
}

function batchChanges(result: D1Result<unknown> | undefined) {
  return Number((result?.meta as { changes?: number } | undefined)?.changes ?? 0);
}

async function readSourceState(templateId: string) {
  return env.DB.prepare(`
    SELECT template_id AS templateId, revision, current_version_id AS currentVersionId,
      next_version_number AS nextVersionNumber
    FROM template_source_state WHERE template_id = ?
  `).bind(templateId).first<SourceStateRow>();
}

export async function readSourceVersion(templateId: string, versionId: string) {
  return env.DB.prepare(`
    SELECT id, template_id AS templateId, version_number AS versionNumber,
      based_on_source_version_id AS basedOnSourceVersionId,
      compared_master_version_id AS comparedMasterVersionId, status,
      source_psd_key AS sourcePsdKey, reference_jpg_key AS referenceJpgKey,
      source_psd_name AS sourcePsdName, reference_jpg_name AS referenceJpgName,
      source_psd_size AS sourcePsdSize, reference_jpg_size AS referenceJpgSize,
      config_json AS configJson, asset_manifest_json AS assetManifestJson,
      diff_json AS diffJson, unresolved_json AS unresolvedJson, failure_reason AS failureReason,
      created_by_user_id AS createdByUserId, created_by_email AS createdByEmail,
      created_by_display_name AS createdByDisplayName, created_at AS createdAt,
      updated_at AS updatedAt, activated_at AS activatedAt
    FROM template_source_versions WHERE template_id = ? AND id = ?
  `).bind(templateId, versionId).first<StoredSourceVersion>();
}

function staticConfig(template: TemplateSummary, sourceVersionId: string | null): SourceTemplateConfig {
  const availableLengths = lengthsForTemplate(template);
  return {
    schemaVersion: 1,
    template: {
      ...template,
      sourceVersionId,
      availableLengths,
      initialCards: template.initialCards.map((card, index) => ({
        ...card,
        candidateId: `initial-${index + 1}`,
        geometry: card.geometry ?? { swatch: template.dynamicBounds },
        matchState: 'exact',
        matchedEntryId: card.entryId,
        matchReason: '首次导入母版',
      })),
    },
    colors: colorsForTemplate(CATALOG.colors, template),
    availableLengths,
    parseIssues: template.warnings.map((message, index) => ({
      issueId: `initial-warning-${index + 1}`,
      code: `INITIAL_WARNING_${index + 1}`,
      message,
      blocking: false,
    })),
    parseSummary: {
      layerCount: 0,
      parsedColorCount: template.initialCards.length,
      parsedSpecCount: template.initialCards.reduce((sum, card) => sum + card.lengths.length, 0),
      sectionCount: template.sections.length,
      documentWidth: template.width,
      documentHeight: template.height,
    },
  };
}

export function effectiveSourceColors(config: SourceTemplateConfig) {
  const merged = new Map<string, StockColor>();
  for (const color of CATALOG.colors) merged.set(color.id, color);
  for (const color of config.colors) merged.set(color.id, color);
  for (const color of config.template.legacyColors) if (!merged.has(color.id)) merged.set(color.id, color);
  return [...merged.values()];
}

export async function ensureSourceHistory(templateId: string) {
  const template = requireTemplate(templateId);
  await env.DB.prepare(`
    INSERT OR IGNORE INTO template_source_state (template_id, revision, next_version_number)
    VALUES (?, 0, 1)
  `).bind(template.id).run();

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const state = await readSourceState(template.id);
    if (!state) fail(500, 'SOURCE_STATE_MISSING', '源文件版本状态尚未初始化。');
    if (state.currentVersionId) {
      const current = await readSourceVersion(template.id, state.currentVersionId);
      if (!current) fail(500, 'SOURCE_VERSION_MISSING', '当前源文件版本记录不存在。');
      return { state, current };
    }

    const files = await env.DB.prepare(`
      SELECT source_psd_key AS sourcePsdKey, reference_jpg_key AS referenceJpgKey,
        source_psd_name AS sourcePsdName, reference_jpg_name AS referenceJpgName,
        imported_by AS importedBy, created_at AS createdAt
      FROM template_files WHERE template_id = ?
    `).bind(template.id).first<InitialFilesRow>();
    if (!files) return { state, current: null };

    const sourceId = crypto.randomUUID();
    const mutationId = crypto.randomUUID();
    const now = new Date().toISOString();
    const [psd, jpg] = await Promise.all([
      getFiles().head(files.sourcePsdKey),
      getFiles().head(files.referenceJpgKey),
    ]);
    if (!psd || !jpg) fail(409, 'INITIAL_SOURCE_FILES_MISSING', '首次导入的 PSD 或 JPG 文件不存在，请重新完成首次导入。');
    const config = staticConfig(template, sourceId);
    const guardSql = `SELECT 1 FROM template_source_state WHERE template_id = ? AND last_mutation_id = ?`;
    const guard: SqlValue[] = [template.id, mutationId];
    const results = await env.DB.batch([
      env.DB.prepare(`
        UPDATE template_source_state
        SET revision = revision + 1, current_version_id = ?, next_version_number = next_version_number + 1,
          last_mutation_id = ?, updated_by_user_id = ?, updated_by_email = ?,
          updated_by_display_name = ?, updated_at = ?
        WHERE template_id = ? AND revision = ? AND current_version_id IS NULL
      `).bind(
        sourceId,
        mutationId,
        'system-source-import',
        files.importedBy,
        '系统首次导入',
        now,
        template.id,
        state.revision,
      ),
      env.DB.prepare(`
        INSERT INTO template_source_versions
          (id, template_id, version_number, based_on_source_version_id, compared_master_version_id,
           status, source_psd_key, reference_jpg_key,
           source_psd_name, reference_jpg_name, source_psd_size, reference_jpg_size,
           config_json, asset_manifest_json, diff_json, unresolved_json, failure_reason,
           created_by_user_id, created_by_email, created_by_display_name,
           created_at, updated_at, activated_at)
        SELECT ?, ?, ?, NULL, NULL, 'active', ?, ?, ?, ?, ?, ?, ?, '{}', NULL, '[]', NULL,
          'system-source-import', ?, '系统首次导入', ?, ?, ?
        WHERE EXISTS (${guardSql})
      `).bind(
        sourceId,
        template.id,
        state.nextVersionNumber,
        files.sourcePsdKey,
        files.referenceJpgKey,
        files.sourcePsdName,
        files.referenceJpgName,
        psd.size,
        jpg.size,
        JSON.stringify(config),
        files.importedBy,
        files.createdAt || now,
        now,
        now,
        ...guard,
      ),
      env.DB.prepare(`
        UPDATE master_versions SET source_version_id = ?
        WHERE template_id = ? AND source_version_id IS NULL AND EXISTS (${guardSql})
      `).bind(sourceId, template.id, ...guard),
    ]);
    if (batchChanges(results[0]) === 1) {
      const nextState = await readSourceState(template.id);
      const current = await readSourceVersion(template.id, sourceId);
      if (!nextState || !current) fail(500, 'SOURCE_HISTORY_FAILED', '首次源文件版本记录建立失败。');
      return { state: nextState, current };
    }
  }
  fail(409, 'SOURCE_STATE_CONFLICT', '源文件版本正在更新，请刷新后重试。');
}

export async function sourceContextForVersion(templateId: string, versionId: string | null) {
  const template = requireTemplate(templateId);
  if (!versionId) {
    const config = staticConfig(template, null);
    return {
      row: null,
      config,
      template: config.template,
      colors: effectiveSourceColors(config),
      sourceVersion: {
        id: null,
        number: null,
        status: 'static' as const,
        psdName: template.sourcePsdName,
        jpgName: template.referenceJpgName,
      },
    };
  }
  const row = await readSourceVersion(template.id, versionId);
  if (!row || !row.configJson) fail(500, 'SOURCE_CONFIG_MISSING', '这个母版版本对应的源文件配置不存在。');
  const config = parseJson<SourceTemplateConfig | null>(row.configJson, null);
  if (!config?.template || !Array.isArray(config.colors)) fail(500, 'SOURCE_CONFIG_INVALID', '这个源文件版本的配置无法读取。');
  return {
    row,
    config,
    template: { ...config.template, sourceVersionId: row.id, availableLengths: config.availableLengths },
    colors: effectiveSourceColors(config),
    sourceVersion: {
      id: row.id,
      number: row.versionNumber,
      status: row.status === 'active' ? 'active' as const : 'superseded' as const,
      psdName: row.sourcePsdName,
      jpgName: row.referenceJpgName,
    },
  };
}

export async function currentSourceContext(templateId: string) {
  const { current } = await ensureSourceHistory(templateId);
  return sourceContextForVersion(templateId, current?.id ?? null);
}

function cleanFileName(value: unknown, extension: '.psd' | '.jpg') {
  if (typeof value !== 'string') fail(400, 'INVALID_FILE_NAME', `请选择 ${extension.toUpperCase()} 文件。`);
  const name = value.trim().replace(/[\\/:*?"<>|]/g, '-').slice(0, 220);
  if (!name.toLowerCase().endsWith(extension)) fail(400, 'INVALID_FILE_NAME', `请选择 ${extension.toUpperCase()} 文件。`);
  return name;
}

function cleanDeclaredSize(value: unknown, maximum: number, label: string) {
  const size = Number(value);
  if (!Number.isInteger(size) || size < 1 || size > maximum) {
    fail(400, 'INVALID_FILE_SIZE', `${label} 文件不能为空或超过允许大小。`);
  }
  return size;
}

export async function createSourceUpload(templateId: string, actor: AuthorizedUser, input: unknown) {
  const template = requireTemplate(templateId);
  if (!input || typeof input !== 'object') fail(400, 'INVALID_REQUEST', '请求格式无效。');
  const body = input as Record<string, unknown>;
  const sourcePsdName = cleanFileName(body.psdName, '.psd');
  const referenceJpgName = cleanFileName(body.jpgName, '.jpg');
  const declaredPsdSize = cleanDeclaredSize(body.psdSize, PSD_LIMIT, 'PSD');
  const declaredJpgSize = cleanDeclaredSize(body.jpgSize, JPG_LIMIT, 'JPG');
  const { state, current } = await ensureSourceHistory(template.id);
  if (!current) fail(409, 'INITIAL_SOURCE_REQUIRED', '请先完成这个产品与 Radio 的首次源文件导入。');
  const pending = await env.DB.prepare(`
    SELECT COUNT(*) AS total FROM template_source_versions
    WHERE template_id = ? AND status IN ('uploading', 'parsing')
  `).bind(template.id).first<{ total: number }>();
  if ((pending?.total ?? 0) >= 2) fail(429, 'TOO_MANY_PENDING_SOURCE_UPLOADS', '已有 2 个源文件版本正在上传或解析，请先完成后再继续。');

  const id = crypto.randomUUID();
  const sourcePsdKey = `template-sources/${template.id}/versions/${id}/source.psd`;
  const referenceJpgKey = `template-sources/${template.id}/versions/${id}/reference.jpg`;
  const upload = await getFiles().createMultipartUpload(sourcePsdKey, {
    httpMetadata: { contentType: 'image/vnd.adobe.photoshop' },
  });
  const mutationId = crypto.randomUUID();
  const now = new Date().toISOString();
  try {
    const results = await env.DB.batch([
      env.DB.prepare(`
        UPDATE template_source_state
        SET revision = revision + 1, next_version_number = next_version_number + 1,
          last_mutation_id = ?, updated_by_user_id = ?, updated_by_email = ?,
          updated_by_display_name = ?, updated_at = ?
        WHERE template_id = ? AND revision = ? AND current_version_id = ?
      `).bind(
        mutationId,
        actor.id,
        actor.email,
        actor.displayName,
        now,
        template.id,
        state.revision,
        current.id,
      ),
      env.DB.prepare(`
        INSERT INTO template_source_versions
          (id, template_id, version_number, based_on_source_version_id, compared_master_version_id,
           status, source_psd_key, reference_jpg_key,
           source_psd_name, reference_jpg_name, source_psd_size, reference_jpg_size,
           config_json, asset_manifest_json, diff_json, unresolved_json, failure_reason,
           created_by_user_id, created_by_email, created_by_display_name,
           created_at, updated_at, activated_at)
        SELECT ?, ?, ?, ?, NULL, 'uploading', ?, ?, ?, ?, ?, ?, NULL, '{}', NULL, '[]', NULL,
          ?, ?, ?, ?, ?, NULL
        WHERE EXISTS (
          SELECT 1 FROM template_source_state WHERE template_id = ? AND last_mutation_id = ?
        )
      `).bind(
        id,
        template.id,
        state.nextVersionNumber,
        current.id,
        sourcePsdKey,
        referenceJpgKey,
        sourcePsdName,
        referenceJpgName,
        declaredPsdSize,
        declaredJpgSize,
        actor.id,
        actor.email,
        actor.displayName,
        now,
        now,
        template.id,
        mutationId,
      ),
    ]);
    if (batchChanges(results[0]) !== 1 || batchChanges(results[1]) !== 1) {
      await upload.abort().catch(() => undefined);
      fail(409, 'SOURCE_STATE_CONFLICT', '源文件版本已被其他操作更新，请刷新后重试。');
    }
  } catch (error) {
    await upload.abort().catch(() => undefined);
    throw error;
  }
  return {
    sourceVersion: { id, number: state.nextVersionNumber, status: 'uploading' as const },
    uploadId: upload.uploadId,
    partSize: PSD_PART_SIZE,
    declaredPsdSize,
    declaredJpgSize,
  };
}

export function sourceObjectKey(row: StoredSourceVersion, assetName: string) {
  if (assetName === 'source.psd') return row.sourcePsdKey;
  if (assetName === 'reference.jpg') return row.referenceJpgKey;
  if (assetName === 'base.png' || assetName === 'hot.png' || /^colors\/[a-z0-9][a-z0-9_-]{0,80}\.png$/.test(assetName)) {
    return `template-sources/${row.templateId}/versions/${row.id}/assets/${assetName}`;
  }
  fail(400, 'INVALID_SOURCE_ASSET', '源文件素材路径无效。');
}

function finiteNumber(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function canonicalColorCode(value: unknown) {
  return typeof value === 'string'
    ? value.trim().toUpperCase().replace(/^#/, '').replace(/[^A-Z0-9]/g, '')
    : '';
}

function sourceIssueDetails(value: unknown): SourceIssueDetails | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const input = value as Record<string, unknown>;
  const layerCount = input.layerCount == null ? null : Number(input.layerCount);
  const layerNames = Array.isArray(input.layerNames)
    ? input.layerNames.filter((item): item is string => typeof item === 'string').map((item) => item.slice(0, 240)).slice(0, 8)
    : undefined;
  const structureTypes = Array.isArray(input.structureTypes)
    ? input.structureTypes.filter((item): item is string => typeof item === 'string').map((item) => item.slice(0, 120)).slice(0, 8)
    : undefined;
  const swatchStatus = input.swatchStatus === '待确认／待补充色块图' ? input.swatchStatus : undefined;
  if (
    (layerCount != null && (!Number.isInteger(layerCount) || layerCount < 1 || layerCount > 1000)) ||
    (layerNames && layerNames.some((item) => !item.trim())) ||
    (structureTypes && structureTypes.some((item) => !item.trim())) ||
    (!layerNames && input.layerNames != null) ||
    (!structureTypes && input.structureTypes != null) ||
    (input.swatchStatus != null && !swatchStatus)
  ) fail(422, 'INVALID_PARSE_ISSUES', '解析问题详情格式无效。');
  if (layerCount == null && !layerNames?.length && !structureTypes?.length && !swatchStatus) return undefined;
  return {
    ...(Number.isInteger(layerCount) ? { layerCount: layerCount as number } : {}),
    ...(layerNames?.length ? { layerNames } : {}),
    ...(structureTypes?.length ? { structureTypes } : {}),
    ...(swatchStatus ? { swatchStatus } : {}),
  };
}

function cleanBounds(value: unknown, width: number, height: number, label: string) {
  if (!Array.isArray(value) || value.length !== 4) fail(422, 'INVALID_SOURCE_BOUNDS', `${label} 坐标无法读取。`);
  const result = value.map(finiteNumber);
  if (result.some((item) => item == null)) fail(422, 'INVALID_SOURCE_BOUNDS', `${label} 坐标无法读取。`);
  const [left, top, right, bottom] = result as number[];
  if (left < 0 || top < 0 || right <= left || bottom <= top || right > width || bottom > height) {
    fail(422, 'INVALID_SOURCE_BOUNDS', `${label} 超出新版 PSD 画布 ${width}×${height}。`);
  }
  return [left, top, right, bottom] as [number, number, number, number];
}

async function validateParsedConfig(row: StoredSourceVersion, input: unknown) {
  const original = requireTemplate(row.templateId);
  if (!input || typeof input !== 'object') fail(400, 'INVALID_PARSE_RESULT', '解析结果格式无效。');
  const raw = input as SourceTemplateConfig;
  if (raw.schemaVersion !== 1 || !raw.template || !Array.isArray(raw.colors) || !Array.isArray(raw.availableLengths)) {
    fail(400, 'INVALID_PARSE_RESULT', '解析结果缺少必要的母版数据。');
  }
  const width = Number(raw.template.width);
  const height = Number(raw.template.height);
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 200 || height < 200 || width > 12000 || height > 12000) {
    fail(422, 'INVALID_DOCUMENT_SIZE', 'PSD 画布尺寸无法用于工作台。');
  }
  const reference = await getFiles().head(row.referenceJpgKey);
  const psdObject = await getFiles().get(row.sourcePsdKey, { range: { offset: 0, length: 26 } });
  const psd = psdObject ? psdDimensions(new Uint8Array(await psdObject.arrayBuffer())) : null;
  const jpgWidth = Number(reference?.customMetadata?.width);
  const jpgHeight = Number(reference?.customMetadata?.height);
  if (!psd || psd.width !== width || psd.height !== height || !reference || jpgWidth !== psd.width || jpgHeight !== psd.height) {
    fail(422, 'PSD_JPG_SIZE_MISMATCH', 'PSD 与对应 JPG 的画布尺寸不一致。', {
      psd: { width, height },
      jpg: { width: jpgWidth || null, height: jpgHeight || null },
    });
  }
  if (
    raw.template.id !== original.id ||
    raw.template.productName !== original.productName ||
    raw.template.radio !== original.radio
  ) {
    fail(422, 'TEMPLATE_IDENTITY_MISMATCH', '解析结果不能改变原产品与 Radio 的关联。');
  }
  const availableLengths = lengthsForTemplate(original);
  if (
    !availableLengths.length || availableLengths.length > 20 ||
    availableLengths.some((value) => !Number.isInteger(value) || value < 1 || value > 100)
  ) fail(422, 'INVALID_AVAILABLE_LENGTHS', '解析到的尺寸列表无效。');

  const sections = raw.template.sections;
  if (!Array.isArray(sections) || sections.length > 12) fail(422, 'INVALID_SECTIONS', '母版分区数量无效。');
  const sectionKeys = new Set<string>();
  for (const section of sections) {
    if (
      !section || typeof section.key !== 'string' || typeof section.label !== 'string' ||
      !section.key || section.key !== section.key.trim() || section.key.length > 100 ||
      !section.label.trim() || section.label.trim().length > 120 || sectionKeys.has(section.key)
    ) {
      fail(422, 'INVALID_SECTIONS', '母版包含无效或重复分区。');
    }
    sectionKeys.add(section.key);
  }
  const colors = raw.colors;
  if (!colors.length || colors.length > 100) fail(422, 'INVALID_COLORS', '解析到的颜色数量无效。');
  const colorIds = new Set<string>();
  const colorCodes = new Set<string>();
  const colorsById = new Map<string, StockColor>();
  for (const color of colors) {
    if (
      !color || typeof color.id !== 'string' || typeof color.code !== 'string' || typeof color.image !== 'string' ||
      !color.id || color.id !== color.id.trim() || color.id.length > 120 ||
      !color.code.trim() || color.code.trim().length > 80 || color.image.length > 700 ||
      colorIds.has(color.id) || colorCodes.has(color.code.trim().toUpperCase())
    ) fail(422, 'INVALID_COLORS', '解析到的颜色编号无效或重复。');
    colorIds.add(color.id);
    colorCodes.add(color.code.trim().toUpperCase());
    colorsById.set(color.id, color);
    const expectedPrefix = `/api/template-source-assets/${encodeURIComponent(row.id)}/colors/`;
    if (!color.image.startsWith(expectedPrefix) || !color.image.endsWith('.png')) {
      fail(422, 'INVALID_COLOR_ASSET', '解析颜色没有绑定到这个源文件版本的素材。', { colorId: color.id });
    }
  }
  const allKnownColorIds = new Set([...CATALOG.colors.map((color) => color.id), ...colorIds]);
  const cards = raw.template.initialCards as SourceCard[];
  if (!Array.isArray(cards) || !cards.length || cards.length > 100) fail(422, 'INVALID_SOURCE_CARDS', '解析到的颜色条目数量无效。');
  const candidateIds = new Set<string>();
  const sourceEntryIds = new Set<string>();
  const matchedEntryIds = new Set<string>();
  const validatedCards: SourceCard[] = [];
  const currentMaster = await env.DB.prepare(`
    SELECT current_version_id AS currentVersionId FROM master_template_state WHERE template_id = ?
  `).bind(row.templateId).first<{ currentVersionId: string | null }>();
  const currentEntries = currentMaster?.currentVersionId
    ? await env.DB.prepare(`
        SELECT entry_id AS entryId, color_id AS colorId, section_key AS section
        FROM master_version_entries WHERE version_id = ?
      `).bind(currentMaster.currentVersionId).all<{ entryId: string; colorId: string; section: string | null }>()
    : { results: [] as Array<{ entryId: string; colorId: string; section: string | null }> };
  const currentEntriesById = new Map((currentEntries.results ?? []).map((entry) => [entry.entryId, entry]));
  for (const card of cards) {
    const sourceColor = colorsById.get(card.colorId);
    if (
      !card || typeof card.candidateId !== 'string' || !card.candidateId || card.candidateId.length > 120 || candidateIds.has(card.candidateId) ||
      typeof card.entryId !== 'string' || !card.entryId || card.entryId.length > 220 || sourceEntryIds.has(card.entryId) ||
      typeof card.colorId !== 'string' || card.colorId.length > 120 || !allKnownColorIds.has(card.colorId) || !sourceColor ||
      typeof card.colorCode !== 'string' || card.colorCode.trim().length > 80 || !canonicalColorCode(card.colorCode) ||
      canonicalColorCode(card.colorCode) !== canonicalColorCode(sourceColor.code) ||
      !Array.isArray(card.lengths) || !card.lengths.length ||
      card.lengths.some((value) => !Number.isInteger(Number(value)) || Number(value) < 1 || Number(value) > 100) ||
      new Set(card.lengths.map(Number)).size !== card.lengths.length ||
      !['exact', 'new', 'unresolved'].includes(card.matchState)
    ) fail(422, 'INVALID_SOURCE_CARD', '解析到的颜色条目不完整或重复。');
    candidateIds.add(card.candidateId);
    sourceEntryIds.add(card.entryId);
    if (card.section != null && !sectionKeys.has(card.section)) fail(422, 'INVALID_SOURCE_SECTION', '颜色条目指向了未知分区。');
    if (card.matchState === 'exact') {
      const existing = card.matchedEntryId ? currentEntriesById.get(card.matchedEntryId) : null;
      if (!existing || existing.colorId !== card.colorId || existing.section !== card.section || matchedEntryIds.has(existing.entryId)) {
        fail(422, 'INVALID_EXACT_MATCH', '自动对应的旧规格无效或重复。');
      }
      matchedEntryIds.add(existing.entryId);
    } else if (card.matchedEntryId) {
      fail(422, 'INVALID_NEW_MATCH', '新增或待确认颜色不能预先绑定旧规格。');
    }
    const swatch = cleanBounds(card.geometry?.swatch, width, height, `${card.colorCode} 色块`);
    const colorLabel = card.geometry?.colorLabel
      ? cleanBounds(card.geometry.colorLabel, width, height, `${card.colorCode} 色号文字`)
      : null;
    const sizeLabel = card.geometry?.sizeLabel
      ? cleanBounds(card.geometry.sizeLabel, width, height, `${card.colorCode} 尺寸文字`)
      : null;
    const hotBadge = card.geometry?.hotBadge
      ? cleanBounds(card.geometry.hotBadge, width, height, `${card.colorCode} Hot 标记`)
      : null;
    validatedCards.push({
      ...card,
      candidateId: card.candidateId,
      entryId: card.entryId,
      colorId: card.colorId,
      colorCode: card.colorCode.trim(),
      lengths: [...new Set(card.lengths.map(Number))].sort((a, b) => a - b),
      section: card.section,
      matchedEntryId: card.matchedEntryId,
      matchReason: typeof card.matchReason === 'string' ? card.matchReason.slice(0, 500) : '',
      geometry: { swatch, colorLabel, sizeLabel, hotBadge },
    });
  }
  const issues = raw.parseIssues;
  if (!Array.isArray(issues) || issues.length > 500 || issues.some((issue) => (
    !issue || typeof issue.code !== 'string' || typeof issue.message !== 'string' || typeof issue.blocking !== 'boolean' ||
    (issue.issueId != null && (typeof issue.issueId !== 'string' || !issue.issueId.trim() || issue.issueId.length > 160))
  ))) fail(422, 'INVALID_PARSE_ISSUES', '解析问题列表格式无效。');
  for (const issue of issues) sourceIssueDetails(issue.details);
  const issueIds = new Set<string>();
  const normalizedIssues = sourceReviewIssues(issues, validatedCards, CATALOG.colors, availableLengths).map((issue, index) => {
    const issueId = issue.issueId?.trim() || `issue-${index + 1}-${issue.code.slice(0, 60)}`;
    if (issueIds.has(issueId)) fail(422, 'DUPLICATE_PARSE_ISSUE', '解析问题编号重复，无法逐项确认。', { issueId });
    issueIds.add(issueId);
    return {
      issueId,
      code: issue.code.slice(0, 80),
      message: issue.message.slice(0, 500),
      candidateId: issue.candidateId?.slice(0, 120),
      blocking: issue.blocking,
      details: sourceIssueDetails(issue.details),
    };
  });
  const expectedBase = sourceAssetUrl(row.id, 'base.png');
  const expectedReference = sourceAssetUrl(row.id, 'reference.jpg');
  if (raw.template.baseUrl !== expectedBase || raw.template.referenceUrl !== expectedReference) {
    fail(422, 'INVALID_SOURCE_URLS', '母版底图或参考图没有绑定到这个源文件版本。');
  }
  if (raw.template.hotUrl && raw.template.hotUrl !== sourceAssetUrl(row.id, 'hot.png')) {
    fail(422, 'INVALID_HOT_ASSET', 'Hot 素材没有绑定到这个源文件版本。');
  }
  const dynamicBounds = cleanBounds(raw.template.dynamicBounds, width, height, '动态排版区域');
  const validated: SourceTemplateConfig = {
    schemaVersion: 1,
    template: {
      ...raw.template,
      id: original.id,
      productName: original.productName,
      radio: original.radio,
      width,
      height,
      sourcePsdName: row.sourcePsdName,
      referenceJpgName: row.referenceJpgName,
      sourceVersionId: row.id,
      dynamicBounds,
      availableLengths,
      sections: sections.map((section) => ({ key: section.key, label: section.label.trim() })),
      initialCards: validatedCards.map((card, order) => ({
        ...card,
        order,
        lengths: [...new Set(card.lengths.map(Number))].sort((a, b) => a - b),
        hot: Boolean(card.hot),
      })),
      warnings: normalizedIssues.map((issue) => issue.message),
      initialColorCount: cards.length,
    },
    colors: colors.map((color) => ({
      id: color.id,
      code: color.code.trim(),
      image: color.image,
      sourceVersionId: row.id,
    })),
    availableLengths,
    parseIssues: normalizedIssues,
    parseSummary: {
      layerCount: Math.max(0, Number(raw.parseSummary?.layerCount) || 0),
      parsedColorCount: validatedCards.length,
      parsedSpecCount: validatedCards.reduce((sum, card) => sum + card.lengths.length, 0),
      sectionCount: sections.length,
      documentWidth: width,
      documentHeight: height,
    },
  };
  return validated;
}

async function requireSourceAssets(row: StoredSourceVersion, config: SourceTemplateConfig) {
  const assets = new Set(['source.psd', 'reference.jpg', 'base.png', ...config.colors.map((color) => {
    const marker = `/api/template-source-assets/${encodeURIComponent(row.id)}/`;
    return decodeURIComponent(color.image.slice(marker.length));
  })]);
  if (config.template.hotUrl) assets.add('hot.png');
  const missing: string[] = [];
  const manifest: SourceAssetManifestItem[] = [];
  for (const asset of assets) {
    const fingerprint = await assetFingerprint(sourceObjectKey(row, asset), asset);
    if (!fingerprint) missing.push(asset);
    else manifest.push(fingerprint);
  }
  if (missing.length) fail(422, 'SOURCE_ASSETS_MISSING', '解析素材尚未全部上传。', { missing });
  return manifest;
}

export async function verifySourceVersionAssets(row: StoredSourceVersion) {
  const [psd, jpg] = await Promise.all([
    getFiles().head(row.sourcePsdKey),
    getFiles().head(row.referenceJpgKey),
  ]);
  if (!psd || !jpg || psd.size !== row.sourcePsdSize || jpg.size !== row.referenceJpgSize) {
    fail(409, 'SOURCE_FILES_CHANGED', '这个源文件版本的 PSD/JPG 缺失或大小发生变化，不能启用。');
  }
  const stored = parseJson<unknown>(row.assetManifestJson, []);
  if (!Array.isArray(stored)) return;
  const changed: string[] = [];
  for (const raw of stored) {
    if (typeof raw === 'string') {
      if (!(await assetFingerprint(sourceObjectKey(row, raw), raw))) changed.push(raw);
      continue;
    }
    if (!raw || typeof raw !== 'object') {
      changed.push('未知素材');
      continue;
    }
    const item = raw as Partial<SourceAssetManifestItem>;
    if (typeof item.name !== 'string' || typeof item.size !== 'number' || typeof item.sha256 !== 'string') {
      changed.push('未知素材');
      continue;
    }
    const current = await assetFingerprint(sourceObjectKey(row, item.name), item.name);
    if (!current || current.size !== item.size || current.sha256 !== item.sha256) changed.push(item.name);
  }
  if (changed.length) {
    fail(409, 'SOURCE_ASSETS_CHANGED', '解析后封存的素材发生缺失或变化，不能启用。请重新上传一个新版本。', { changed });
  }
}

async function currentMasterInput(templateId: string) {
  const state = await env.DB.prepare(`
    SELECT current_version_id AS currentVersionId FROM master_template_state WHERE template_id = ?
  `).bind(templateId).first<{ currentVersionId: string | null }>();
  if (!state?.currentVersionId) fail(409, 'MASTER_NOT_INITIALIZED', '当前标准母版尚未初始化。');
  const version = await env.DB.prepare(`
    SELECT source_version_id AS sourceVersionId FROM master_versions WHERE id = ? AND template_id = ?
  `).bind(state.currentVersionId, templateId).first<{ sourceVersionId: string | null }>();
  const entries = await env.DB.prepare(`
    SELECT entry_id AS entryId, color_id AS colorId, lengths_json AS lengthsJson,
      hot, section_key AS section, display_order AS "order"
    FROM master_version_entries WHERE version_id = ? ORDER BY display_order, entry_id
  `).bind(state.currentVersionId).all<{
    entryId: string; colorId: string; lengthsJson: string; hot: number; section: string | null; order: number;
  }>();
  const selection: Selection = (entries.results ?? []).map((entry) => ({
    entryId: entry.entryId,
    colorId: entry.colorId,
    lengths: parseJson<number[]>(entry.lengthsJson, []).map(Number),
    hot: Boolean(entry.hot),
    section: entry.section,
    order: entry.order,
  }));
  const context = await sourceContextForVersion(templateId, version?.sourceVersionId ?? null);
  return { masterVersionId: state.currentVersionId, selection, context };
}

export async function recordParsedSource(templateId: string, versionId: string, actor: AuthorizedUser, input: unknown) {
  const row = await readSourceVersion(templateId, versionId);
  if (!row) fail(404, 'SOURCE_VERSION_NOT_FOUND', '没有找到这个源文件版本。');
  if (row.status !== 'parsing') fail(409, 'SOURCE_VERSION_NOT_PARSING', '这个源文件版本不在可提交解析结果的状态。');
  const config = await validateParsedConfig(row, input);
  const assets = await requireSourceAssets(row, config);
  const current = await currentMasterInput(templateId);
  const diff = computeSourceChanges(current.context.template, current.context.colors, current.selection, config);
  const unresolved = [
    ...config.parseIssues.filter((issue) => issue.blocking),
    ...config.template.initialCards
      .filter((card) => card.matchState === 'unresolved')
      .map((card) => ({
        code: 'ENTRY_MAPPING_REQUIRED',
        message: `${card.colorCode} 无法可靠对应旧规格，请人工选择对应关系或确认为新增。`,
        candidateId: card.candidateId,
        blocking: true,
      })),
  ];
  const status: SourceVersionStatus = unresolved.length ? 'needs_review' : 'ready';
  const now = new Date().toISOString();
  const updated = await env.DB.prepare(`
    UPDATE template_source_versions
    SET status = ?, config_json = ?, asset_manifest_json = ?, diff_json = ?,
      compared_master_version_id = ?,
      unresolved_json = ?, failure_reason = NULL, updated_at = ?
    WHERE id = ? AND template_id = ? AND status = 'parsing'
  `).bind(
    status,
    JSON.stringify(config),
    JSON.stringify(assets),
    JSON.stringify(diff),
    current.masterVersionId,
    JSON.stringify(unresolved),
    now,
    row.id,
    row.templateId,
  ).run();
  if (!updated.meta.changes) fail(409, 'SOURCE_VERSION_CONFLICT', '源文件版本已被其他操作更新，请刷新后重试。');
  return getSourceVersionDetail(templateId, versionId, actor);
}

function publicSourceVersion(row: StoredSourceVersion, includeConfig = false): SourceVersionSummary {
  const unresolved = parseJson<SourceParseIssue[]>(row.unresolvedJson, []);
  return {
    id: row.id,
    templateId: row.templateId,
    number: row.versionNumber,
    basedOnSourceVersionId: row.basedOnSourceVersionId,
    comparedMasterVersionId: row.comparedMasterVersionId,
    status: row.status,
    psdName: row.sourcePsdName,
    jpgName: row.referenceJpgName,
    psdSize: row.sourcePsdSize,
    jpgSize: row.referenceJpgSize,
    createdBy: { id: row.createdByUserId, email: row.createdByEmail, displayName: row.createdByDisplayName },
    createdAt: row.createdAt,
    updatedAt: row.updatedAt,
    activatedAt: row.activatedAt,
    failureReason: row.failureReason,
    unresolvedCount: unresolved.length,
    diff: parseJson(row.diffJson, null),
    ...(includeConfig ? { config: row.configJson ? sourceVersionConfig(row) : null } : {}),
  };
}

export async function listSourceVersions(templateId: string, _actor: AuthorizedUser) {
  const template = requireTemplate(templateId);
  const { current } = await ensureSourceHistory(template.id);
  const result = await env.DB.prepare(`
    SELECT id, template_id AS templateId, version_number AS versionNumber,
      based_on_source_version_id AS basedOnSourceVersionId,
      compared_master_version_id AS comparedMasterVersionId, status,
      source_psd_key AS sourcePsdKey, reference_jpg_key AS referenceJpgKey,
      source_psd_name AS sourcePsdName, reference_jpg_name AS referenceJpgName,
      source_psd_size AS sourcePsdSize, reference_jpg_size AS referenceJpgSize,
      config_json AS configJson, asset_manifest_json AS assetManifestJson,
      diff_json AS diffJson, unresolved_json AS unresolvedJson, failure_reason AS failureReason,
      created_by_user_id AS createdByUserId, created_by_email AS createdByEmail,
      created_by_display_name AS createdByDisplayName, created_at AS createdAt,
      updated_at AS updatedAt, activated_at AS activatedAt
    FROM template_source_versions WHERE template_id = ?
    ORDER BY version_number DESC LIMIT 50
  `).bind(template.id).all<StoredSourceVersion>();
  return {
    templateId: template.id,
    currentVersionId: current?.id ?? null,
    versions: (result.results ?? []).map((row) => publicSourceVersion(row)),
  };
}

export async function getSourceVersionDetail(templateId: string, versionId: string, _actor: AuthorizedUser) {
  requireTemplate(templateId);
  const row = await readSourceVersion(templateId, versionId);
  if (!row) fail(404, 'SOURCE_VERSION_NOT_FOUND', '没有找到这个源文件版本。');
  return publicSourceVersion(row, true);
}

export async function markSourceFailed(
  templateId: string,
  versionId: string,
  actor: AuthorizedUser,
  reason: unknown,
) {
  const row = await readSourceVersion(templateId, versionId);
  if (!row) fail(404, 'SOURCE_VERSION_NOT_FOUND', '没有找到这个源文件版本。');
  if (row.status === 'active' || row.status === 'superseded') {
    fail(409, 'SOURCE_VERSION_IMMUTABLE', '已启用的源文件版本不能标记为解析失败。');
  }
  const message = typeof reason === 'string' && reason.trim()
    ? reason.trim().slice(0, 500)
    : 'PSD 结构无法可靠解析。';
  const updated = await env.DB.prepare(`
    UPDATE template_source_versions SET status = 'failed', failure_reason = ?, updated_at = ?
    WHERE id = ? AND template_id = ? AND status NOT IN ('active', 'superseded')
  `).bind(message, new Date().toISOString(), row.id, row.templateId).run();
  if (!updated.meta.changes) fail(409, 'SOURCE_VERSION_CONFLICT', '源文件版本已被其他操作更新，请刷新后重试。');
  return { sourceVersion: publicSourceVersion({ ...row, status: 'failed', failureReason: message, updatedAt: new Date().toISOString() }), actor: actor.displayName };
}

export async function mayReadSourceAsset(row: StoredSourceVersion, actor: AuthorizedUser) {
  if (actor.role === 'admin') return true;
  if (row.status !== 'active') return false;
  const current = await env.DB.prepare(`
    SELECT source.current_version_id AS sourceVersionId
    FROM template_source_state source WHERE source.template_id = ?
  `).bind(row.templateId).first<{ sourceVersionId: string | null }>();
  return current?.sourceVersionId === row.id;
}

export function sourceVersionConfig(row: StoredSourceVersion) {
  const config = parseJson<SourceTemplateConfig | null>(row.configJson, null);
  if (!config) fail(500, 'SOURCE_CONFIG_MISSING', '源文件版本配置不存在。');
  const allowedLengths = lengthsForTemplate(requireTemplate(row.templateId));
  return {
    ...config,
    availableLengths: allowedLengths,
    template: { ...config.template, availableLengths: allowedLengths },
    parseIssues: sourceReviewIssues(config.parseIssues, config.template.initialCards, CATALOG.colors, allowedLengths),
  };
}
