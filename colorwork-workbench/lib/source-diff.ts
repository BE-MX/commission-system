import { colorForId, type Selection, type StockColor, type TemplateSummary } from '@/lib/catalog';
import type {
  SourceCard,
  SourceChangeItem,
  SourceChangeSummary,
  SourceTemplateConfig,
} from '@/lib/source-versions';

function sorted(values: number[]) {
  return [...new Set(values.map(Number))].sort((a, b) => a - b);
}

function sameNumbers(left: number[], right: number[]) {
  const a = sorted(left);
  const b = sorted(right);
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

function sectionLabel(template: TemplateSummary, key: string | null) {
  if (!key) return null;
  return template.sections.find((section) => section.key === key)?.label ?? key;
}

function currentItem(
  entryId: string,
  selection: Selection,
  colors: StockColor[],
  template: TemplateSummary,
): SourceChangeItem | null {
  const entry = selection.find((value) => value.entryId === entryId);
  if (!entry) return null;
  const color = colorForId(colors, template, entry.colorId);
  return {
    entryId,
    colorCode: color?.code ?? entry.colorId,
    section: sectionLabel(template, entry.section),
    lengths: sorted(entry.lengths),
  };
}

function nextItem(card: SourceCard, template: TemplateSummary): SourceChangeItem {
  return {
    candidateId: card.candidateId,
    entryId: card.matchedEntryId ?? undefined,
    colorCode: card.colorCode,
    section: sectionLabel(template, card.section),
    lengths: sorted(card.lengths),
  };
}

export function computeSourceChanges(
  currentTemplate: TemplateSummary,
  currentColors: StockColor[],
  currentSelection: Selection,
  next: SourceTemplateConfig,
): SourceChangeSummary {
  const currentActive = [...currentSelection]
    .filter((entry) => entry.lengths.length > 0)
    .sort((a, b) => a.order - b.order || a.entryId.localeCompare(b.entryId));
  const currentById = new Map(currentActive.map((entry, index) => [entry.entryId, { entry, index }]));
  const matchedIds = new Set<string>();
  const added: SourceChangeItem[] = [];
  const unchanged: SourceChangeItem[] = [];
  const resized: SourceChangeSummary['resized'] = [];
  const reordered: SourceChangeItem[] = [];
  const resectioned: SourceChangeItem[] = [];
  const nextMatched: Array<{ entryId: string; item: SourceChangeItem }> = [];

  next.template.initialCards.forEach((card) => {
    const nextValue = nextItem(card, next.template);
    const matched = card.matchedEntryId ? currentById.get(card.matchedEntryId) : null;
    if (!matched) {
      added.push(nextValue);
      return;
    }
    matchedIds.add(matched.entry.entryId);
    nextMatched.push({ entryId: matched.entry.entryId, item: nextValue });
    const previous = currentItem(matched.entry.entryId, currentActive, currentColors, currentTemplate)!;
    const sameSection = previous.section === nextValue.section;
    if (sameNumbers(previous.lengths, nextValue.lengths)) {
      if (sameSection) unchanged.push(nextValue);
    } else {
      resized.push({ ...nextValue, previousLengths: previous.lengths, nextLengths: nextValue.lengths });
    }
    if (!sameSection) resectioned.push(nextValue);
  });

  const currentMatchedOrder = currentActive
    .filter((entry) => matchedIds.has(entry.entryId))
    .map((entry) => entry.entryId);
  nextMatched.forEach((match, index) => {
    if (currentMatchedOrder[index] !== match.entryId) reordered.push(match.item);
  });

  const removed = currentActive
    .filter((entry) => !matchedIds.has(entry.entryId))
    .map((entry) => currentItem(entry.entryId, currentActive, currentColors, currentTemplate)!)
    .filter(Boolean);
  const currentSections = currentTemplate.sections.map((section) => section.label.trim().toLowerCase());
  const nextSections = next.template.sections.map((section) => section.label.trim().toLowerCase());

  return {
    added,
    removed,
    unchanged,
    resized,
    reordered,
    resectioned,
    dimensionsChanged:
      currentTemplate.width === next.template.width && currentTemplate.height === next.template.height
        ? null
        : {
            before: { width: currentTemplate.width, height: currentTemplate.height },
            after: { width: next.template.width, height: next.template.height },
          },
    sectionsChanged:
      currentSections.length !== nextSections.length ||
      currentSections.some((value, index) => value !== nextSections[index]),
    backgroundChanged: 'unknown',
  };
}
