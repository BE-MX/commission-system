import { workbenchUrl } from '@/lib/workbench-url';
import {
  colorForId,
  type Selection,
  type SelectionEntry,
  type StockColor,
  type TemplateSummary,
} from '@/lib/catalog';
import {
  drawInventoryOverlay,
  type InventoryStatusMap,
} from '@/lib/inventory-overlay';

export type ActiveColor = { color: StockColor; entry: SelectionEntry };
export type LayoutSlot = {
  x: number;
  y: number;
  size: number;
  codeSize: number;
  lengthSize: number;
  codeY: number;
  lengthY: number;
};

const imageCache = new Map<string, Promise<HTMLImageElement>>();

function loadImage(src: string): Promise<HTMLImageElement> {
  if (!imageCache.has(src)) {
    imageCache.set(
      src,
      new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => {
          imageCache.delete(src);
          reject(new Error(`素材加载失败：${src.split('/').pop()}`));
        };
        image.src = workbenchUrl(src);
      }),
    );
  }
  return imageCache.get(src)!;
}

export function activeColorsFor(
  colors: StockColor[],
  item: TemplateSummary,
  selection: Selection,
): ActiveColor[] {
  return selection
    .filter((entry) => entry.lengths.length)
    .map((entry) => ({ color: colorForId(colors, item, entry.colorId), entry }))
    .filter((value): value is ActiveColor => Boolean(value.color))
    .sort(
      (a, b) =>
        a.entry.order - b.entry.order ||
        a.color.code.localeCompare(b.color.code),
    );
}

function slotFromGeometry(
  card: TemplateSummary['initialCards'][number],
): LayoutSlot {
  const [left, top, right, bottom] = card.geometry!.swatch;
  const size = Math.min(right - left, bottom - top);
  const colorLabel = card.geometry!.colorLabel;
  const sizeLabel = card.geometry!.sizeLabel;
  const codeSize = colorLabel
    ? Math.max(12, Math.min(25, colorLabel[3] - colorLabel[1] + 2))
    : Math.max(12, Math.min(25, Math.round(size * 0.1)));
  const lengthSize = sizeLabel
    ? Math.max(12, Math.min(25, sizeLabel[3] - sizeLabel[1] + 2))
    : codeSize;
  return {
    x: left,
    y: top,
    size,
    codeSize,
    lengthSize,
    codeY: colorLabel ? (colorLabel[1] + colorLabel[3]) / 2 : bottom + 20,
    lengthY: sizeLabel ? (sizeLabel[1] + sizeLabel[3]) / 2 : bottom + 44,
  };
}

function exactSourceLayout(item: TemplateSummary, active: ActiveColor[]) {
  if (active.length !== item.initialCards.length) return null;
  const sourceByEntry = new Map(
    item.initialCards.map((card) => [card.entryId, card]),
  );
  const cards = active.map(({ entry }) => sourceByEntry.get(entry.entryId));
  if (cards.some((card) => !card?.geometry?.swatch)) return null;
  return cards.map((card) => slotFromGeometry(card!));
}

function layoutWithin(
  count: number,
  bounds: [number, number, number, number],
  maxColumns = 6,
): LayoutSlot[] {
  if (!Number.isInteger(count) || count < 1 || count > 40) return [];
  const [left, top, right, bottom] = bounds;
  const width = Math.max(1, right - left);
  const height = Math.max(1, bottom - top);
  let best: {
    columns: number;
    rows: number;
    size: number;
    labelHeight: number;
    gapX: number;
    gapY: number;
  } | null = null;

  for (let columns = 1; columns <= Math.min(maxColumns, count); columns += 1) {
    const rows = Math.ceil(count / columns);
    const labelHeight = columns >= 5 ? 44 : columns === 4 ? 50 : 62;
    const gapX = columns >= 5 ? 12 : 22;
    const gapY = columns >= 5 ? 10 : 20;
    const size = Math.floor(
      Math.min(
        count === 1 ? 390 : 330,
        (width - (columns - 1) * gapX) / columns,
        (height - rows * labelHeight - (rows - 1) * gapY) / rows,
      ),
    );
    if (size < 42) continue;
    const score = size - Math.abs(columns - rows) * 0.08;
    const bestScore = best
      ? best.size - Math.abs(best.columns - best.rows) * 0.08
      : -Infinity;
    if (score > bestScore)
      best = { columns, rows, size, labelHeight, gapX, gapY };
  }

  if (!best) return [];
  const blockHeight =
    best.rows * (best.size + best.labelHeight) + (best.rows - 1) * best.gapY;
  const startY = top + Math.max(0, (height - blockHeight) / 2);
  const codeSize = Math.max(12, Math.min(25, Math.round(best.size * 0.105)));
  const lengthSize = Math.max(12, Math.min(25, Math.round(best.size * 0.1)));

  return Array.from({ length: count }, (_, index) => {
    const row = Math.floor(index / best!.columns);
    const column = index % best!.columns;
    const rowCount = Math.min(best!.columns, count - row * best!.columns);
    const rowWidth = rowCount * best!.size + (rowCount - 1) * best!.gapX;
    const startX = left + (width - rowWidth) / 2;
    return {
      x: startX + column * (best!.size + best!.gapX),
      y: startY + row * (best!.size + best!.labelHeight + best!.gapY),
      size: best!.size,
      codeSize,
      lengthSize,
      codeY:
        startY +
        row * (best!.size + best!.labelHeight + best!.gapY) +
        best!.size +
        (codeSize >= 22 ? 24 : 20),
      lengthY:
        startY +
        row * (best!.size + best!.labelHeight + best!.gapY) +
        best!.size +
        (codeSize >= 22 ? 53 : 44),
    };
  });
}

function sectionLayout(item: TemplateSummary, active: ActiveColor[]) {
  if (!item.sections.length) return null;
  const slots = new Map<string, LayoutSlot[]>();
  for (const section of item.sections) {
    const sourceCards = item.initialCards.filter(
      (card) => card.section === section.key && card.geometry?.swatch,
    );
    if (!sourceCards.length) continue;
    const group = active.filter(({ entry }) => entry.section === section.key);
    if (!group.length) {
      slots.set(section.key, []);
      continue;
    }
    const xs = sourceCards.flatMap((card) => [
      card.geometry!.swatch[0],
      card.geometry!.swatch[2],
    ]);
    const ys = sourceCards.flatMap((card) => [
      card.geometry!.swatch[1],
      card.geometry!.swatch[3] + 64,
    ]);
    const bounds: [number, number, number, number] = [
      Math.min(...xs),
      Math.min(...ys),
      Math.max(...xs),
      Math.max(...ys),
    ];
    const originalColumns = new Set(
      sourceCards.map((card) => Math.round(card.geometry!.swatch[0])),
    ).size;
    slots.set(
      section.key,
      layoutWithin(group.length, bounds, Math.max(1, originalColumns)),
    );
  }
  const ordered: LayoutSlot[] = [];
  const cursors = new Map<string, number>();
  for (const { entry } of active) {
    const section = entry.section ?? item.sections.at(-1)!.key;
    const index = cursors.get(section) ?? 0;
    const slot = slots.get(section)?.[index];
    if (!slot) return null;
    ordered.push(slot);
    cursors.set(section, index + 1);
  }
  return ordered;
}

export function layoutFor(item: TemplateSummary, active: ActiveColor[]) {
  return (
    exactSourceLayout(item, active) ??
    sectionLayout(item, active) ??
    layoutWithin(active.length, item.dynamicBounds)
  );
}

function fitFont(
  context: CanvasRenderingContext2D,
  text: string,
  size: number,
  maxWidth: number,
) {
  let result = size;
  context.font = `500 ${result}px Arial, 'Microsoft YaHei', sans-serif`;
  while (context.measureText(text).width > maxWidth && result > 10) {
    result -= 1;
    context.font = `500 ${result}px Arial, 'Microsoft YaHei', sans-serif`;
  }
  return result;
}

export function sizeText(lengths: number[]) {
  return [...new Set(lengths)]
    .sort((a, b) => a - b)
    .map((value) => `${value}″`)
    .join('  ');
}

export async function paintPoster(
  colors: StockColor[],
  item: TemplateSummary,
  selection: Selection,
  inventory?: InventoryStatusMap,
) {
  const active = activeColorsFor(colors, item, selection);
  const [base, photos, hot] = await Promise.all([
    loadImage(item.baseUrl),
    Promise.all(active.map(({ color }) => loadImage(color.image))),
    active.some(({ entry }) => entry.hot)
      ? loadImage(item.hotUrl ?? '/api/runtime-assets/hot.png')
      : Promise.resolve(null),
  ]);
  const output = document.createElement('canvas');
  output.width = item.width;
  output.height = item.height;
  const context = output.getContext('2d');
  if (!context) throw new Error('当前浏览器无法生成图片。');

  context.fillStyle = '#fff';
  context.fillRect(0, 0, output.width, output.height);
  context.drawImage(base, 0, 0, output.width, output.height);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = 'high';
  context.textAlign = 'center';
  context.textBaseline = 'middle';

  const slots = layoutFor(item, active);
  if (slots.length !== active.length)
    throw new Error('当前颜色数量无法排入这个模板。');
  slots.forEach((slot, index) => {
    const { color, entry } = active[index];
    context.drawImage(photos[index], slot.x, slot.y, slot.size, slot.size);
    context.strokeStyle = '#e2bd30';
    context.lineWidth = 1;
    context.strokeRect(
      slot.x - 0.5,
      slot.y - 0.5,
      slot.size + 1,
      slot.size + 1,
    );
    context.fillStyle = '#050505';
    fitFont(context, color.code, slot.codeSize, slot.size + 8);
    context.fillText(color.code, slot.x + slot.size / 2, slot.codeY);
    const lengths = sizeText(entry.lengths);
    fitFont(context, lengths, slot.lengthSize, slot.size + 12);
    context.fillText(lengths, slot.x + slot.size / 2, slot.lengthY);
    drawInventoryOverlay(context, slot, entry, inventory);
    if (entry.hot && hot) {
      const width = slot.size >= 240 ? 65 : 47;
      context.drawImage(
        hot,
        slot.x + slot.size - width * 0.55,
        slot.y - 8,
        width,
        (width * hot.height) / hot.width,
      );
    }
  });
  return output;
}
