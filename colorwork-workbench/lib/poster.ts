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

async function loadBaseImage(item: TemplateSummary) {
  if (item.referenceUrl) {
    try {
      return { image: await loadImage(item.referenceUrl), fromReference: true };
    } catch {
      // Older imported templates and isolated QA fixtures may not have a
      // separately addressable reference JPG yet.
    }
  }
  return { image: await loadImage(item.baseUrl), fromReference: false };
}

/** Restore real artwork only when the server has certified its source binding. */
export async function loadRedrawBackground(item: TemplateSummary) {
  const cleanUrl = item.cleanBaseUrl ?? (item.baseUrl.startsWith('/api/runtime-assets/') ? item.baseUrl : undefined);
  // Other source versions retain their existing rendering contract. A matching
  // template name or a similar picture is not proof of a certified background.
  if (!cleanUrl) return null;
  const clean = await loadImage(cleanUrl);
  if (clean.width !== item.width || clean.height !== item.height) {
    throw new Error('无文字底图与当前源文件尺寸不一致，请检查配套素材。');
  }
  const canvas = document.createElement('canvas');
  canvas.width = item.width;
  canvas.height = item.height;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('当前浏览器无法校验母版底图。');
  context.drawImage(clean, 0, 0);
  const pixels = context.getImageData(0, 0, item.width, item.height).data;
  for (let index = 3; index < pixels.length; index += 4) {
    if (pixels[index] < 250) throw new Error('无文字底图不完整，文字下方需要保留原背景纹理。');
  }
  // Source/reference byte fingerprints are checked on the server. Pixel
  // similarity cannot certify artwork changes; static reference JPGs may also
  // be thumbnails while their complete backgrounds are full-resolution.
  return clean;
}

export function activeColorsFor(
  colors: StockColor[],
  item: TemplateSummary,
  selection: Selection,
): ActiveColor[] {
  return selection
    .filter((entry) => entry.kind === 'display' || entry.lengths.length)
    .map((entry) => ({ color: colorForId(colors, item, entry.colorId), entry }))
    .filter((value): value is ActiveColor => Boolean(value.color))
    .sort(
      (a, b) =>
        a.entry.order - b.entry.order ||
        a.color.code.localeCompare(b.color.code),
    );
}

function sourceLabelBounds(
  item: TemplateSummary,
  card: TemplateSummary['initialCards'][number],
  field: 'colorLabel' | 'sizeLabel',
): [number, number, number, number] | null {
  const known = card.geometry?.[field];
  if (known) return known;
  if (!card.geometry || card.kind === 'display') return null;
  if (!item.cleanBaseUrl && !item.baseUrl.startsWith('/api/runtime-assets/')) return null;
  const [left, top, right, bottom] = card.geometry.swatch;
  // Some approved PSD imports have an unbound text layer. Its ink is still in
  // the reference JPG. Use the nearest stock card in the same row to recover
  // the caption band for both erasing that ink and positioning the new text.
  const peer = item.initialCards
    .filter((candidate) => candidate !== card && candidate.kind !== 'display' &&
      candidate.geometry?.[field] &&
      Math.abs(candidate.geometry.swatch[1] - top) <= 4 &&
      Math.abs(candidate.geometry.swatch[3] - bottom) <= 4)
    .sort((a, b) => Math.abs(a.geometry!.swatch[0] - left) - Math.abs(b.geometry!.swatch[0] - left))[0];
  if (!peer?.geometry) return null;
  const bounds = peer.geometry[field]!;
  const offset = bottom - peer.geometry.swatch[3];
  // The missing label may be wider than the peer's text (e.g. Cookies Cream).
  return [left - 10, bounds[1] + offset, right + 10, bounds[3] + offset];
}

function slotFromGeometry(
  card: TemplateSummary['initialCards'][number],
  item: TemplateSummary,
): LayoutSlot {
  const [left, top, right, bottom] = card.geometry!.swatch;
  const size = Math.min(right - left, bottom - top);
  const colorLabel = sourceLabelBounds(item, card, 'colorLabel');
  const sizeLabel = sourceLabelBounds(item, card, 'sizeLabel');
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
  return sourceLayoutForActive(item, active);
}

function sourceLayoutForActive(item: TemplateSummary, active: ActiveColor[]) {
  const sourceByEntry = new Map(
    item.initialCards.map((card) => [card.entryId, card]),
  );
  const cards = active.map(({ entry }) => sourceByEntry.get(entry.entryId));
  if (cards.some((card) => !card?.geometry?.swatch)) return null;
  // Keep the source positions, but assign them in the current display order.
  // Otherwise moving a card only changes the editor list, not the exported JPG.
  return [...cards]
    .sort((left, right) => left!.order - right!.order || left!.entryId.localeCompare(right!.entryId))
    .map((card) => slotFromGeometry(card!, item));
}

function sameReferenceComposition(item: TemplateSummary, active: ActiveColor[]) {
  if (!item.referenceUrl || active.length !== item.initialCards.length) return false;
  const sourceCards = [...item.initialCards].sort(
    (left, right) => left.order - right.order || left.entryId.localeCompare(right.entryId),
  );
  return active.every(({ entry }, index) => {
    const card = sourceCards[index];
    if (!card || card.entryId !== entry.entryId || card.colorId !== entry.colorId) return false;
    if ((card.kind ?? 'stock') !== (entry.kind ?? 'stock') || card.hot !== entry.hot || card.section !== entry.section || card.order !== entry.order) return false;
    const cardLengths = [...card.lengths].sort((left, right) => left - right);
    const entryLengths = [...entry.lengths].sort((left, right) => left - right);
    return cardLengths.length === entryLengths.length && cardLengths.every(
      (length, lengthIndex) => length === entryLengths[lengthIndex],
    );
  });
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

function clearUnverifiedSourceRegions(context: CanvasRenderingContext2D, item: TemplateSummary) {
  // Preserve the pre-existing behavior for arbitrary uploaded source artwork.
  // Only certified source/background pairs may replace it with real texture.
  context.save();
  context.fillStyle = '#ffffff';
  for (const card of item.initialCards) {
    const geometry = card.geometry;
    for (const bounds of [geometry?.swatch, geometry?.colorLabel, geometry?.sizeLabel, geometry?.hotBadge]) {
      if (!bounds) continue;
      const [left, top, right, bottom] = bounds;
      context.fillRect(Math.max(0, left - 3), Math.max(0, top - 3),
        Math.min(item.width, right + 3) - Math.max(0, left - 3),
        Math.min(item.height, bottom + 3) - Math.max(0, top - 3));
    }
  }
  context.restore();
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
  const baseResult = await loadBaseImage(item);
  const preserveReferenceComposition = baseResult.fromReference &&
    sameReferenceComposition(item, active);
  const background = preserveReferenceComposition
    ? baseResult.image
    : await loadRedrawBackground(item);
  const [photos, hot] = await Promise.all([
    preserveReferenceComposition
      ? Promise.resolve([] as HTMLImageElement[])
      : Promise.all(active.map(({ color }) => loadImage(color.image))),
    !preserveReferenceComposition && active.some(({ entry }) => entry.hot)
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
  context.drawImage(background ?? baseResult.image, 0, 0, output.width, output.height);
  if (!preserveReferenceComposition && !background) clearUnverifiedSourceRegions(context, item);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = 'high';
  context.textAlign = 'center';
  context.textBaseline = 'middle';

  const slots = preserveReferenceComposition
    ? sourceLayoutForActive(item, active) ?? layoutFor(item, active)
    : layoutFor(item, active);
  if (slots.length !== active.length)
    throw new Error('当前颜色数量无法排入这个模板。');
  slots.forEach((slot, index) => {
    const { color, entry } = active[index];
    if (!preserveReferenceComposition) {
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
      if (entry.kind !== 'display') {
        fitFont(context, color.code, slot.codeSize, slot.size + 8);
        context.fillText(color.code, slot.x + slot.size / 2, slot.codeY);
        const lengths = sizeText(entry.lengths);
        fitFont(context, lengths, slot.lengthSize, slot.size + 12);
        context.fillText(lengths, slot.x + slot.size / 2, slot.lengthY);
      }
    }
    drawInventoryOverlay(context, slot, entry, inventory);
    if (!preserveReferenceComposition && entry.kind !== 'display' && entry.hot && hot) {
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
