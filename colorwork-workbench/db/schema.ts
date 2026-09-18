import { index, integer, primaryKey, sqliteTable, text, uniqueIndex } from 'drizzle-orm/sqlite-core';

export const allowedAccounts = sqliteTable('allowed_accounts', {
  email: text('email').primaryKey(),
  displayName: text('display_name').notNull(),
  role: text('role', { enum: ['admin', 'member'] }).notNull().default('member'),
  enabled: integer('enabled', { mode: 'boolean' }).notNull().default(true),
  addedBy: text('added_by'),
  createdAt: text('created_at').notNull(),
  updatedAt: text('updated_at').notNull(),
});

export const users = sqliteTable('users', {
  id: text('id').primaryKey(),
  email: text('email').notNull(),
  displayName: text('display_name').notNull(),
  role: text('role', { enum: ['admin', 'member'] }).notNull(),
  lastSeenAt: text('last_seen_at').notNull(),
  createdAt: text('created_at').notNull(),
}, (table) => [
  uniqueIndex('idx_users_email').on(table.email),
]);

/** Local username sessions used when the workbench is opened outside ChatGPT. */
export const localSessions = sqliteTable('local_sessions', {
  token: text('token').primaryKey(),
  username: text('username').notNull(),
  createdAt: text('created_at').notNull(),
  expiresAt: text('expires_at').notNull(),
  /** 方舟 SSO 下发的可见视图清单（JSON 数组，如 ["library","inventory"]）；空/NULL 兼容旧会话：按角色推导（admin=全部，member=下载+修改）。 */
  viewsJson: text('views_json'),
}, (table) => [
  index('idx_local_sessions_expires').on(table.expiresAt),
  index('idx_local_sessions_username').on(table.username),
]);

export const artifacts = sqliteTable('artifacts', {
  id: text('id').primaryKey(),
  ownerUserId: text('owner_user_id').notNull(),
  ownerEmail: text('owner_email').notNull(),
  ownerDisplayName: text('owner_display_name').notNull(),
  sourceTemplateId: text('source_template_id').notNull(),
  sourceArtifactId: text('source_artifact_id'),
  name: text('name').notNull(),
  configJson: text('config_json').notNull(),
  jpgKey: text('jpg_key').notNull(),
  psdKey: text('psd_key').notNull(),
  status: text('status', { enum: ['uploading', 'psd_uploading', 'ready', 'failed'] }).notNull().default('uploading'),
  jpgSize: integer('jpg_size').notNull().default(0),
  psdSize: integer('psd_size').notNull().default(0),
  createdAt: text('created_at').notNull(),
  updatedAt: text('updated_at').notNull(),
}, (table) => [
  index('idx_artifacts_owner_created').on(table.ownerUserId, table.createdAt),
  index('idx_artifacts_template_created').on(table.sourceTemplateId, table.createdAt),
]);

export const templateFiles = sqliteTable('template_files', {
  templateId: text('template_id').primaryKey(),
  sourcePsdKey: text('source_psd_key').notNull(),
  referenceJpgKey: text('reference_jpg_key').notNull(),
  sourcePsdName: text('source_psd_name').notNull(),
  referenceJpgName: text('reference_jpg_name').notNull(),
  importedBy: text('imported_by').notNull(),
  createdAt: text('created_at').notNull(),
  updatedAt: text('updated_at').notNull(),
});

export const templateSourceState = sqliteTable('template_source_state', {
  templateId: text('template_id').primaryKey(),
  revision: integer('revision').notNull().default(0),
  currentVersionId: text('current_version_id'),
  nextVersionNumber: integer('next_version_number').notNull().default(1),
  lastMutationId: text('last_mutation_id'),
  updatedByUserId: text('updated_by_user_id'),
  updatedByEmail: text('updated_by_email'),
  updatedByDisplayName: text('updated_by_display_name'),
  updatedAt: text('updated_at'),
});

export const templateSourceVersions = sqliteTable('template_source_versions', {
  id: text('id').primaryKey(),
  templateId: text('template_id').notNull(),
  versionNumber: integer('version_number').notNull(),
  basedOnSourceVersionId: text('based_on_source_version_id'),
  comparedMasterVersionId: text('compared_master_version_id'),
  status: text('status', {
    enum: ['uploading', 'parsing', 'needs_review', 'ready', 'active', 'superseded', 'failed'],
  }).notNull().default('uploading'),
  sourcePsdKey: text('source_psd_key').notNull(),
  referenceJpgKey: text('reference_jpg_key').notNull(),
  sourcePsdName: text('source_psd_name').notNull(),
  referenceJpgName: text('reference_jpg_name').notNull(),
  sourcePsdSize: integer('source_psd_size').notNull().default(0),
  referenceJpgSize: integer('reference_jpg_size').notNull().default(0),
  configJson: text('config_json'),
  assetManifestJson: text('asset_manifest_json').notNull().default('{}'),
  diffJson: text('diff_json'),
  unresolvedJson: text('unresolved_json').notNull().default('[]'),
  failureReason: text('failure_reason'),
  createdByUserId: text('created_by_user_id').notNull(),
  createdByEmail: text('created_by_email').notNull(),
  createdByDisplayName: text('created_by_display_name').notNull(),
  createdAt: text('created_at').notNull(),
  updatedAt: text('updated_at').notNull(),
  activatedAt: text('activated_at'),
}, (table) => [
  uniqueIndex('idx_template_source_versions_template_number').on(table.templateId, table.versionNumber),
  index('idx_template_source_versions_template_status').on(table.templateId, table.status),
  index('idx_template_source_versions_template_created').on(table.templateId, table.createdAt),
]);

export const runtimeAssets = sqliteTable('runtime_assets', {
  assetKey: text('asset_key').primaryKey(),
  sha256: text('sha256').notNull(),
  size: integer('size').notNull(),
  uploadedBy: text('uploaded_by').notNull(),
  updatedAt: text('updated_at').notNull(),
});

export const masterTemplateState = sqliteTable('master_template_state', {
  templateId: text('template_id').primaryKey(),
  revision: integer('revision').notNull().default(0),
  currentVersionId: text('current_version_id'),
  nextVersionNumber: integer('next_version_number').notNull().default(1),
  lastMutationId: text('last_mutation_id'),
  updatedByUserId: text('updated_by_user_id'),
  updatedByEmail: text('updated_by_email'),
  updatedByDisplayName: text('updated_by_display_name'),
  updatedAt: text('updated_at'),
});

export const masterVersions = sqliteTable('master_versions', {
  id: text('id').primaryKey(),
  templateId: text('template_id').notNull(),
  versionNumber: integer('version_number').notNull(),
  action: text('action', { enum: ['initial', 'update', 'restore', 'source_update'] }).notNull(),
  restoredFromVersionId: text('restored_from_version_id'),
  sourceVersionId: text('source_version_id'),
  note: text('note'),
  createdByUserId: text('created_by_user_id').notNull(),
  createdByEmail: text('created_by_email').notNull(),
  createdByDisplayName: text('created_by_display_name').notNull(),
  createdAt: text('created_at').notNull(),
}, (table) => [
  uniqueIndex('idx_master_versions_template_number').on(table.templateId, table.versionNumber),
  index('idx_master_versions_template_created').on(table.templateId, table.createdAt),
]);

export const masterVersionEntries = sqliteTable('master_version_entries', {
  versionId: text('version_id').notNull(),
  entryId: text('entry_id').notNull(),
  colorId: text('color_id').notNull(),
  lengthsJson: text('lengths_json').notNull(),
  hot: integer('hot', { mode: 'boolean' }).notNull().default(false),
  sectionKey: text('section_key'),
  displayOrder: integer('display_order').notNull(),
}, (table) => [
  primaryKey({ columns: [table.versionId, table.entryId] }),
  index('idx_master_version_entries_order').on(table.versionId, table.displayOrder),
]);

export const masterSpecs = sqliteTable('master_specs', {
  id: text('id').primaryKey(),
  businessKey: text('business_key').notNull(),
  templateId: text('template_id').notNull(),
  entryId: text('entry_id').notNull(),
  colorId: text('color_id').notNull(),
  length: integer('length').notNull(),
  createdByUserId: text('created_by_user_id').notNull(),
  createdByEmail: text('created_by_email').notNull(),
  createdAt: text('created_at').notNull(),
}, (table) => [
  uniqueIndex('idx_master_specs_business_key').on(table.businessKey),
  uniqueIndex('idx_master_specs_template_entry_length').on(table.templateId, table.entryId, table.length),
  index('idx_master_specs_template').on(table.templateId),
]);

export const masterVersionSpecs = sqliteTable('master_version_specs', {
  versionId: text('version_id').notNull(),
  specId: text('spec_id').notNull(),
  displayOrder: integer('display_order').notNull(),
  statusSnapshot: text('status_snapshot', { enum: ['normal', 'low_stock', 'out_of_stock', 'restocking'] }),
  statusUpdatedAt: text('status_updated_at'),
}, (table) => [
  primaryKey({ columns: [table.versionId, table.specId] }),
  index('idx_master_version_specs_order').on(table.versionId, table.displayOrder),
]);

export const inventoryTemplateState = sqliteTable('inventory_template_state', {
  templateId: text('template_id').primaryKey(),
  revision: integer('revision').notNull().default(0),
  lastMutationId: text('last_mutation_id'),
  updatedByUserId: text('updated_by_user_id'),
  updatedByEmail: text('updated_by_email'),
  updatedByDisplayName: text('updated_by_display_name'),
  updatedAt: text('updated_at'),
});

export const inventoryStates = sqliteTable('inventory_states', {
  specId: text('spec_id').primaryKey(),
  templateId: text('template_id').notNull(),
  status: text('status', { enum: ['normal', 'low_stock', 'out_of_stock', 'restocking'] }).notNull(),
  revision: integer('revision').notNull().default(1),
  updatedByUserId: text('updated_by_user_id').notNull(),
  updatedByEmail: text('updated_by_email').notNull(),
  updatedByDisplayName: text('updated_by_display_name').notNull(),
  updatedAt: text('updated_at').notNull(),
}, (table) => [
  index('idx_inventory_states_template').on(table.templateId),
]);

export const inventoryEvents = sqliteTable('inventory_events', {
  id: text('id').primaryKey(),
  templateId: text('template_id').notNull(),
  specId: text('spec_id').notNull(),
  eventType: text('event_type', { enum: ['status_change', 'activated', 'reactivated'] }).notNull(),
  fromStatus: text('from_status', { enum: ['normal', 'low_stock', 'out_of_stock', 'restocking'] }),
  toStatus: text('to_status', { enum: ['normal', 'low_stock', 'out_of_stock', 'restocking'] }).notNull(),
  inventoryRevision: integer('inventory_revision').notNull(),
  actorUserId: text('actor_user_id').notNull(),
  actorEmail: text('actor_email').notNull(),
  actorDisplayName: text('actor_display_name').notNull(),
  occurredAt: text('occurred_at').notNull(),
}, (table) => [
  index('idx_inventory_events_template_revision').on(table.templateId, table.inventoryRevision),
  index('idx_inventory_events_spec_time').on(table.specId, table.occurredAt),
]);
