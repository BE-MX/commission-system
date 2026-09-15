export const RADIO_OPTIONS = [
  'Regular Double Drawn',
  'Super Double Drawn',
  'Ultra Double Drawn',
] as const;

export const LENGTHS = [16, 18, 20, 22, 24] as const;

export type RadioOption = (typeof RADIO_OPTIONS)[number];
export type StockColor = {
  id: string;
  code: string;
  image: string;
  legacy?: boolean;
  sourceVersionId?: string | null;
};
export type SelectionEntry = {
  entryId: string;
  colorId: string;
  lengths: number[];
  hot: boolean;
  section: string | null;
  order: number;
};
export type Selection = SelectionEntry[];
export type InitialCard = SelectionEntry & {
  candidateId?: string;
  colorCode: string;
  geometry?: {
    swatch: [number, number, number, number];
    colorLabel?: [number, number, number, number] | null;
    sizeLabel?: [number, number, number, number] | null;
    hotBadge?: [number, number, number, number] | null;
  };
};
export type TemplateSection = { key: string; label: string };
export type TemplateSummary = {
  id: string;
  productName: string;
  radio: RadioOption;
  width: number;
  height: number;
  initialColorCount: number;
  sourcePsdName: string;
  referenceJpgName: string;
  referenceUrl: string;
  baseUrl: string;
  hotUrl?: string;
  dynamicBounds: [number, number, number, number];
  availableLengths?: number[];
  sourceVersionId?: string | null;
  sections: TemplateSection[];
  initialCards: InitialCard[];
  legacyColors: StockColor[];
  warnings: string[];
};
export type RuntimeAsset = {
  key: string;
  relativePath: string;
  size: number;
  sha256: string;
  contentType: 'image/jpeg' | 'image/png';
};
export type CatalogData = {
  colors: StockColor[];
  templates: TemplateSummary[];
  runtimeAssets: RuntimeAsset[];
};

export function productNames(templates: TemplateSummary[]) {
  return [...new Set(templates.map((item) => item.productName))];
}

export function templateById(templates: TemplateSummary[], id: string) {
  return templates.find((item) => item.id === id) ?? templates[0];
}

export function templateFor(templates: TemplateSummary[], productName: string, radio: string) {
  return templates.find((item) => item.productName === productName && item.radio === radio) ??
    templates.find((item) => item.productName === productName) ?? templates[0];
}

export function radiosFor(templates: TemplateSummary[], productName: string) {
  return templates.filter((item) => item.productName === productName).map((item) => item.radio);
}

export function colorsForTemplate(colors: StockColor[], item: TemplateSummary) {
  const merged = new Map<string, StockColor>();
  for (const color of [...colors, ...item.legacyColors]) {
    if (!merged.has(color.id)) merged.set(color.id, color);
  }
  return [...merged.values()];
}

export function colorForId(colors: StockColor[], item: TemplateSummary, id: string) {
  return colorsForTemplate(colors, item).find((color) => color.id === id);
}

export function selectionForTemplate(colors: StockColor[], item: TemplateSummary): Selection {
  const selected: Selection = item.initialCards.map((card) => ({
    entryId: card.entryId,
    colorId: card.colorId,
    lengths: [...card.lengths],
    hot: card.hot,
    section: card.section,
    order: card.order,
  }));
  const presentColorIds = new Set(selected.map((entry) => entry.colorId));
  const defaultSection = item.sections.at(-1)?.key ?? null;
  colors.forEach((color, index) => {
    if (presentColorIds.has(color.id)) return;
    selected.push({
      entryId: `${item.id}:available:${color.id}`,
      colorId: color.id,
      lengths: [],
      hot: false,
      section: defaultSection,
      order: 1000 + index,
    });
  });
  return selected;
}

export function lengthsForTemplate(item: TemplateSummary) {
  const values = (item.availableLengths?.length ? item.availableLengths : LENGTHS)
    .map(Number)
    .filter((value) => Number.isInteger(value) && value > 0 && value <= 100);
  return [...new Set(values)].sort((a, b) => a - b);
}

export function normalizeSelection(colors: StockColor[], item: TemplateSummary, value: unknown): Selection {
  const fallback = selectionForTemplate(colors, item);
  const allowedLengths = lengthsForTemplate(item);
  if (!Array.isArray(value)) return fallback;
  const known = new Map(fallback.map((entry) => [entry.entryId, entry]));
  const seen = new Set<string>();
  for (const raw of value.slice(0, fallback.length)) {
    if (!raw || typeof raw !== 'object') continue;
    const input = raw as Record<string, unknown>;
    const entryId = typeof input.entryId === 'string' ? input.entryId : '';
    const target = known.get(entryId);
    if (!target || seen.has(entryId)) continue;
    seen.add(entryId);
    const lengths = Array.isArray(input.lengths)
      ? input.lengths.map(Number).filter((size) => allowedLengths.includes(size))
      : [];
    target.lengths = [...new Set(lengths)].sort((a, b) => a - b);
    target.hot = Boolean(input.hot);
    target.section = typeof input.section === 'string' && item.sections.some((section) => section.key === input.section)
      ? input.section
      : item.sections.at(-1)?.key ?? null;
    target.order = Number.isFinite(Number(input.order)) ? Number(input.order) : target.order;
  }
  return fallback;
}

/**
 * Hydrates an administrator master snapshot into the complete editor list.
 * Unlike normalizeSelection(), entries omitted from the snapshot stay disabled;
 * this is required after a color or size has been intentionally removed from a
 * current master.
 */
export function selectionFromMaster(colors: StockColor[], item: TemplateSummary, value: unknown): Selection {
  const allowedLengths = lengthsForTemplate(item);
  const editor = selectionForTemplate(colors, item).map((entry) => ({
    ...entry,
    lengths: [] as number[],
    hot: false,
  }));
  if (!Array.isArray(value)) return editor;
  const known = new Map(editor.map((entry) => [entry.entryId, entry]));
  const seen = new Set<string>();
  for (const raw of value.slice(0, editor.length)) {
    if (!raw || typeof raw !== 'object') continue;
    const input = raw as Record<string, unknown>;
    const entryId = typeof input.entryId === 'string' ? input.entryId : '';
    const target = known.get(entryId);
    if (!target || seen.has(entryId)) continue;
    seen.add(entryId);
    const lengths = Array.isArray(input.lengths)
      ? input.lengths.map(Number).filter((size) => allowedLengths.includes(size))
      : [];
    target.lengths = [...new Set(lengths)].sort((a, b) => a - b);
    target.hot = Boolean(input.hot) && target.lengths.length > 0;
    target.section = typeof input.section === 'string' && item.sections.some((section) => section.key === input.section)
      ? input.section
      : item.sections.at(-1)?.key ?? null;
    target.order = Number.isFinite(Number(input.order)) ? Number(input.order) : target.order;
  }
  return editor;
}

export function activeMasterSelection(selection: Selection): Selection {
  return selection
    .filter((entry) => entry.lengths.length > 0)
    .map((entry) => ({
      ...entry,
      lengths: [...new Set(entry.lengths)].sort((a, b) => a - b),
      hot: Boolean(entry.hot),
    }))
    .sort((a, b) => a.order - b.order || a.entryId.localeCompare(b.entryId));
}

export function defaultSizesForTemplate(item: TemplateSummary) {
  const counts = new Map<string, { values: number[]; count: number }>();
  item.initialCards.forEach((card) => {
    const values = [...card.lengths].sort((a, b) => a - b);
    const key = values.join(',');
    counts.set(key, { values, count: (counts.get(key)?.count ?? 0) + 1 });
  });
  return [...counts.values()].sort((a, b) => b.count - a.count)[0]?.values ?? [18, 22];
}
