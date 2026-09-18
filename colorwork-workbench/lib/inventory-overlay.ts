import type { SelectionEntry } from '@/lib/catalog';
import {
  STATUS_IMAGE_LABELS,
  statusFor,
  type InventoryStatus,
  type InventoryStatusMap,
} from '@/lib/inventory';

export type { InventoryStatus, InventoryStatusMap };
export type InventoryLength = 16 | 18 | 20 | 22 | 24;

export type InventoryOverlaySlot = {
  x: number;
  y: number;
  size: number;
};

export type InventoryOverlayBadge = {
  status: Exclude<InventoryStatus, 'normal'>;
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
  fontSize: number;
};

export type InventoryOverlayPlan = {
  badges: InventoryOverlayBadge[];
  bounds: { x: number; y: number; width: number; height: number } | null;
};

const LENGTH_ORDER: InventoryLength[] = [16, 18, 20, 22, 24];
const STATUS_ORDER: Array<Exclude<InventoryStatus, 'normal'>> = [
  'out_of_stock',
  'low_stock',
  'restocking',
];

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function selectedLengths(entry: SelectionEntry): InventoryLength[] {
  const selected = new Set(entry.lengths);
  return LENGTH_ORDER.filter((length) => selected.has(length));
}

function compactLengthText(lengths: InventoryLength[]) {
  if (lengths.length === 1) return `${lengths[0]}″`;

  const positions = lengths.map((length) => LENGTH_ORDER.indexOf(length));
  const contiguous = positions.every(
    (position, index) => index === 0 || position === positions[index - 1] + 1,
  );
  if (contiguous) return `${lengths[0]}–${lengths.at(-1)}″`;
  return `${lengths.join('/')}″`;
}

export function inventoryStatusFor(
  inventory: InventoryStatusMap | undefined,
  entryId: string,
  length: number,
): InventoryStatus {
  if (!LENGTH_ORDER.includes(length as InventoryLength)) return 'normal';
  return inventory ? statusFor(inventory, entryId, length) : 'normal';
}

export function createInventoryOverlayPlan(
  slot: InventoryOverlaySlot,
  entry: SelectionEntry,
  inventory?: InventoryStatusMap,
): InventoryOverlayPlan {
  const lengths = selectedLengths(entry);
  if (!lengths.length || !inventory?.[entry.entryId])
    return { badges: [], bounds: null };

  const groups = STATUS_ORDER.map((status) => ({
    status,
    lengths: lengths.filter(
      (length) =>
        inventoryStatusFor(inventory, entry.entryId, length) === status,
    ),
  }))
    .filter((group) => group.lengths.length)
    .sort((left, right) => left.lengths[0] - right.lengths[0]);

  if (!groups.length) return { badges: [], bounds: null };

  const margin = clamp(Math.round(slot.size * 0.035), 4, 8);
  const gap = clamp(Math.round(slot.size * 0.022), 3, 5);
  const height = clamp(Math.round(slot.size * 0.12), 16, 25);
  const fontSize = clamp(Math.round(slot.size * 0.068), 9, 15);
  const width = Math.max(1, Math.round(slot.size - margin * 2));
  const x = Math.round(slot.x + margin);
  const totalHeight = groups.length * height + (groups.length - 1) * gap;
  const startY = Math.round(slot.y + slot.size - margin - totalHeight);
  const wholeColor =
    lengths.length > 1 &&
    groups.length === 1 &&
    groups[0].lengths.length === lengths.length;

  const badges = groups.map(
    (group, index): InventoryOverlayBadge => ({
      status: group.status,
      text: wholeColor
        ? STATUS_IMAGE_LABELS[group.status]
        : `${compactLengthText(group.lengths)} · ${STATUS_IMAGE_LABELS[group.status]}`,
      x,
      y: startY + index * (height + gap),
      width,
      height,
      fontSize,
    }),
  );

  return {
    badges,
    bounds: {
      x,
      y: startY,
      width,
      height: totalHeight,
    },
  };
}

function roundedRectangle(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  const safeRadius = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(x + safeRadius, y);
  context.lineTo(x + width - safeRadius, y);
  context.quadraticCurveTo(x + width, y, x + width, y + safeRadius);
  context.lineTo(x + width, y + height - safeRadius);
  context.quadraticCurveTo(
    x + width,
    y + height,
    x + width - safeRadius,
    y + height,
  );
  context.lineTo(x + safeRadius, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - safeRadius);
  context.lineTo(x, y + safeRadius);
  context.quadraticCurveTo(x, y, x + safeRadius, y);
  context.closePath();
}

function fittedBadgeFont(
  context: CanvasRenderingContext2D,
  text: string,
  preferredSize: number,
  maxWidth: number,
) {
  let size = preferredSize;
  context.font = `700 ${size}px Arial, 'Microsoft YaHei', sans-serif`;
  while (size > 7 && context.measureText(text).width > maxWidth) {
    size -= 1;
    context.font = `700 ${size}px Arial, 'Microsoft YaHei', sans-serif`;
  }
  return size;
}

function drawFittedBadgeText(
  context: CanvasRenderingContext2D,
  text: string,
  centerX: number,
  centerY: number,
  preferredSize: number,
  maxWidth: number,
) {
  fittedBadgeFont(context, text, preferredSize, maxWidth);
  const measuredWidth = context.measureText(text).width;
  const horizontalScale =
    measuredWidth > 0 ? Math.min(1, maxWidth / measuredWidth) : 1;
  context.save();
  context.translate(centerX, centerY);
  context.scale(horizontalScale, 1);
  context.fillText(text, 0, 0.5);
  context.restore();
}

export function drawInventoryOverlayPlan(
  context: CanvasRenderingContext2D,
  plan: InventoryOverlayPlan,
) {
  if (!plan.badges.length) return;

  context.save();
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.lineWidth = 1;

  for (const badge of plan.badges) {
    const radius = clamp(Math.round(badge.height * 0.28), 4, 7);
    roundedRectangle(
      context,
      badge.x,
      badge.y,
      badge.width,
      badge.height,
      radius,
    );
    if (badge.status === 'out_of_stock') {
      context.fillStyle = 'rgba(10, 30, 84, 0.94)';
      context.fill();
      context.strokeStyle = 'rgba(249, 240, 238, 0.95)';
      context.stroke();
      context.fillStyle = '#ffffff';
    } else if (badge.status === 'low_stock') {
      context.fillStyle = 'rgba(255, 243, 205, 0.96)';
      context.fill();
      context.strokeStyle = '#d6a64b';
      context.stroke();
      context.fillStyle = '#7a4d00';
    } else {
      context.fillStyle = 'rgba(249, 240, 238, 0.95)';
      context.fill();
      context.strokeStyle = '#b39a84';
      context.stroke();
      context.fillStyle = '#0a1e54';
    }

    drawFittedBadgeText(
      context,
      badge.text,
      badge.x + badge.width / 2,
      badge.y + badge.height / 2,
      badge.fontSize,
      badge.width - 8,
    );
  }

  context.restore();
}

export function drawInventoryOverlay(
  context: CanvasRenderingContext2D,
  slot: InventoryOverlaySlot,
  entry: SelectionEntry,
  inventory?: InventoryStatusMap,
) {
  const plan = createInventoryOverlayPlan(slot, entry, inventory);
  drawInventoryOverlayPlan(context, plan);
  return plan;
}
