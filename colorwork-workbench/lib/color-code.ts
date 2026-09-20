import type { StockColor } from '@/lib/catalog';

type ColorCodeSource = Pick<StockColor, 'code'>;

export function colorCodeKey(value: string) {
  return value
    .trim()
    .toUpperCase()
    .replace(/^#/, '')
    .replace(/[／\\-]/g, '/')
    .replace(/\s+/g, '');
}

function editDistanceAtMostOne(left: string, right: string) {
  if (Math.abs(left.length - right.length) > 1) return false;
  let leftIndex = 0;
  let rightIndex = 0;
  let differences = 0;
  while (leftIndex < left.length && rightIndex < right.length) {
    if (left[leftIndex] === right[rightIndex]) {
      leftIndex += 1;
      rightIndex += 1;
      continue;
    }
    differences += 1;
    if (differences > 1) return false;
    if (left.length > right.length) leftIndex += 1;
    else if (right.length > left.length) rightIndex += 1;
    else {
      leftIndex += 1;
      rightIndex += 1;
    }
  }
  return (
    differences + (left.length - leftIndex) + (right.length - rightIndex) <= 1
  );
}

/**
 * Exact matching is preferred. A unique one-character typo is accepted for
 * long color codes so PSD labels such as 5TP8A/24 and COOKISCREAM can still
 * resolve to an existing catalog color without guessing between candidates.
 */
export function knownColorForCode<T extends ColorCodeSource>(
  value: string,
  colors: T[],
) {
  const key = colorCodeKey(value);
  const exact = colors.filter((color) => colorCodeKey(color.code) === key);
  if (exact.length === 1) return exact[0];
  if (!key || key.length < 4) return null;
  const near = colors.filter((color) =>
    editDistanceAtMostOne(colorCodeKey(color.code), key),
  );
  return near.length === 1 ? near[0] : null;
}
