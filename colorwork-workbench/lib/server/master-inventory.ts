import { env } from 'cloudflare:workers';
import { serverTemplateById } from '@/lib/server/catalog';
import { applyArkInventoryOverlay } from '@/lib/server/ark-sync';
import {
  lengthsForTemplate,
  selectionForTemplate,
  type SelectionEntry,
  type StockColor,
  type TemplateSummary,
} from '@/lib/catalog';
import type { AuthorizedUser } from '@/lib/server/auth';
import {
  currentSourceContext,
  effectiveSourceColors,
  ensureSourceHistory,
  readSourceVersion,
  sourceContextForVersion,
  sourceVersionConfig,
  verifySourceVersionAssets,
  type StoredSourceVersion,
} from '@/lib/server/template-sources';
import { computeSourceChanges } from '@/lib/source-diff';
import type {
  SourceCard,
  SourceChangeSummary,
  SourceInitialStatus,
  SourceMappingDecision,
  SourceTemplateConfig,
} from '@/lib/source-versions';
import { sourceIssueKey } from '@/lib/source-versions';

export const INVENTORY_STATUSES = ['normal', 'out_of_stock', 'restocking'] as const;
export type InventoryStatus = (typeof INVENTORY_STATUSES)[number];

type SqlValue = string | number | null;
type VersionAction = 'initial' | 'update' | 'restore' | 'source_update';

type MasterStateRow = {
  templateId: string;
  revision: number;
  currentVersionId: string | null;
  nextVersionNumber: number;
};

type InventoryTemplateStateRow = {
  revision: number;
  updatedByUserId: string | null;
  updatedByEmail: string | null;
  updatedByDisplayName: string | null;
  updatedAt: string | null;
};

type VersionRow = {
  id: string;
  templateId: string;
  versionNumber: number;
  action: VersionAction;
  restoredFromVersionId: string | null;
  sourceVersionId: string | null;
  sourceVersionNumber: number | null;
  note: string | null;
  createdByUserId: string;
  createdByEmail: string;
  createdByDisplayName: string;
  createdAt: string;
};

type VersionEntryRow = {
  entryId: string;
  colorId: string;
  lengthsJson: string;
  hot: number;
  section: string | null;
  order: number;
};

type SpecRow = {
  specId: string;
  businessKey: string;
  templateId: string;
  entryId: string;
  colorId: string;
  length: number;
};

type InventoryRow = SpecRow & {
  order: number;
  status: InventoryStatus;
  statusRevision: number;
  updatedByUserId: string;
  updatedByEmail: string;
  updatedByDisplayName: string;
  updatedAt: string;
};

type InitialStatusInput = {
  entryId: string;
  length: number;
  status: InventoryStatus;
};

const SOURCE_IMPORT_ACTOR: AuthorizedUser = {
  id: 'system-source-import',
  email: 'system@inventory-workbench.local',
  displayName: '系统首次导入',
  role: 'admin',
  views: ['library', 'inventory', 'master'],
};

type NormalizedSelection = SelectionEntry & { colorId: string };

type DesiredSpec = {
  specId: string;
  businessKey: string;
  templateId: string;
  entryId: string;
  colorId: string;
  length: number;
  order: number;
  isNewRegistrySpec: boolean;
};

type SourceActivation = {
  row: StoredSourceVersion;
  expectedCurrentSourceVersionId: string;
  config?: SourceTemplateConfig;
  diff?: SourceChangeSummary;
};

export class MasterInventoryError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'MasterInventoryError';
  }
}

export function masterInventoryErrorResponse(error: unknown) {
  if (!(error instanceof MasterInventoryError)) return null;
  return Response.json(
    { error: error.message, code: error.code, ...(error.details ? { details: error.details } : {}) },
    {
      status: error.status,
      headers: { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' },
    },
  );
}

function fail(status: number, code: string, message: string, details?: Record<string, unknown>): never {
  throw new MasterInventoryError(status, code, message, details);
}

function requireTemplate(templateId: string) {
  const template = serverTemplateById(templateId);
  if (!template) fail(404, 'TEMPLATE_NOT_FOUND', '没有找到这个产品与 Radio 母版。');
  return template;
}

function cleanNote(value: unknown) {
  if (value == null) return null;
  if (typeof value !== 'string') fail(400, 'INVALID_NOTE', '版本说明格式无效。');
  const note = value.trim();
  return note ? note.slice(0, 500) : null;
}

function expectedRevision(value: unknown, field: string) {
  const revision = Number(value);
  if (!Number.isInteger(revision) || revision < 0) {
    fail(400, 'INVALID_REVISION', `${field} 必须是有效的非负整数。`);
  }
  return revision;
}

function expectedSourceVersion(value: unknown) {
  if (value === null) return null;
  if (typeof value !== 'string' || !value.trim()) {
    fail(400, 'INVALID_SOURCE_VERSION', '必须提交当前页面使用的源文件版本。');
  }
  return value.slice(0, 80);
}

function isInventoryStatus(value: unknown): value is InventoryStatus {
  return typeof value === 'string' && INVENTORY_STATUSES.includes(value as InventoryStatus);
}

function businessKey(templateId: string, entryId: string, length: number) {
  return JSON.stringify([templateId, entryId, length]);
}

function candidateSelection(template: TemplateSummary, colors: StockColor[]) {
  return selectionForTemplate(colors, template).map((entry) => ({ ...entry }));
}

function candidateMap(template: TemplateSummary, colors: StockColor[]) {
  return new Map(candidateSelection(template, colors).map((entry) => [entry.entryId, entry]));
}

function normalizedSelection(template: TemplateSummary, colors: StockColor[], value: unknown): NormalizedSelection[] {
  if (!Array.isArray(value)) fail(400, 'INVALID_SELECTION', '必须提交完整的母版规格。');
  const candidates = candidateMap(template, colors);
  const allowedLengths = lengthsForTemplate(template);
  if (value.length !== candidates.size) {
    fail(422, 'INCOMPLETE_SELECTION', '母版必须包含这个产品与 Radio 的全部颜色条目。', {
      expectedEntryCount: candidates.size,
      receivedEntryCount: value.length,
    });
  }

  const seen = new Set<string>();
  const selection = value.map((raw): NormalizedSelection => {
    if (!raw || typeof raw !== 'object') fail(400, 'INVALID_SELECTION', '母版条目格式无效。');
    const input = raw as Record<string, unknown>;
    const entryId = typeof input.entryId === 'string' ? input.entryId : '';
    const candidate = candidates.get(entryId);
    if (!candidate || seen.has(entryId)) {
      fail(422, 'INVALID_MASTER_ENTRY', '母版包含未知或重复的颜色条目。', { entryId });
    }
    seen.add(entryId);

    if (!Array.isArray(input.lengths) || input.lengths.length > allowedLengths.length) {
      fail(400, 'INVALID_LENGTHS', '尺寸列表格式无效。', { entryId });
    }
    const lengths = input.lengths.map(Number);
    if (
      lengths.some((length) => !Number.isInteger(length) || !allowedLengths.includes(length)) ||
      new Set(lengths).size !== lengths.length
    ) {
      fail(422, 'INVALID_LENGTHS', '母版只能使用当前源文件已定义的尺寸，且同一尺寸不能重复。', { entryId });
    }
    lengths.sort((a, b) => a - b);

    if (typeof input.hot !== 'boolean') fail(400, 'INVALID_HOT', 'Hot 状态必须明确提交。', { entryId });
    if (!lengths.length && input.hot) {
      fail(422, 'INACTIVE_HOT_ENTRY', '没有任何尺寸的颜色不能标记为 Hot。', { entryId });
    }

    const section = input.section == null ? null : typeof input.section === 'string' ? input.section : '__invalid__';
    if (
      (template.sections.length === 0 && section !== null) ||
      (template.sections.length > 0 && !template.sections.some((item) => item.key === section))
    ) {
      fail(422, 'INVALID_SECTION', '颜色条目使用了无效分区。', { entryId, section });
    }

    const order = Number(input.order);
    if (!Number.isInteger(order) || order < -100_000 || order > 100_000) {
      fail(400, 'INVALID_ORDER', '颜色条目排序值无效。', { entryId });
    }

    return {
      entryId,
      colorId: candidate.colorId,
      lengths,
      hot: input.hot,
      section,
      order,
    };
  });

  return selection.sort((a, b) => a.order - b.order || a.entryId.localeCompare(b.entryId));
}

function parseInitialStatuses(template: TemplateSummary, colors: StockColor[], value: unknown) {
  if (value == null) return new Map<string, InitialStatusInput>();
  const allowedLengths = lengthsForTemplate(template);
  if (!Array.isArray(value) || value.length > candidateMap(template, colors).size * allowedLengths.length) {
    fail(400, 'INVALID_INITIAL_STATUSES', '新增规格的初始库存状态格式无效。');
  }
  const candidates = candidateMap(template, colors);
  const result = new Map<string, InitialStatusInput>();
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') fail(400, 'INVALID_INITIAL_STATUSES', '新增规格的初始库存状态格式无效。');
    const input = raw as Record<string, unknown>;
    const entryId = typeof input.entryId === 'string' ? input.entryId : '';
    const length = Number(input.length);
    const status = input.status;
    if (
      !candidates.has(entryId) ||
      !Number.isInteger(length) ||
      !allowedLengths.includes(length) ||
      !isInventoryStatus(status)
    ) {
      fail(422, 'INVALID_INITIAL_STATUS_SPEC', '初始库存状态指向了无效规格。', { entryId, length });
    }
    const key = businessKey(template.id, entryId, length);
    if (result.has(key)) fail(400, 'DUPLICATE_INITIAL_STATUS', '同一新增规格不能重复提交初始库存状态。', { entryId, length });
    result.set(key, { entryId, length, status });
  }
  return result;
}

function validateExplicitInitialStatuses(
  additions: DesiredSpec[],
  statuses: Map<string, InitialStatusInput>,
) {
  const required = new Set(additions.map((spec) => spec.businessKey));
  const missing = additions
    .filter((spec) => !statuses.has(spec.businessKey))
    .map((spec) => ({ entryId: spec.entryId, length: spec.length }));
  const extra = [...statuses.entries()]
    .filter(([key]) => !required.has(key))
    .map(([, value]) => ({ entryId: value.entryId, length: value.length }));
  if (missing.length || extra.length) {
    fail(422, 'INITIAL_STATUS_MISMATCH', '每个本次新增或重新启用的规格都必须且只能提交一个初始库存状态。', { missing, extra });
  }
}

function guardMaster(templateId: string, mutationId: string) {
  return {
    sql: 'SELECT 1 FROM master_template_state WHERE template_id = ? AND last_mutation_id = ?',
    bindings: [templateId, mutationId] as SqlValue[],
  };
}

function guardInventory(templateId: string, mutationId: string) {
  return {
    sql: 'SELECT 1 FROM inventory_template_state WHERE template_id = ? AND last_mutation_id = ?',
    bindings: [templateId, mutationId] as SqlValue[],
  };
}

function conditionalInserts(
  table: string,
  columns: string[],
  rows: SqlValue[][],
  guard: { sql: string; bindings: SqlValue[] },
) {
  if (!rows.length) return [];
  const quoted = columns.map((column) => `\`${column}\``);
  const extracted = columns.map((column, index) => `json_extract(value, '$[${index}]') AS \`${column}\``);
  const sql = `
    WITH allowed AS (${guard.sql}), data AS (
      SELECT ${extracted.join(', ')} FROM json_each(?)
    )
    INSERT INTO \`${table}\` (${quoted.join(', ')})
    SELECT ${quoted.map((column) => `data.${column}`).join(', ')} FROM data CROSS JOIN allowed
  `;
  return [env.DB.prepare(sql).bind(...guard.bindings, JSON.stringify(rows))];
}

function conditionalInventoryUpdates(
  rows: Array<{ specId: string; status: InventoryStatus }>,
  actor: AuthorizedUser,
  now: string,
  guard: { sql: string; bindings: SqlValue[] },
) {
  if (!rows.length) return [];
  const data = rows.map((row) => [row.specId, row.status]);
  return [env.DB.prepare(`
    WITH allowed AS (${guard.sql}), data AS (
      SELECT json_extract(value, '$[0]') AS spec_id,
        json_extract(value, '$[1]') AS next_status
      FROM json_each(?)
    )
    UPDATE inventory_states
    SET status = (SELECT next_status FROM data WHERE data.spec_id = inventory_states.spec_id),
      revision = revision + 1,
      updated_by_user_id = ?, updated_by_email = ?, updated_by_display_name = ?, updated_at = ?
    WHERE spec_id IN (SELECT spec_id FROM data) AND EXISTS (SELECT 1 FROM allowed)
  `).bind(...guard.bindings, JSON.stringify(data), actor.id, actor.email, actor.displayName, now)];
}

function conditionalCurrentVersionSnapshotUpdates(
  versionId: string,
  rows: Array<{ specId: string; status: InventoryStatus }>,
  now: string,
  guard: { sql: string; bindings: SqlValue[] },
) {
  if (!rows.length) return [];
  const data = rows.map((row) => [row.specId, row.status]);
  return [env.DB.prepare(`
    WITH allowed AS (${guard.sql}), data AS (
      SELECT json_extract(value, '$[0]') AS spec_id,
        json_extract(value, '$[1]') AS next_status
      FROM json_each(?)
    )
    UPDATE master_version_specs
    SET status_snapshot = (SELECT next_status FROM data WHERE data.spec_id = master_version_specs.spec_id),
      status_updated_at = ?
    WHERE version_id = ? AND spec_id IN (SELECT spec_id FROM data)
      AND EXISTS (SELECT 1 FROM allowed)
  `).bind(...guard.bindings, JSON.stringify(data), now, versionId)];
}

async function readMasterState(templateId: string) {
  return env.DB.prepare(`
    SELECT template_id AS templateId, revision, current_version_id AS currentVersionId,
      next_version_number AS nextVersionNumber
    FROM master_template_state WHERE template_id = ?
  `).bind(templateId).first<MasterStateRow>();
}

async function readInventoryTemplateState(templateId: string) {
  return env.DB.prepare(`
    SELECT revision, updated_by_user_id AS updatedByUserId, updated_by_email AS updatedByEmail,
      updated_by_display_name AS updatedByDisplayName, updated_at AS updatedAt
    FROM inventory_template_state WHERE template_id = ?
  `).bind(templateId).first<InventoryTemplateStateRow>();
}

async function readVersion(versionId: string, templateId: string) {
  return env.DB.prepare(`
    SELECT v.id, v.template_id AS templateId, v.version_number AS versionNumber, v.action,
      v.restored_from_version_id AS restoredFromVersionId, v.source_version_id AS sourceVersionId,
      source.version_number AS sourceVersionNumber, v.note,
      v.created_by_user_id AS createdByUserId, v.created_by_email AS createdByEmail,
      v.created_by_display_name AS createdByDisplayName, v.created_at AS createdAt
    FROM master_versions v
    LEFT JOIN template_source_versions source ON source.id = v.source_version_id
    WHERE v.id = ? AND v.template_id = ?
  `).bind(versionId, templateId).first<VersionRow>();
}

async function readVersionSelection(versionId: string) {
  const result = await env.DB.prepare(`
    SELECT entry_id AS entryId, color_id AS colorId, lengths_json AS lengthsJson,
      hot, section_key AS section, display_order AS \`order\`
    FROM master_version_entries WHERE version_id = ?
    ORDER BY display_order, entry_id
  `).bind(versionId).all<VersionEntryRow>();
  return (result.results ?? []).map((row): NormalizedSelection => {
    let lengths: number[] = [];
    try {
      const parsed = JSON.parse(row.lengthsJson);
      if (Array.isArray(parsed)) lengths = parsed.map(Number);
    } catch {
      lengths = [];
    }
    return {
      entryId: row.entryId,
      colorId: row.colorId,
      lengths,
      hot: Boolean(row.hot),
      section: row.section,
      order: row.order,
    };
  });
}

async function readRegistry(templateId: string) {
  const result = await env.DB.prepare(`
    SELECT id AS specId, business_key AS businessKey, template_id AS templateId,
      entry_id AS entryId, color_id AS colorId, length
    FROM master_specs WHERE template_id = ?
  `).bind(templateId).all<SpecRow>();
  return result.results ?? [];
}

async function readStoredInventory(specIds: string[]) {
  if (!specIds.length) return [] as Array<{ specId: string; status: InventoryStatus }>;
  const result = await env.DB.prepare(`
    SELECT spec_id AS specId, status FROM inventory_states
    WHERE spec_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
  `).bind(JSON.stringify(specIds)).all<{ specId: string; status: InventoryStatus }>();
  return result.results ?? [];
}

async function readVersionSpecs(versionId: string, historical = false) {
  const result = await env.DB.prepare(`
    SELECT s.id AS specId, s.business_key AS businessKey, s.template_id AS templateId,
      s.entry_id AS entryId, s.color_id AS colorId, s.length,
      mvs.display_order AS \`order\`,
      ${historical ? 'COALESCE(mvs.status_snapshot, i.status)' : 'i.status'} AS status,
      i.revision AS statusRevision,
      i.updated_by_user_id AS updatedByUserId, i.updated_by_email AS updatedByEmail,
      i.updated_by_display_name AS updatedByDisplayName,
      ${historical ? 'COALESCE(mvs.status_updated_at, i.updated_at)' : 'i.updated_at'} AS updatedAt
    FROM master_version_specs mvs
    JOIN master_specs s ON s.id = mvs.spec_id
    JOIN inventory_states i ON i.spec_id = s.id
    WHERE mvs.version_id = ?
    ORDER BY mvs.display_order, s.id
  `).bind(versionId).all<InventoryRow>();
  return result.results ?? [];
}

function publicVersion(row: VersionRow) {
  return {
    id: row.id,
    number: row.versionNumber,
    action: row.action,
    restoredFromVersionId: row.restoredFromVersionId,
    note: row.note,
    createdBy: {
      id: row.createdByUserId,
      email: row.createdByEmail,
      displayName: row.createdByDisplayName,
    },
    createdAt: row.createdAt,
    sourceVersionId: row.sourceVersionId,
    sourceVersionNumber: row.sourceVersionNumber,
  };
}

function publicInventory(rows: InventoryRow[]) {
  return rows.map((row) => ({
    specId: row.specId,
    templateId: row.templateId,
    entryId: row.entryId,
    colorId: row.colorId,
    length: row.length,
    order: row.order,
    status: row.status,
    statusRevision: row.statusRevision,
    statusUpdatedBy: {
      id: row.updatedByUserId,
      email: row.updatedByEmail,
      displayName: row.updatedByDisplayName,
    },
    statusUpdatedAt: row.updatedAt,
  }));
}

function batchChanges(result: D1Result<unknown> | undefined) {
  return Number((result?.meta as { changes?: number } | undefined)?.changes ?? 0);
}

async function ensureTemplateStateRows(templateId: string) {
  await env.DB.batch([
    env.DB.prepare(`
      INSERT OR IGNORE INTO master_template_state (template_id, revision, next_version_number)
      VALUES (?, 0, 1)
    `).bind(templateId),
    env.DB.prepare(`
      INSERT OR IGNORE INTO inventory_template_state (template_id, revision)
      VALUES (?, 0)
    `).bind(templateId),
  ]);
}

async function commitVersion(args: {
  template: TemplateSummary;
  colors: StockColor[];
  actor: AuthorizedUser;
  expectedMasterRevision: number;
  selection: NormalizedSelection[];
  initialStatuses: Map<string, InitialStatusInput>;
  action: VersionAction;
  sourceVersionId: string | null;
  activateSource?: SourceActivation;
  restoredFromVersionId?: string | null;
  note?: string | null;
}) {
  const { template, actor, selection, initialStatuses, action } = args;
  const state = await readMasterState(template.id);
  const inventoryTemplateState = await readInventoryTemplateState(template.id);
  if (!state || !inventoryTemplateState) fail(500, 'STATE_MISSING', '母版状态尚未初始化。');
  if (state.revision !== args.expectedMasterRevision) {
    fail(409, 'MASTER_REVISION_CONFLICT', '母版已被其他人更新，请刷新后重试。', {
      expectedRevision: args.expectedMasterRevision,
      currentRevision: state.revision,
    });
  }

  const currentSpecs = state.currentVersionId ? await readVersionSpecs(state.currentVersionId) : [];
  const currentKeys = new Set(currentSpecs.map((spec) => spec.businessKey));
  const registry = await readRegistry(template.id);
  const registryByKey = new Map(registry.map((spec) => [spec.businessKey, spec]));

  let specOrder = 0;
  const desired: DesiredSpec[] = [];
  for (const entry of selection) {
    for (const length of entry.lengths) {
      const key = businessKey(template.id, entry.entryId, length);
      const registered = registryByKey.get(key);
      if (registered && registered.colorId !== entry.colorId) {
        fail(422, 'SPEC_IDENTITY_CONFLICT', '不能把不同色号强行映射到已有库存规格，请确认为新增颜色。', {
          entryId: entry.entryId,
          length,
          registeredColorId: registered.colorId,
          nextColorId: entry.colorId,
        });
      }
      desired.push({
        specId: registered?.specId ?? crypto.randomUUID(),
        businessKey: key,
        templateId: template.id,
        entryId: entry.entryId,
        colorId: entry.colorId,
        length,
        order: specOrder,
        isNewRegistrySpec: !registered,
      });
      specOrder += 1;
    }
  }
  if (!desired.length) fail(422, 'EMPTY_MASTER', '母版至少需要保留一个真实规格。');

  const additions = desired.filter((spec) => !currentKeys.has(spec.businessKey));
  validateExplicitInitialStatuses(additions, initialStatuses);

  const storedInventory = await readStoredInventory(desired.filter((spec) => !spec.isNewRegistrySpec).map((spec) => spec.specId));
  const storedInventoryBySpecId = new Map(storedInventory.map((spec) => [spec.specId, spec]));
  const currentByKey = new Map(currentSpecs.map((spec) => [spec.businessKey, spec]));
  for (const spec of desired) {
    if (!spec.isNewRegistrySpec && !storedInventoryBySpecId.has(spec.specId)) {
      fail(500, 'INVENTORY_STATE_MISSING', '已有规格缺少库存状态，无法安全建立新版本。', { specId: spec.specId });
    }
  }

  const mutationId = crypto.randomUUID();
  const inventoryMutationId = crypto.randomUUID();
  const versionId = crypto.randomUUID();
  const versionNumber = state.nextVersionNumber;
  const now = new Date().toISOString();
  const masterGuard = guardMaster(template.id, mutationId);
  const sourceGuardSql = args.activateSource
    ? `AND EXISTS (
        SELECT 1 FROM template_source_state source
        WHERE source.template_id = ? AND source.current_version_id = ?
      ) AND EXISTS (
        SELECT 1 FROM template_source_versions candidate
        WHERE candidate.template_id = ? AND candidate.id = ?
          AND candidate.status IN ('ready', 'needs_review', 'superseded', 'active')
      )`
    : '';
  const statements: D1PreparedStatement[] = [
    env.DB.prepare(`
      UPDATE master_template_state
      SET revision = revision + 1, current_version_id = ?, next_version_number = next_version_number + 1,
        last_mutation_id = ?, updated_by_user_id = ?, updated_by_email = ?,
        updated_by_display_name = ?, updated_at = ?
      WHERE template_id = ? AND revision = ?
        AND EXISTS (
          SELECT 1 FROM inventory_template_state WHERE template_id = ? AND revision = ?
        )
        ${sourceGuardSql}
    `).bind(
      versionId,
      mutationId,
      actor.id,
      actor.email,
      actor.displayName,
      now,
      template.id,
      args.expectedMasterRevision,
      template.id,
      inventoryTemplateState.revision,
      ...(args.activateSource
        ? [
            template.id,
            args.activateSource.expectedCurrentSourceVersionId,
            template.id,
            args.activateSource.row.id,
          ]
        : []),
    ),
  ];

  if (additions.length) {
    statements.push(env.DB.prepare(`
      UPDATE inventory_template_state
      SET revision = revision + 1, last_mutation_id = ?, updated_by_user_id = ?,
        updated_by_email = ?, updated_by_display_name = ?, updated_at = ?
      WHERE template_id = ? AND EXISTS (${masterGuard.sql})
    `).bind(
      inventoryMutationId,
      actor.id,
      actor.email,
      actor.displayName,
      now,
      template.id,
      ...masterGuard.bindings,
    ));
  }

  statements.push(...conditionalInserts(
    'master_versions',
    [
      'id', 'template_id', 'version_number', 'action', 'restored_from_version_id',
      'source_version_id', 'note', 'created_by_user_id', 'created_by_email',
      'created_by_display_name', 'created_at',
    ],
    [[
      versionId,
      template.id,
      versionNumber,
      action,
      args.restoredFromVersionId ?? null,
      args.sourceVersionId,
      args.note ?? null,
      actor.id,
      actor.email,
      actor.displayName,
      now,
    ]],
    masterGuard,
  ));

  const newRegistrySpecs = desired.filter((spec) => spec.isNewRegistrySpec);
  statements.push(...conditionalInserts(
    'master_specs',
    [
      'id', 'business_key', 'template_id', 'entry_id', 'color_id', 'length',
      'created_by_user_id', 'created_by_email', 'created_at',
    ],
    newRegistrySpecs.map((spec) => [
      spec.specId,
      spec.businessKey,
      spec.templateId,
      spec.entryId,
      spec.colorId,
      spec.length,
      actor.id,
      actor.email,
      now,
    ]),
    masterGuard,
  ));

  statements.push(...conditionalInserts(
    'master_version_entries',
    ['version_id', 'entry_id', 'color_id', 'lengths_json', 'hot', 'section_key', 'display_order'],
    selection.map((entry) => [
      versionId,
      entry.entryId,
      entry.colorId,
      JSON.stringify(entry.lengths),
      entry.hot ? 1 : 0,
      entry.section,
      entry.order,
    ]),
    masterGuard,
  ));

  statements.push(...conditionalInserts(
    'master_version_specs',
    ['version_id', 'spec_id', 'display_order', 'status_snapshot', 'status_updated_at'],
    desired.map((spec) => {
      const current = currentByKey.get(spec.businessKey);
      return [
        versionId,
        spec.specId,
        spec.order,
        current?.status ?? initialStatuses.get(spec.businessKey)!.status,
        current?.updatedAt ?? now,
      ];
    }),
    masterGuard,
  ));

  const newInventory = additions.filter((spec) => spec.isNewRegistrySpec);
  statements.push(...conditionalInserts(
    'inventory_states',
    [
      'spec_id', 'template_id', 'status', 'revision', 'updated_by_user_id',
      'updated_by_email', 'updated_by_display_name', 'updated_at',
    ],
    newInventory.map((spec) => [
      spec.specId,
      template.id,
      initialStatuses.get(spec.businessKey)!.status,
      1,
      actor.id,
      actor.email,
      actor.displayName,
      now,
    ]),
    masterGuard,
  ));

  const reactivated = additions.filter((spec) => !spec.isNewRegistrySpec);
  statements.push(...conditionalInventoryUpdates(
    reactivated.map((spec) => ({ specId: spec.specId, status: initialStatuses.get(spec.businessKey)!.status })),
    actor,
    now,
    masterGuard,
  ));

  if (additions.length && action !== 'initial') {
    const hiddenState = new Map(registry.map((spec) => [spec.specId, spec]));
    const priorStatus = new Map(storedInventory.map((row) => [row.specId, row.status]));
    const eventGuard = guardInventory(template.id, inventoryMutationId);
    statements.push(...conditionalInserts(
      'inventory_events',
      [
        'id', 'template_id', 'spec_id', 'event_type', 'from_status', 'to_status',
        'inventory_revision', 'actor_user_id', 'actor_email', 'actor_display_name', 'occurred_at',
      ],
      additions.map((spec) => [
        crypto.randomUUID(),
        template.id,
        spec.specId,
        hiddenState.has(spec.specId) ? 'reactivated' : 'activated',
        priorStatus.get(spec.specId) ?? null,
        initialStatuses.get(spec.businessKey)!.status,
        inventoryTemplateState.revision + 1,
        actor.id,
        actor.email,
        actor.displayName,
        now,
      ]),
      eventGuard,
    ));
  }

  if (args.activateSource) {
    const activation = args.activateSource;
    statements.push(
      env.DB.prepare(`
        UPDATE template_source_versions
        SET status = 'superseded', updated_at = ?
        WHERE template_id = ? AND status = 'active' AND id <> ?
          AND EXISTS (${masterGuard.sql})
      `).bind(now, template.id, activation.row.id, ...masterGuard.bindings),
      env.DB.prepare(`
        UPDATE template_source_versions
        SET status = 'active', activated_at = ?, updated_at = ?,
          config_json = COALESCE(?, config_json), diff_json = COALESCE(?, diff_json),
          unresolved_json = '[]', failure_reason = NULL
        WHERE template_id = ? AND id = ?
          AND status IN ('ready', 'needs_review', 'superseded', 'active')
          AND EXISTS (${masterGuard.sql})
      `).bind(
        now,
        now,
        activation.config ? JSON.stringify(activation.config) : null,
        activation.diff ? JSON.stringify(activation.diff) : null,
        template.id,
        activation.row.id,
        ...masterGuard.bindings,
      ),
      env.DB.prepare(`
        UPDATE template_source_state
        SET revision = revision + 1, current_version_id = ?, last_mutation_id = ?,
          updated_by_user_id = ?, updated_by_email = ?, updated_by_display_name = ?, updated_at = ?
        WHERE template_id = ? AND current_version_id = ? AND EXISTS (${masterGuard.sql})
      `).bind(
        activation.row.id,
        mutationId,
        actor.id,
        actor.email,
        actor.displayName,
        now,
        template.id,
        activation.expectedCurrentSourceVersionId,
        ...masterGuard.bindings,
      ),
      env.DB.prepare(`
        UPDATE template_files
        SET source_psd_key = ?, reference_jpg_key = ?, source_psd_name = ?,
          reference_jpg_name = ?, imported_by = ?, updated_at = ?
        WHERE template_id = ? AND EXISTS (${masterGuard.sql})
      `).bind(
        activation.row.sourcePsdKey,
        activation.row.referenceJpgKey,
        activation.row.sourcePsdName,
        activation.row.referenceJpgName,
        actor.email,
        now,
        template.id,
        ...masterGuard.bindings,
      ),
    );
  }

  const results = await env.DB.batch(statements);
  if (batchChanges(results[0]) !== 1) {
    const current = await readMasterState(template.id);
    fail(409, 'MASTER_REVISION_CONFLICT', '母版已被其他人更新，请刷新后重试。', {
      expectedRevision: args.expectedMasterRevision,
      currentRevision: current?.revision ?? null,
    });
  }

  return getCurrentSnapshot(template.id, actor, false);
}

async function ensureInitialized(templateId: string, _actor: AuthorizedUser) {
  const identity = requireTemplate(templateId);
  await ensureSourceHistory(identity.id);
  const context = await currentSourceContext(identity.id);
  const { template, colors } = context;
  await ensureTemplateStateRows(template.id);
  const state = await readMasterState(template.id);
  if (!state) fail(500, 'STATE_MISSING', '母版状态尚未初始化。');
  if (state.currentVersionId) return identity;
  if (state.revision !== 0) fail(500, 'INVALID_INITIAL_STATE', '母版初始状态不完整。');

  const selection = candidateSelection(template, colors).sort((a, b) => a.order - b.order || a.entryId.localeCompare(b.entryId));
  const initialStatuses = new Map<string, InitialStatusInput>();
  for (const entry of selection) {
    for (const length of entry.lengths) {
      initialStatuses.set(businessKey(template.id, entry.entryId, length), {
        entryId: entry.entryId,
        length,
        status: 'normal',
      });
    }
  }
  try {
    await commitVersion({
      template,
      colors,
      actor: SOURCE_IMPORT_ACTOR,
      expectedMasterRevision: 0,
      selection,
      initialStatuses,
      action: 'initial',
      sourceVersionId: context.sourceVersion.id,
      note: '按首次导入 JPG 建立初始母版',
    });
  } catch (error) {
    if (!(error instanceof MasterInventoryError) || error.code !== 'MASTER_REVISION_CONFLICT') throw error;
  }
  const initialized = await readMasterState(template.id);
  if (!initialized?.currentVersionId) fail(500, 'INITIALIZATION_FAILED', '母版初始化失败。');
  return identity;
}

export async function getCurrentSnapshot(templateId: string, actor: AuthorizedUser, initialize = true) {
  const identity = initialize ? await ensureInitialized(templateId, actor) : requireTemplate(templateId);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const [state, inventoryState] = await Promise.all([
      readMasterState(identity.id),
      readInventoryTemplateState(identity.id),
    ]);
    if (!state?.currentVersionId || !inventoryState) fail(500, 'STATE_MISSING', '母版状态尚未初始化。');
    const [version, selection, inventory] = await Promise.all([
      readVersion(state.currentVersionId, identity.id),
      readVersionSelection(state.currentVersionId),
      readVersionSpecs(state.currentVersionId),
    ]);
    if (!version) fail(500, 'VERSION_MISSING', '当前母版版本不存在。');
    const source = await sourceContextForVersion(identity.id, version.sourceVersionId);
    const [confirmedMaster, confirmedInventory] = await Promise.all([
      readMasterState(identity.id),
      readInventoryTemplateState(identity.id),
    ]);
    if (
      confirmedMaster?.revision !== state.revision ||
      confirmedMaster?.currentVersionId !== state.currentVersionId ||
      confirmedInventory?.revision !== inventoryState.revision
    ) continue;

    const specs = publicInventory(inventory);
    // 方舟 okki 实时库存覆盖：enable_count > 0 → 到货正常，否则正在补货；
    // 接口未配置/不可达或模板未配置映射时保持站内已保存状态（见 lib/server/ark-sync.ts）。
    await applyArkInventoryOverlay(identity.id, source.colors, source.template, specs);
    const inventoryUpdatedBy = inventoryState.updatedByUserId && inventoryState.updatedByEmail
      ? {
          id: inventoryState.updatedByUserId,
          email: inventoryState.updatedByEmail,
          displayName: inventoryState.updatedByDisplayName ?? inventoryState.updatedByEmail,
        }
      : null;
    return {
      templateId: identity.id,
      template: source.template,
      colors: source.colors,
      availableLengths: lengthsForTemplate(source.template),
      sourceVersion: source.sourceVersion,
      masterRevision: state.revision,
      inventoryRevision: inventoryState.revision,
      version: publicVersion(version),
      selection,
      specs,
      inventoryUpdatedBy,
      inventoryUpdatedAt: inventoryState.updatedAt,
      inventory: specs,
    };
  }
  fail(409, 'SNAPSHOT_CHANGED', '母版或库存正在更新，请刷新后重试。');
}

export async function listMasterVersions(templateId: string, actor: AuthorizedUser) {
  const template = await ensureInitialized(templateId, actor);
  const state = await readMasterState(template.id);
  const result = await env.DB.prepare(`
    SELECT v.id, v.template_id AS templateId, v.version_number AS versionNumber, v.action,
      v.restored_from_version_id AS restoredFromVersionId, v.source_version_id AS sourceVersionId,
      source.version_number AS sourceVersionNumber, v.note,
      v.created_by_user_id AS createdByUserId, v.created_by_email AS createdByEmail,
      v.created_by_display_name AS createdByDisplayName, v.created_at AS createdAt,
      COUNT(mvs.spec_id) AS specCount
    FROM master_versions v
    LEFT JOIN template_source_versions source ON source.id = v.source_version_id
    LEFT JOIN master_version_specs mvs ON mvs.version_id = v.id
    WHERE v.template_id = ?
    GROUP BY v.id
    ORDER BY v.version_number DESC
    LIMIT 100
  `).bind(template.id).all<VersionRow & { specCount: number }>();
  return {
    templateId: template.id,
    masterRevision: state?.revision ?? 0,
    currentVersionId: state?.currentVersionId ?? null,
    versions: (result.results ?? []).map((row) => ({
      ...publicVersion(row),
      specCount: Number(row.specCount),
      isCurrent: row.id === state?.currentVersionId,
    })),
  };
}

export async function getMasterVersion(templateId: string, versionId: string, actor: AuthorizedUser) {
  const identity = await ensureInitialized(templateId, actor);
  const version = await readVersion(versionId, identity.id);
  if (!version) fail(404, 'VERSION_NOT_FOUND', '没有找到这个母版版本。');
  const source = await sourceContextForVersion(identity.id, version.sourceVersionId);
  const [state, inventoryState, selection, inventory] = await Promise.all([
    readMasterState(identity.id),
    readInventoryTemplateState(identity.id),
    readVersionSelection(version.id),
    readVersionSpecs(version.id, true),
  ]);
  return {
    template: source.template,
    colors: source.colors,
    availableLengths: lengthsForTemplate(source.template),
    sourceVersion: source.sourceVersion,
    masterRevision: state?.revision ?? 0,
    inventoryRevision: inventoryState?.revision ?? 0,
    isCurrent: state?.currentVersionId === version.id,
    version: publicVersion(version),
    selection,
    inventory: publicInventory(inventory),
  };
}

export async function createMasterVersion(templateId: string, actor: AuthorizedUser, input: unknown) {
  const identity = await ensureInitialized(templateId, actor);
  const source = await currentSourceContext(identity.id);
  const { template, colors } = source;
  if (!input || typeof input !== 'object') fail(400, 'INVALID_REQUEST', '请求格式无效。');
  const body = input as Record<string, unknown>;
  return commitVersion({
    template,
    colors,
    actor,
    expectedMasterRevision: expectedRevision(body.expectedRevision, 'expectedRevision'),
    selection: normalizedSelection(template, colors, body.selection),
    initialStatuses: parseInitialStatuses(template, colors, body.initialStatuses),
    action: 'update',
    sourceVersionId: source.sourceVersion.id,
    note: cleanNote(body.note),
  });
}

export async function restoreMasterVersion(templateId: string, actor: AuthorizedUser, input: unknown) {
  const identity = await ensureInitialized(templateId, actor);
  if (!input || typeof input !== 'object') fail(400, 'INVALID_REQUEST', '请求格式无效。');
  const body = input as Record<string, unknown>;
  const versionId = typeof body.versionId === 'string' ? body.versionId.slice(0, 80) : '';
  if (!versionId) fail(400, 'INVALID_VERSION_ID', '请选择需要恢复的母版版本。');
  const target = await readVersion(versionId, identity.id);
  if (!target) fail(404, 'VERSION_NOT_FOUND', '没有找到需要恢复的母版版本。');
  const [targetSource, currentSource] = await Promise.all([
    sourceContextForVersion(identity.id, target.sourceVersionId),
    currentSourceContext(identity.id),
  ]);
  const targetSelection = normalizedSelection(
    targetSource.template,
    targetSource.colors,
    await readVersionSelection(target.id),
  );
  const activateSource = targetSource.row && currentSource.row && targetSource.row.id !== currentSource.row.id
    ? {
        row: targetSource.row,
        expectedCurrentSourceVersionId: currentSource.row.id,
      }
    : undefined;
  if (activateSource) await verifySourceVersionAssets(activateSource.row);
  return commitVersion({
    template: targetSource.template,
    colors: targetSource.colors,
    actor,
    expectedMasterRevision: expectedRevision(body.expectedRevision, 'expectedRevision'),
    selection: targetSelection,
    initialStatuses: parseInitialStatuses(targetSource.template, targetSource.colors, body.initialStatuses),
    action: 'restore',
    sourceVersionId: target.sourceVersionId,
    activateSource,
    restoredFromVersionId: target.id,
    note: cleanNote(body.note),
  });
}

function sourceDecisions(value: unknown) {
  if (value == null) return new Map<string, SourceMappingDecision>();
  if (!Array.isArray(value) || value.length > 100) {
    fail(400, 'INVALID_SOURCE_MAPPINGS', '人工映射格式无效。');
  }
  const result = new Map<string, SourceMappingDecision>();
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') fail(400, 'INVALID_SOURCE_MAPPINGS', '人工映射格式无效。');
    const item = raw as Record<string, unknown>;
    const candidateId = typeof item.candidateId === 'string' ? item.candidateId.slice(0, 120) : '';
    const entryId = item.entryId == null ? null : typeof item.entryId === 'string' ? item.entryId.slice(0, 220) : '__invalid__';
    const treatAsNew = item.treatAsNew === true;
    const ignore = item.ignore === true;
    const lengths = Array.isArray(item.lengths) ? [...new Set(item.lengths.map(Number))].sort((a, b) => a - b) : [];
    const section = item.section == null ? null : typeof item.section === 'string' ? item.section.slice(0, 100) : '__invalid__';
    if (
      !candidateId || result.has(candidateId) || (!ignore && !treatAsNew && !entryId) ||
      (!ignore && (!lengths.length || lengths.length > 20 || lengths.some((length) => !Number.isInteger(length) || length < 1 || length > 100))) ||
      (!ignore && section === '__invalid__') || entryId === '__invalid__'
    ) fail(422, 'INVALID_SOURCE_MAPPING', '人工映射包含无效或重复内容。', { candidateId });
    result.set(candidateId, {
      candidateId,
      entryId: ignore ? null : entryId,
      treatAsNew: ignore ? false : treatAsNew,
      ignore,
      lengths: ignore ? [] : lengths,
      section: ignore ? null : section,
    });
  }
  return result;
}

function sourceInitialStatuses(value: unknown) {
  if (!Array.isArray(value) || value.length > 2000) {
    fail(400, 'INVALID_SOURCE_INITIAL_STATUSES', '新增规格初始状态格式无效。');
  }
  const result = new Map<string, SourceInitialStatus>();
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') fail(400, 'INVALID_SOURCE_INITIAL_STATUSES', '新增规格初始状态格式无效。');
    const item = raw as Record<string, unknown>;
    const candidateId = typeof item.candidateId === 'string' ? item.candidateId.slice(0, 120) : '';
    const length = Number(item.length);
    const status = item.status;
    const key = `${candidateId}\u001f${length}`;
    if (!candidateId || !Number.isInteger(length) || length < 1 || length > 100 || !isInventoryStatus(status) || result.has(key)) {
      fail(422, 'INVALID_SOURCE_INITIAL_STATUS', '新增规格初始状态包含无效或重复内容。', { candidateId, length });
    }
    result.set(key, { candidateId, length, status });
  }
  return result;
}

export async function enableTemplateSourceVersion(
  templateId: string,
  versionId: string,
  actor: AuthorizedUser,
  input: unknown,
) {
  const identity = await ensureInitialized(templateId, actor);
  if (!input || typeof input !== 'object') fail(400, 'INVALID_REQUEST', '请求格式无效。');
  const body = input as Record<string, unknown>;
  const expectedMasterRevision = expectedRevision(body.expectedMasterRevision, 'expectedMasterRevision');
  const acknowledged = new Set(
    Array.isArray(body.acknowledgedIssues)
      ? body.acknowledgedIssues.filter((value): value is string => typeof value === 'string').map((value) => value.slice(0, 240))
      : [],
  );
  const decisions = sourceDecisions(body.mappings);
  const suppliedStatuses = sourceInitialStatuses(body.initialStatuses);
  const row = await readSourceVersion(identity.id, versionId);
  if (!row) fail(404, 'SOURCE_VERSION_NOT_FOUND', '没有找到需要启用的源文件版本。');
  if (row.status !== 'ready' && row.status !== 'needs_review') {
    fail(409, 'SOURCE_VERSION_NOT_REVIEWABLE', '这个源文件版本尚未完成解析与校验，不能启用。');
  }
  await verifySourceVersionAssets(row);

  const [masterState, currentSource] = await Promise.all([
    readMasterState(identity.id),
    currentSourceContext(identity.id),
  ]);
  if (!masterState?.currentVersionId || !currentSource.row) fail(500, 'STATE_MISSING', '当前母版或源文件版本状态不完整。');
  if (
    masterState.revision !== expectedMasterRevision ||
    row.basedOnSourceVersionId !== currentSource.row.id ||
    row.comparedMasterVersionId !== masterState.currentVersionId
  ) {
    fail(409, 'SOURCE_REVIEW_STALE', '审阅期间当前母版已发生变化，请重新上传或重新解析后再启用。', {
      expectedMasterRevision,
      currentMasterRevision: masterState.revision,
      basedOnSourceVersionId: row.basedOnSourceVersionId,
      currentSourceVersionId: currentSource.row.id,
      comparedMasterVersionId: row.comparedMasterVersionId,
      currentMasterVersionId: masterState.currentVersionId,
    });
  }

  const config = sourceVersionConfig(row);
  const blocking = config.parseIssues.filter((issue) => issue.blocking && !acknowledged.has(sourceIssueKey(issue)));
  if (blocking.length) {
    fail(422, 'SOURCE_ISSUES_NOT_ACKNOWLEDGED', '仍有无法可靠识别的内容需要管理员逐项确认。', {
      issues: blocking.map((issue) => ({ ...issue, key: sourceIssueKey(issue) })),
    });
  }

  const currentSelection = await readVersionSelection(masterState.currentVersionId);
  const currentByEntryId = new Map(currentSelection.map((entry) => [entry.entryId, entry]));
  const candidateIds = new Set(config.template.initialCards.map((card) => card.candidateId));
  const unknownMappings = [...decisions.keys()].filter((candidateId) => !candidateIds.has(candidateId));
  const unknownStatuses = [...suppliedStatuses.values()].filter((status) => !candidateIds.has(status.candidateId));
  if (unknownMappings.length || unknownStatuses.length) {
    fail(422, 'UNKNOWN_SOURCE_CANDIDATE', '人工确认指向了不存在的解析条目。', {
      unknownMappings,
      unknownStatuses: unknownStatuses.map((status) => status.candidateId),
    });
  }

  const seenEntryIds = new Set<string>();
  const cards: SourceCard[] = [];
  for (const card of config.template.initialCards) {
    const decision = decisions.get(card.candidateId);
    if (decision?.ignore) continue;
    if (!decision) {
      fail(422, 'SOURCE_MAPPING_REQUIRED', '无法可靠对应的颜色必须人工映射或明确确认为新增。', {
        candidateId: card.candidateId,
        colorCode: card.colorCode,
      });
    }
    const lengths = decision?.lengths ?? card.lengths;
    const section = decision ? decision.section : card.section;
    if (!lengths.length || lengths.length > 20 || lengths.some((length) => !Number.isInteger(length) || !lengthsForTemplate(identity).includes(length))) {
      fail(422, 'INVALID_SOURCE_LENGTHS', '只能使用目标产品旧母版 S1 允许的尺寸，请修改尺寸或排除该颜色。', { candidateId: card.candidateId });
    }
    if (
      (config.template.sections.length === 0 && section !== null) ||
      (config.template.sections.length > 0 && !config.template.sections.some((item) => item.key === section))
    ) fail(422, 'INVALID_SOURCE_SECTION', '人工确认的分区无效。', { candidateId: card.candidateId, section });

    const requestedExisting = decision && !decision.treatAsNew
      ? decision.entryId
      : !decision && card.matchState === 'exact'
        ? card.matchedEntryId
        : null;
    let entryId: string;
    let colorId = card.colorId;
    if (requestedExisting) {
      const existing = currentByEntryId.get(requestedExisting);
      if (!existing) fail(422, 'INVALID_SOURCE_ENTRY_MAPPING', '人工映射指向了当前母版中不存在的颜色。', { candidateId: card.candidateId, entryId: requestedExisting });
      if (existing.colorId !== card.colorId) {
        fail(422, 'SOURCE_COLOR_IDENTITY_CHANGED', '不同色号不能继承旧库存状态，请确认为新增颜色。', {
          candidateId: card.candidateId,
          entryId: requestedExisting,
        });
      }
      entryId = existing.entryId;
      colorId = existing.colorId;
    } else {
      entryId = `source:${row.id}:${card.candidateId}`;
    }
    if (seenEntryIds.has(entryId)) fail(422, 'DUPLICATE_SOURCE_ENTRY_MAPPING', '多个新版颜色不能映射到同一个旧颜色。', { entryId });
    seenEntryIds.add(entryId);
    cards.push({
      ...card,
      entryId,
      colorId,
      lengths: [...new Set(lengths)].sort((a, b) => a - b),
      section,
      order: cards.length,
      matchState: requestedExisting ? 'exact' as const : 'new' as const,
      matchedEntryId: requestedExisting,
      matchReason: requestedExisting ? '管理员确认保留旧规格身份' : '管理员确认作为新增规格',
    });
  }
  if (!cards.length) fail(422, 'EMPTY_SOURCE_TEMPLATE', '新版至少需要保留一个业务颜色条目。');

  const availableLengths = lengthsForTemplate(identity);
  const usedSections = new Set(cards.map((card) => card.section).filter((section): section is string => Boolean(section)));
  const sections = config.template.sections.filter((section) => usedSections.has(section.key));
  const usedColorIds = new Set(cards.map((card) => card.colorId));
  const finalConfig: SourceTemplateConfig = {
    ...config,
    colors: config.colors.filter((color) => usedColorIds.has(color.id)),
    availableLengths,
    template: {
      ...config.template,
      sourceVersionId: row.id,
      availableLengths,
      initialCards: cards,
      initialColorCount: cards.length,
      sections,
      warnings: config.parseIssues.map((issue) => issue.message),
    },
  };
  const colors = effectiveSourceColors(finalConfig);
  const selection = normalizedSelection(
    finalConfig.template,
    colors,
    candidateSelection(finalConfig.template, colors),
  );
  const translatedStatuses = new Map<string, InitialStatusInput>();
  for (const status of suppliedStatuses.values()) {
    const card = cards.find((candidate) => candidate.candidateId === status.candidateId);
    if (!card) {
      fail(422, 'INVALID_SOURCE_INITIAL_STATUS', '已忽略的颜色不能提交新增规格初始状态。', {
        candidateId: status.candidateId,
        length: status.length,
      });
    }
    if (!card.lengths.includes(status.length)) {
      fail(422, 'INVALID_SOURCE_INITIAL_STATUS', '初始状态指向了这个颜色未启用的尺寸。', {
        candidateId: status.candidateId,
        length: status.length,
      });
    }
    translatedStatuses.set(businessKey(identity.id, card.entryId, status.length), {
      entryId: card.entryId,
      length: status.length,
      status: status.status,
    });
  }
  const diff = computeSourceChanges(
    currentSource.template,
    currentSource.colors,
    currentSelection,
    finalConfig,
  );
  return commitVersion({
    template: finalConfig.template,
    colors,
    actor,
    expectedMasterRevision,
    selection,
    initialStatuses: translatedStatuses,
    action: 'source_update',
    sourceVersionId: row.id,
    activateSource: {
      row,
      expectedCurrentSourceVersionId: currentSource.row.id,
      config: finalConfig,
      diff,
    },
    note: cleanNote(body.note) ?? `启用源文件 S${row.versionNumber}`,
  });
}

export async function getInventorySnapshot(templateId: string, actor: AuthorizedUser) {
  return getCurrentSnapshot(templateId, actor);
}

export async function updateInventory(templateId: string, actor: AuthorizedUser, input: unknown) {
  const template = await ensureInitialized(templateId, actor);
  if (!input || typeof input !== 'object') fail(400, 'INVALID_REQUEST', '请求格式无效。');
  const body = input as Record<string, unknown>;
  const expectedMasterRevision = expectedRevision(body.expectedMasterRevision, 'expectedMasterRevision');
  const expectedInventoryRevision = expectedRevision(body.expectedInventoryRevision, 'expectedInventoryRevision');
  const expectedSourceVersionId = expectedSourceVersion(body.expectedSourceVersionId);
  if (!Array.isArray(body.updates) || !body.updates.length || body.updates.length > 2000) {
    fail(400, 'INVALID_UPDATES', '请提交 1 至 2000 个库存状态更新。');
  }

  const updates = body.updates.map((raw) => {
    if (!raw || typeof raw !== 'object') fail(400, 'INVALID_UPDATE', '库存状态更新格式无效。');
    const row = raw as Record<string, unknown>;
    const specId = typeof row.specId === 'string' ? row.specId.slice(0, 80) : '';
    if (!specId || !isInventoryStatus(row.status)) fail(400, 'INVALID_UPDATE', '规格 ID 或库存状态无效。');
    return { specId, status: row.status };
  });
  if (new Set(updates.map((row) => row.specId)).size !== updates.length) {
    fail(400, 'DUPLICATE_SPEC_UPDATE', '同一规格不能在一次请求中重复更新。');
  }

  const [masterState, inventoryState] = await Promise.all([
    readMasterState(template.id),
    readInventoryTemplateState(template.id),
  ]);
  if (!masterState?.currentVersionId || !inventoryState) fail(500, 'STATE_MISSING', '库存状态尚未初始化。');
  const currentVersion = await readVersion(masterState.currentVersionId, template.id);
  if (!currentVersion) fail(500, 'VERSION_MISSING', '当前母版版本不存在。');
  if (currentVersion.sourceVersionId !== expectedSourceVersionId) {
    fail(409, 'SOURCE_VERSION_CHANGED', '源文件版本已更新，本页旧配置不能保存，请刷新新版后重试。', {
      expectedSourceVersionId,
      currentSourceVersionId: currentVersion.sourceVersionId,
    });
  }
  if (masterState.revision !== expectedMasterRevision || inventoryState.revision !== expectedInventoryRevision) {
    fail(409, 'INVENTORY_REVISION_CONFLICT', '母版或库存状态已被其他人更新，请刷新后重试。', {
      expectedMasterRevision,
      currentMasterRevision: masterState.revision,
      expectedInventoryRevision,
      currentInventoryRevision: inventoryState.revision,
    });
  }

  const current = await readVersionSpecs(masterState.currentVersionId);
  const [confirmedMaster, confirmedInventory] = await Promise.all([
    readMasterState(template.id),
    readInventoryTemplateState(template.id),
  ]);
  if (
    confirmedMaster?.revision !== masterState.revision ||
    confirmedMaster?.currentVersionId !== masterState.currentVersionId ||
    confirmedInventory?.revision !== inventoryState.revision
  ) {
    fail(409, 'INVENTORY_REVISION_CONFLICT', '母版或库存状态已被其他人更新，请刷新后重试。', {
      expectedMasterRevision,
      currentMasterRevision: confirmedMaster?.revision ?? null,
      expectedInventoryRevision,
      currentInventoryRevision: confirmedInventory?.revision ?? null,
    });
  }
  const currentById = new Map(current.map((row) => [row.specId, row]));
  const invalidSpecIds = updates.filter((row) => !currentById.has(row.specId)).map((row) => row.specId);
  if (invalidSpecIds.length) {
    fail(422, 'SPEC_NOT_IN_CURRENT_MASTER', '只能更新当前母版中的真实规格。', { invalidSpecIds });
  }
  const changed = updates.filter((row) => currentById.get(row.specId)!.status !== row.status);
  if (!changed.length) return getInventorySnapshot(template.id, actor);

  const mutationId = crypto.randomUUID();
  const now = new Date().toISOString();
  const inventoryGuard = guardInventory(template.id, mutationId);
  const statements: D1PreparedStatement[] = [
    env.DB.prepare(`
      UPDATE inventory_template_state
      SET revision = revision + 1, last_mutation_id = ?, updated_by_user_id = ?,
        updated_by_email = ?, updated_by_display_name = ?, updated_at = ?
      WHERE template_id = ? AND revision = ?
        AND EXISTS (
          SELECT 1 FROM master_template_state
          WHERE template_id = ? AND revision = ? AND current_version_id = ?
        )
    `).bind(
      mutationId,
      actor.id,
      actor.email,
      actor.displayName,
      now,
      template.id,
      expectedInventoryRevision,
      template.id,
      expectedMasterRevision,
      masterState.currentVersionId,
    ),
    ...conditionalInventoryUpdates(changed, actor, now, inventoryGuard),
    ...conditionalCurrentVersionSnapshotUpdates(
      masterState.currentVersionId,
      changed,
      now,
      inventoryGuard,
    ),
    ...conditionalInserts(
      'inventory_events',
      [
        'id', 'template_id', 'spec_id', 'event_type', 'from_status', 'to_status',
        'inventory_revision', 'actor_user_id', 'actor_email', 'actor_display_name', 'occurred_at',
      ],
      changed.map((row) => [
        crypto.randomUUID(),
        template.id,
        row.specId,
        'status_change',
        currentById.get(row.specId)!.status,
        row.status,
        expectedInventoryRevision + 1,
        actor.id,
        actor.email,
        actor.displayName,
        now,
      ]),
      inventoryGuard,
    ),
  ];
  const results = await env.DB.batch(statements);
  if (batchChanges(results[0]) !== 1) {
    const [nextMaster, nextInventory] = await Promise.all([
      readMasterState(template.id),
      readInventoryTemplateState(template.id),
    ]);
    fail(409, 'INVENTORY_REVISION_CONFLICT', '母版或库存状态已被其他人更新，请刷新后重试。', {
      expectedMasterRevision,
      currentMasterRevision: nextMaster?.revision ?? null,
      expectedInventoryRevision,
      currentInventoryRevision: nextInventory?.revision ?? null,
    });
  }
  return getInventorySnapshot(template.id, actor);
}

export async function validateInventoryForGeneration(templateId: string, actor: AuthorizedUser, input: unknown) {
  const template = await ensureInitialized(templateId, actor);
  if (!input || typeof input !== 'object') fail(400, 'INVALID_REQUEST', '请求格式无效。');
  const body = input as Record<string, unknown>;
  const expectedMasterRevision = expectedRevision(body.expectedMasterRevision, 'expectedMasterRevision');
  const expectedInventoryRevision = expectedRevision(body.expectedInventoryRevision, 'expectedInventoryRevision');
  const expectedSourceVersionId = expectedSourceVersion(body.expectedSourceVersionId);
  if (!Array.isArray(body.specIds) || !body.specIds.length || body.specIds.length > 2000) {
    fail(400, 'INVALID_SPEC_IDS', '生成前必须提交 1 至 2000 个规格 ID。');
  }
  const specIds = body.specIds.map((value) => typeof value === 'string' ? value.slice(0, 80) : '');
  if (specIds.some((id) => !id) || new Set(specIds).size !== specIds.length) {
    fail(400, 'INVALID_SPEC_IDS', '生成规格 ID 无效或重复。');
  }

  const [masterState, inventoryState] = await Promise.all([
    readMasterState(template.id),
    readInventoryTemplateState(template.id),
  ]);
  if (!masterState?.currentVersionId || !inventoryState) fail(500, 'STATE_MISSING', '库存状态尚未初始化。');
  const currentVersion = await readVersion(masterState.currentVersionId, template.id);
  if (!currentVersion) fail(500, 'VERSION_MISSING', '当前母版版本不存在。');
  if (currentVersion.sourceVersionId !== expectedSourceVersionId) {
    fail(409, 'SOURCE_VERSION_CHANGED', '源文件版本已更新，本页旧配置不能导出，请刷新新版后重试。', {
      expectedSourceVersionId,
      currentSourceVersionId: currentVersion.sourceVersionId,
    });
  }
  if (masterState.revision !== expectedMasterRevision || inventoryState.revision !== expectedInventoryRevision) {
    fail(409, 'GENERATION_REVISION_CONFLICT', '生成前数据已发生变化，请刷新后重新确认。', {
      expectedMasterRevision,
      currentMasterRevision: masterState.revision,
      expectedInventoryRevision,
      currentInventoryRevision: inventoryState.revision,
    });
  }

  const current = await readVersionSpecs(masterState.currentVersionId);
  const [confirmedMaster, confirmedInventory] = await Promise.all([
    readMasterState(template.id),
    readInventoryTemplateState(template.id),
  ]);
  if (
    confirmedMaster?.revision !== masterState.revision ||
    confirmedMaster?.currentVersionId !== masterState.currentVersionId ||
    confirmedInventory?.revision !== inventoryState.revision
  ) {
    fail(409, 'GENERATION_REVISION_CONFLICT', '生成前数据已发生变化，请刷新后重新确认。', {
      expectedMasterRevision,
      currentMasterRevision: confirmedMaster?.revision ?? null,
      expectedInventoryRevision,
      currentInventoryRevision: confirmedInventory?.revision ?? null,
    });
  }
  const currentById = new Map(current.map((row) => [row.specId, row]));
  const invalidSpecIds = specIds.filter((id) => !currentById.has(id));
  if (invalidSpecIds.length) {
    fail(422, 'SPEC_NOT_IN_CURRENT_MASTER', '生成内容包含当前母版中不存在的规格。', { invalidSpecIds });
  }
  return {
    valid: true,
    templateId: template.id,
    masterRevision: masterState.revision,
    inventoryRevision: inventoryState.revision,
    versionId: masterState.currentVersionId,
    sourceVersionId: currentVersion.sourceVersionId,
    specs: publicInventory(specIds.map((id) => currentById.get(id)!)),
  };
}
