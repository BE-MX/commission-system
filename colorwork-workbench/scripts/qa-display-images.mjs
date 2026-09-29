import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { readFile } from 'node:fs/promises';

const db = new DatabaseSync(':memory:');
db.exec(`
  CREATE TABLE master_template_state (template_id TEXT PRIMARY KEY, revision INTEGER, current_version_id TEXT);
  CREATE TABLE inventory_template_state (template_id TEXT PRIMARY KEY, revision INTEGER);
  CREATE TABLE master_versions (id TEXT PRIMARY KEY, template_id TEXT, source_version_id TEXT);
  CREATE TABLE master_version_entries (version_id TEXT, entry_id TEXT, color_id TEXT, lengths_json TEXT, hot INTEGER, display_order INTEGER);
  CREATE TABLE master_specs (id TEXT PRIMARY KEY, entry_id TEXT);
  CREATE TABLE master_version_specs (version_id TEXT, spec_id TEXT);
  CREATE TABLE template_source_versions (id TEXT PRIMARY KEY, config_json TEXT);
`);

const displayEntry = 'source:photo:candidate-859';
const stockEntry = '20g-genius-weft-regular:0:color-1';
const sourceConfig = {
  template: {
    initialColorCount: 2,
    initialCards: [
      { entryId: displayEntry, colorCode: '#048A5346', lengths: [16], hot: false, order: 0,
        geometry: { swatch: [864, 56, 988, 180], sizeLabel: null }, image: '/photo.png' },
      { entryId: stockEntry, colorCode: '#1', lengths: [18, 22], hot: true, order: 1,
        geometry: { swatch: [30, 189, 167, 326], sizeLabel: [30, 340, 167, 360] }, image: '/stock.png' },
    ],
  },
  parseSummary: { parsedColorCount: 2, parsedSpecCount: 3 },
};
db.prepare('INSERT INTO template_source_versions VALUES (?, ?)').run('source-1', JSON.stringify(sourceConfig));
db.exec(`
  INSERT INTO master_template_state VALUES ('20g-genius-weft-regular', 4, 'version-1');
  INSERT INTO inventory_template_state VALUES ('20g-genius-weft-regular', 7);
  INSERT INTO master_versions VALUES ('version-1', '20g-genius-weft-regular', 'source-1');
  INSERT INTO master_version_entries VALUES ('version-1', 'source:photo:candidate-859', 'source-color-048a5346', '[16]', 0, 0);
  INSERT INTO master_version_entries VALUES ('version-1', '20g-genius-weft-regular:0:color-1', 'color-1', '[18,22]', 1, 1);
  INSERT INTO master_specs VALUES ('false-spec', 'source:photo:candidate-859');
  INSERT INTO master_specs VALUES ('real-spec', '20g-genius-weft-regular:0:color-1');
  INSERT INTO master_version_specs VALUES ('version-1', 'false-spec');
  INSERT INTO master_version_specs VALUES ('version-1', 'real-spec');
`);

const sql = await readFile(new URL('../drizzle/0009_display_images.sql', import.meta.url), 'utf8');
for (const statement of sql.split('--> statement-breakpoint')) {
  if (statement.trim()) db.exec(statement);
}

const display = db.prepare('SELECT * FROM master_version_entries WHERE entry_id = ?').get(displayEntry);
const stock = db.prepare('SELECT * FROM master_version_entries WHERE entry_id = ?').get(stockEntry);
const migrated = JSON.parse(db.prepare('SELECT config_json FROM template_source_versions WHERE id = ?').get('source-1').config_json);
assert.equal(display.kind, 'display');
assert.equal(display.lengths_json, '[]');
assert.equal(display.hot, 0);
assert.equal(display.display_order, 0);
assert.equal(stock.kind, 'stock');
assert.equal(stock.lengths_json, '[18,22]');
assert.equal(db.prepare('SELECT count(*) AS count FROM master_version_specs').get().count, 1);
assert.equal(db.prepare('SELECT count(*) AS count FROM master_specs').get().count, 2);
assert.equal(migrated.template.initialCards[0].image, '/photo.png');
assert.equal(migrated.template.initialCards[0].kind, 'display');
assert.deepEqual(migrated.template.initialCards[0].lengths, []);
assert.equal(migrated.template.initialColorCount, 1);
assert.equal(db.prepare('SELECT revision FROM master_template_state').get().revision, 5);
assert.equal(db.prepare('SELECT revision FROM inventory_template_state').get().revision, 8);
db.close();
console.log('display image migration: photo and order preserved; false spec removed; real stock unchanged');
