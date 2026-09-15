import type { Selection, StockColor, TemplateSummary } from '@/lib/catalog';

export const INVENTORY_STATUSES = ['normal', 'out_of_stock', 'restocking'] as const;
export const INVENTORY_SELECTABLE_STATUSES = ['normal', 'restocking'] as const;
export type InventoryStatus = (typeof INVENTORY_STATUSES)[number];

export type ActorRef = { id: string; email: string; displayName: string };

export type InventorySpec = {
  specId: string;
  entryId: string;
  colorId: string;
  length: number;
  status: InventoryStatus;
  statusUpdatedBy: ActorRef | null;
  statusUpdatedAt: string | null;
};

export type MasterVersion = {
  id: string;
  number: number;
  note: string | null;
  action: 'initial' | 'update' | 'restore' | 'source_update';
  restoredFromVersionId: string | null;
  createdBy: ActorRef;
  createdAt: string;
  sourceVersionId: string | null;
  sourceVersionNumber: number | null;
};

export type SourceVersionRef = {
  id: string | null;
  number: number | null;
  status: 'static' | 'active' | 'superseded';
  psdName: string;
  jpgName: string;
};

export type TemplateState = {
  templateId: string;
  template: TemplateSummary;
  colors: StockColor[];
  availableLengths: number[];
  sourceVersion: SourceVersionRef;
  masterRevision: number;
  inventoryRevision: number;
  version: MasterVersion;
  selection: Selection;
  specs: InventorySpec[];
  inventoryUpdatedBy: ActorRef | null;
  inventoryUpdatedAt: string | null;
};

export type InventoryStatusMap = Record<string, Partial<Record<number, InventoryStatus>>>;

export const STATUS_LABELS: Record<InventoryStatus, string> = {
  normal: '到货正常',
  out_of_stock: '暂时缺货',
  restocking: '正在补货',
};

export const STATUS_IMAGE_LABELS: Record<Exclude<InventoryStatus, 'normal'>, string> = {
  out_of_stock: 'Temporarily Out of Stock',
  restocking: 'Restocking',
};

export function isInventoryStatus(value: unknown): value is InventoryStatus {
  return typeof value === 'string' && INVENTORY_STATUSES.includes(value as InventoryStatus);
}

export function statusMapForSpecs(specs: InventorySpec[]): InventoryStatusMap {
  const result: InventoryStatusMap = {};
  for (const spec of specs) {
    result[spec.entryId] ??= {};
    result[spec.entryId][spec.length] = spec.status;
  }
  return result;
}

export function statusFor(map: InventoryStatusMap, entryId: string, length: number): InventoryStatus {
  return map[entryId]?.[length] ?? 'normal';
}

export function specKey(entryId: string, length: number) {
  return `${entryId}\u001f${length}`;
}

export function specMap(specs: InventorySpec[]) {
  return new Map(specs.map((spec) => [specKey(spec.entryId, spec.length), spec]));
}

export function inventoryMapsEqual(a: InventoryStatusMap, b: InventoryStatusMap, selection: Selection) {
  return selection.every((entry) => entry.lengths.every((length) =>
    statusFor(a, entry.entryId, length) === statusFor(b, entry.entryId, length),
  ));
}
