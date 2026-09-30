ALTER TABLE `master_version_entries` ADD `kind` text DEFAULT 'stock' NOT NULL;--> statement-breakpoint

-- The imported header photo has no size label, sits above the stock grid, and
-- was assigned a synthetic 16-inch spec. Match all three facts and its source
-- identity so a genuine color with a missing label is never reclassified.
UPDATE master_version_entries
SET kind = 'display', lengths_json = '[]', hot = 0
WHERE rowid IN (
  SELECT e.rowid
  FROM master_version_entries e
  JOIN master_versions v ON v.id = e.version_id
  JOIN master_template_state m ON m.template_id = v.template_id AND m.current_version_id = v.id
  JOIN template_source_versions s ON s.id = v.source_version_id
  WHERE e.display_order = 0 AND e.lengths_json = '[16]'
    AND e.entry_id = json_extract(s.config_json, '$.template.initialCards[0].entryId')
    AND json_extract(s.config_json, '$.template.initialCards[0].colorCode') LIKE '#048A%'
    AND json_extract(s.config_json, '$.template.initialCards[0].geometry.sizeLabel') IS NULL
    AND json_extract(s.config_json, '$.template.initialCards[0].geometry.swatch[0]') > 800
    AND json_extract(s.config_json, '$.template.initialCards[0].geometry.swatch[1]') < 220
);--> statement-breakpoint

-- Remove only the current version's false spec association. Keep registry,
-- stored status, and historical versions for audit and rollback.
DELETE FROM master_version_specs
WHERE rowid IN (
  SELECT vs.rowid
  FROM master_version_specs vs
  JOIN master_versions v ON v.id = vs.version_id
  JOIN master_template_state m ON m.template_id = v.template_id AND m.current_version_id = v.id
  JOIN master_specs spec ON spec.id = vs.spec_id
  JOIN master_version_entries e ON e.version_id = v.id AND e.entry_id = spec.entry_id
  WHERE e.kind = 'display'
);--> statement-breakpoint

UPDATE template_source_versions
SET config_json = json_set(
  config_json,
  '$.template.initialCards[0].kind', 'display',
  '$.template.initialCards[0].lengths', json('[]'),
  '$.template.initialCards[0].hot', json('false'),
  '$.template.initialColorCount', json_extract(config_json, '$.template.initialColorCount') - 1,
  '$.parseSummary.parsedColorCount', json_extract(config_json, '$.parseSummary.parsedColorCount') - 1,
  '$.parseSummary.parsedSpecCount', json_extract(config_json, '$.parseSummary.parsedSpecCount') - 1
)
WHERE id IN (
  SELECT v.source_version_id
  FROM master_versions v
  JOIN master_template_state m ON m.template_id = v.template_id AND m.current_version_id = v.id
  JOIN master_version_entries e ON e.version_id = v.id
  WHERE e.kind = 'display'
);--> statement-breakpoint

UPDATE master_template_state
SET revision = revision + 1
WHERE current_version_id IN (
  SELECT version_id FROM master_version_entries WHERE kind = 'display'
);--> statement-breakpoint

UPDATE inventory_template_state
SET revision = revision + 1
WHERE template_id IN (
  SELECT m.template_id FROM master_template_state m
  JOIN master_version_entries e ON e.version_id = m.current_version_id
  WHERE e.kind = 'display'
);
