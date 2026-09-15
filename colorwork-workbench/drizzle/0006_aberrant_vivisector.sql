ALTER TABLE `template_source_versions` ADD `based_on_source_version_id` text;--> statement-breakpoint
ALTER TABLE `template_source_versions` ADD `compared_master_version_id` text;--> statement-breakpoint
UPDATE `master_version_specs`
SET `status_snapshot` = (
  SELECT `inventory_states`.`status` FROM `inventory_states`
  WHERE `inventory_states`.`spec_id` = `master_version_specs`.`spec_id`
),
`status_updated_at` = (
  SELECT `inventory_states`.`updated_at` FROM `inventory_states`
  WHERE `inventory_states`.`spec_id` = `master_version_specs`.`spec_id`
)
WHERE `status_snapshot` IS NULL
  AND `version_id` IN (SELECT `current_version_id` FROM `master_template_state`);--> statement-breakpoint
UPDATE `master_version_specs`
SET `status_snapshot` = COALESCE((
  SELECT `inventory_events`.`to_status`
  FROM `inventory_events`
  JOIN `master_versions` AS `snapshot_version`
    ON `snapshot_version`.`id` = `master_version_specs`.`version_id`
  WHERE `inventory_events`.`spec_id` = `master_version_specs`.`spec_id`
    AND `inventory_events`.`occurred_at` < COALESCE((
      SELECT `next_version`.`created_at`
      FROM `master_versions` AS `next_version`
      WHERE `next_version`.`template_id` = `snapshot_version`.`template_id`
        AND `next_version`.`version_number` = (
          SELECT MIN(`later_version`.`version_number`)
          FROM `master_versions` AS `later_version`
          WHERE `later_version`.`template_id` = `snapshot_version`.`template_id`
            AND `later_version`.`version_number` > `snapshot_version`.`version_number`
        )
    ), '9999-12-31T23:59:59.999Z')
  ORDER BY `inventory_events`.`occurred_at` DESC, `inventory_events`.`inventory_revision` DESC
  LIMIT 1
), 'normal'),
`status_updated_at` = COALESCE((
  SELECT `inventory_events`.`occurred_at`
  FROM `inventory_events`
  JOIN `master_versions` AS `snapshot_version`
    ON `snapshot_version`.`id` = `master_version_specs`.`version_id`
  WHERE `inventory_events`.`spec_id` = `master_version_specs`.`spec_id`
    AND `inventory_events`.`occurred_at` < COALESCE((
      SELECT `next_version`.`created_at`
      FROM `master_versions` AS `next_version`
      WHERE `next_version`.`template_id` = `snapshot_version`.`template_id`
        AND `next_version`.`version_number` = (
          SELECT MIN(`later_version`.`version_number`)
          FROM `master_versions` AS `later_version`
          WHERE `later_version`.`template_id` = `snapshot_version`.`template_id`
            AND `later_version`.`version_number` > `snapshot_version`.`version_number`
        )
    ), '9999-12-31T23:59:59.999Z')
  ORDER BY `inventory_events`.`occurred_at` DESC, `inventory_events`.`inventory_revision` DESC
  LIMIT 1
), (
  SELECT `master_specs`.`created_at` FROM `master_specs`
  WHERE `master_specs`.`id` = `master_version_specs`.`spec_id`
))
WHERE `status_snapshot` IS NULL;
