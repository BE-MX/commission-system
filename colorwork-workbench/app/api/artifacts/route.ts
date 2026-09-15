import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';
import {
  MasterInventoryError, getCurrentSnapshot, masterInventoryErrorResponse,
} from '@/lib/server/master-inventory';

type CreateArtifactInput = {
  name?: unknown;
  templateId?: unknown;
  expectedMasterRevision?: unknown;
  expectedInventoryRevision?: unknown;
  expectedSourceVersionId?: unknown;
};

function safeText(value: unknown, max: number) {
  return typeof value === 'string' ? value.trim().slice(0, max) : '';
}

function requestedRevision(value: unknown) {
  const revision = Number(value);
  return Number.isInteger(revision) && revision >= 0 ? revision : null;
}

export async function GET(request: Request) {
  try {
    const user = await requireView('library');
    const scope = new URL(request.url).searchParams.get('scope') === 'shared' ? 'shared' : 'mine';
    const query = scope === 'shared'
      ? env.DB.prepare(`
          SELECT id, name, source_template_id AS templateId,
            owner_display_name AS ownerName, created_at AS createdAt,
            jpg_size AS jpgSize, psd_size AS psdSize, config_json AS configJson
          FROM (
            SELECT a.*, ROW_NUMBER() OVER (
              PARTITION BY a.source_template_id ORDER BY a.created_at DESC, a.id DESC
            ) AS rowNumber
            FROM artifacts a
            WHERE a.status = 'ready'
          ) latest
          WHERE rowNumber = 1
          ORDER BY createdAt DESC
          LIMIT 200
        `)
      : env.DB.prepare(`
          SELECT id, name, source_template_id AS templateId,
            owner_display_name AS ownerName, created_at AS createdAt,
            jpg_size AS jpgSize, psd_size AS psdSize, config_json AS configJson
          FROM artifacts
          WHERE owner_user_id = ? AND status = 'ready'
          ORDER BY created_at DESC
          LIMIT 200
        `).bind(user.id);
    const result = await query.all<{
      id: string;
      name: string;
      templateId: string;
      ownerName: string;
      createdAt: string;
      jpgSize: number;
      psdSize: number;
      configJson: string;
    }>();
    type ArtifactConfig = {
      master?: { versionNumber?: number };
      inventory?: { revision?: number };
      sourceVersion?: { number?: number };
    };
    const artifacts = (result.results ?? []).map(({ configJson, ...artifact }) => {
      let config: ArtifactConfig | null = null;
      try { config = JSON.parse(configJson) as ArtifactConfig; } catch { config = null; }
      return {
        ...artifact,
        masterVersion: config?.master?.versionNumber,
        inventoryRevision: config?.inventory?.revision,
        sourceVersion: config?.sourceVersion?.number,
      };
    });
    return Response.json({ artifacts }, {
      headers: { 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' },
    });
  } catch (error) {
    return authErrorResponse(error);
  }
}

export async function POST(request: Request) {
  try {
    const user = await requireView('inventory');
    const pending = await env.DB.prepare(`
      SELECT COUNT(*) AS total FROM artifacts
      WHERE owner_user_id = ? AND status IN ('uploading', 'psd_uploading')
    `).bind(user.id).first<{ total: number }>();
    if ((pending?.total ?? 0) >= 3) {
      return Response.json({ error: '已有 3 个文件正在上传，请等待完成后再新建。' }, { status: 429 });
    }

    let input: CreateArtifactInput;
    try { input = await request.json<CreateArtifactInput>(); } catch {
      return Response.json({ error: '请求格式无效。' }, { status: 400 });
    }
    const name = safeText(input.name, 180);
    const templateId = safeText(input.templateId, 120);
    const expectedMasterRevision = requestedRevision(input.expectedMasterRevision);
    const expectedInventoryRevision = requestedRevision(input.expectedInventoryRevision);
    const expectedSourceVersionId = input.expectedSourceVersionId === null
      ? null
      : safeText(input.expectedSourceVersionId, 80);
    if (!name || !templateId || expectedMasterRevision == null || expectedInventoryRevision == null || (input.expectedSourceVersionId !== null && !expectedSourceVersionId)) {
      return Response.json({ error: '文件名、模板或版本信息不完整。' }, { status: 400 });
    }

    const snapshot = await getCurrentSnapshot(templateId, user);
    if (
      snapshot.masterRevision !== expectedMasterRevision ||
      snapshot.inventoryRevision !== expectedInventoryRevision ||
      snapshot.sourceVersion.id !== expectedSourceVersionId
    ) {
      return Response.json({
        error: '保存前母版或库存状态已发生变化，请刷新后重新生成。',
        code: 'ARTIFACT_REVISION_CONFLICT',
        details: {
          currentMasterRevision: snapshot.masterRevision,
          currentInventoryRevision: snapshot.inventoryRevision,
          currentSourceVersionId: snapshot.sourceVersion.id,
        },
      }, { status: 409 });
    }

    const id = crypto.randomUUID();
    const jpgKey = `artifacts/${user.id}/${id}/output.jpg`;
    const psdKey = `artifacts/${user.id}/${id}/source.psd`;
    const now = new Date().toISOString();
    const configJson = JSON.stringify({
      schemaVersion: 3,
      templateId,
      template: snapshot.template,
      colors: snapshot.colors,
      sourceVersion: snapshot.sourceVersion,
      master: {
        revision: snapshot.masterRevision,
        versionId: snapshot.version.id,
        versionNumber: snapshot.version.number,
        selection: snapshot.selection,
      },
      inventory: {
        revision: snapshot.inventoryRevision,
        specs: snapshot.specs,
        updatedBy: snapshot.inventoryUpdatedBy,
        updatedAt: snapshot.inventoryUpdatedAt,
      },
      generatedBy: { id: user.id, email: user.email, displayName: user.displayName },
      generatedAt: now,
    });
    const inserted = await env.DB.prepare(`
      INSERT INTO artifacts
        (id, owner_user_id, owner_email, owner_display_name, source_template_id,
         source_artifact_id, name, config_json, jpg_key, psd_key, status,
         jpg_size, psd_size, created_at, updated_at)
      SELECT ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, 'uploading', 0, 0, ?, ?
      WHERE EXISTS (
        SELECT 1
        FROM master_template_state master
        JOIN inventory_template_state inventory ON inventory.template_id = master.template_id
        WHERE master.template_id = ? AND master.revision = ?
          AND master.current_version_id = ? AND inventory.revision = ?
          AND EXISTS (
            SELECT 1 FROM master_versions version
            WHERE version.id = master.current_version_id
              AND version.source_version_id IS ?
          )
      )
    `).bind(
      id, user.id, user.email, user.displayName, templateId, name, configJson,
      jpgKey, psdKey, now, now, templateId, expectedMasterRevision,
      snapshot.version.id, expectedInventoryRevision, expectedSourceVersionId,
    ).run();
    if (!inserted.meta.changes) {
      const current = await env.DB.prepare(`
        SELECT master.revision AS masterRevision, inventory.revision AS inventoryRevision,
          version.source_version_id AS sourceVersionId
        FROM master_template_state master
        JOIN inventory_template_state inventory ON inventory.template_id = master.template_id
        JOIN master_versions version ON version.id = master.current_version_id
        WHERE master.template_id = ?
      `).bind(templateId).first<{ masterRevision: number; inventoryRevision: number; sourceVersionId: string | null }>();
      return Response.json({
        error: '保存时母版或库存状态刚刚发生变化，请刷新后重新生成。',
        code: 'ARTIFACT_REVISION_CONFLICT',
        details: {
          currentMasterRevision: current?.masterRevision ?? null,
          currentInventoryRevision: current?.inventoryRevision ?? null,
          currentSourceVersionId: current?.sourceVersionId ?? null,
        },
      }, { status: 409 });
    }

    return Response.json({
      artifact: { id, name, templateId, status: 'uploading' },
      upload: { jpg: `/api/artifacts/${id}/file/jpg`, finalize: `/api/artifacts/${id}` },
    }, { status: 201 });
  } catch (error) {
    if (error instanceof MasterInventoryError) return masterInventoryErrorResponse(error)!;
    return authErrorResponse(error);
  }
}
