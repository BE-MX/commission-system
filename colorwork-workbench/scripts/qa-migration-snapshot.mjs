import { DatabaseSync } from 'node:sqlite';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputPath = path.join(projectDir, 'outputs', 'qa-migration-snapshot.json');
const migration = await readFile(path.join(projectDir, 'drizzle', '0006_aberrant_vivisector.sql'), 'utf8');
const database = new DatabaseSync(':memory:');

function assert(condition, message, details) {
  if (!condition) throw new Error(`${message}${details === undefined ? '' : `：${JSON.stringify(details)}`}`);
}

database.exec(`
  CREATE TABLE template_source_versions (id TEXT PRIMARY KEY);
  CREATE TABLE master_versions (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    created_at TEXT NOT NULL
  );
  CREATE TABLE master_specs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
  CREATE TABLE master_version_specs (
    version_id TEXT NOT NULL,
    spec_id TEXT NOT NULL,
    status_snapshot TEXT,
    status_updated_at TEXT
  );
  CREATE TABLE inventory_states (spec_id TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at TEXT NOT NULL);
  CREATE TABLE inventory_events (
    spec_id TEXT NOT NULL,
    to_status TEXT NOT NULL,
    inventory_revision INTEGER NOT NULL,
    occurred_at TEXT NOT NULL
  );
  CREATE TABLE master_template_state (current_version_id TEXT);

  INSERT INTO master_versions VALUES
    ('v1', 'template-a', 1, '2026-01-03T00:00:00.000Z'),
    ('v2', 'template-a', 2, '2026-01-03T00:00:00.000Z');
  INSERT INTO master_specs VALUES ('spec-a', '2026-01-01T00:00:00.000Z');
  INSERT INTO master_version_specs VALUES ('v1', 'spec-a', NULL, NULL);
  INSERT INTO inventory_states VALUES ('spec-a', 'normal', '2026-01-03T00:00:00.000Z');
  INSERT INTO master_template_state VALUES ('v2');
  INSERT INTO inventory_events VALUES
    ('spec-a', 'normal', 1, '2026-01-01T00:00:00.000Z'),
    ('spec-a', 'restocking', 2, '2026-01-02T00:00:00.000Z'),
    ('spec-a', 'out_of_stock', 3, '2026-01-02T00:00:00.000Z'),
    ('spec-a', 'normal', 4, '2026-01-03T00:00:00.000Z');
`);
database.exec(migration);
const snapshot = database.prepare(`
  SELECT status_snapshot AS status, status_updated_at AS updatedAt
  FROM master_version_specs WHERE version_id = 'v1' AND spec_id = 'spec-a'
`).get();
const columns = database.prepare(`PRAGMA table_info(template_source_versions)`).all().map((row) => row.name);
assert(snapshot?.status === 'out_of_stock', '同毫秒下一版边界或事件 revision 排序错误', snapshot);
assert(snapshot?.updatedAt === '2026-01-02T00:00:00.000Z', '历史状态时间恢复错误', snapshot);
assert(columns.includes('based_on_source_version_id') && columns.includes('compared_master_version_id'), '源版本关联字段迁移缺失', columns);

const report = {
  passed: true,
  fixture: {
    v1CreatedAt: '2026-01-03T00:00:00.000Z',
    v2CreatedAt: '2026-01-03T00:00:00.000Z',
    sameTimestampEventRevisions: [2, 3],
    boundaryActivationRevision: 4,
  },
  snapshot,
  sourceVersionColumns: columns.filter((name) => name.endsWith('source_version_id')),
};
await mkdir(path.dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`);
database.close();
process.stdout.write(`${JSON.stringify({ passed: true, reportPath: outputPath, snapshot }, null, 2)}\n`);
