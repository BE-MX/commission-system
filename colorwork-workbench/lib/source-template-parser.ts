'use client';

import { sourceReviewIssues } from '@/lib/source-review';
import { readPsd, type Layer, type Psd } from 'ag-psd';
import {
  colorForId,
  lengthsForTemplate,
  type Selection,
  type StockColor,
  type TemplateSection,
  type TemplateSummary,
} from '@/lib/catalog';
import { sourceAssetUrl, type SourceCard, type SourceParseIssue, type SourceTemplateConfig } from '@/lib/source-versions';

type Bounds = [number, number, number, number];

type FlatLayer = {
  layer: Layer;
  path: string[];
  order: number;
  bounds: Bounds | null;
  text: string;
  hidden: boolean;
};

export type ParsedSourceAsset = { name: string; blob: Blob };

export type ParsedTemplateSource = {
  config: SourceTemplateConfig;
  assets: ParsedSourceAsset[];
};

function cleanText(value: unknown) {
  return typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
}

export function normalizedColorCode(value: string) {
  const cleaned = cleanText(value)
    .replace(/(?:\s|_|-)*(?:拷贝|副本|copy)\s*\d*$/i, '')
    .replace(/[／\\-]/g, '/')
    .replace(/\s+/g, '')
    .toUpperCase();
  const explicitlyPrefixed = cleaned.startsWith('#');
  const body = cleaned.replace(/^#/, '');
  const genericLayerName = /^(?:LAYER|GROUP|SHAPE|RECTANGLE|ELLIPSE|OBJECT|SMARTOBJECT|IMAGE|PHOTO|PICTURE|BACKGROUND|BACKDROP|BG|TITLE|HEADER|LOGO|DECORATION|ORNAMENT|COPY|VECTOR|MASK|TEXT|LABEL|SWATCH|COLOR|COLOUR|ARTBOARD|FRAME|FOLDER|CURVE|LEVELS|HUESATURATION|BRIGHTNESSCONTRAST)\d*$/;
  if (
    !body ||
    !/^[A-Z0-9]+(?:\/[A-Z0-9]+)*$/.test(body) ||
    (!explicitlyPrefixed && genericLayerName.test(body)) ||
    (!/\d/.test(body) && !explicitlyPrefixed)
  ) return null;
  return `#${body}`;
}

function semanticColorKey(value: string) {
  return normalizedColorCode(value)?.replace(/^#/, '') ?? value.trim().toUpperCase();
}

function displayColorCode(value: string, colors: StockColor[]) {
  const normalized = normalizedColorCode(value)!;
  const matches = colors.filter((color) => semanticColorKey(color.code) === semanticColorKey(normalized));
  return matches.length === 1 ? matches[0].code : normalized;
}

function slug(value: string) {
  const result = value.toLowerCase().replace(/^#/, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  return result || 'color';
}

function hash(value: string) {
  let current = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    current ^= value.charCodeAt(index);
    current = Math.imul(current, 16777619);
  }
  return (current >>> 0).toString(36);
}

function layerBounds(layer: Layer): Bounds | null {
  const left = Number(layer.left);
  const top = Number(layer.top);
  const right = Number(layer.right);
  const bottom = Number(layer.bottom);
  if (![left, top, right, bottom].every(Number.isFinite) || right <= left || bottom <= top) return null;
  return [left, top, right, bottom];
}

function flatten(
  layers: Layer[] | undefined,
  parents: string[] = [],
  output: FlatLayer[] = [],
  parentHidden = false,
) {
  for (const layer of layers ?? []) {
    const name = cleanText(layer.name) || '未命名图层';
    const path = [...parents, name];
    const hidden = parentHidden || Boolean(layer.hidden);
    output.push({
      layer,
      path,
      order: output.length,
      bounds: layerBounds(layer),
      text: cleanText(layer.text?.text),
      hidden,
    });
    flatten(layer.children, path, output, hidden);
  }
  return output;
}

function width(bounds: Bounds) {
  return bounds[2] - bounds[0];
}

function height(bounds: Bounds) {
  return bounds[3] - bounds[1];
}

function centerX(bounds: Bounds) {
  return (bounds[0] + bounds[2]) / 2;
}

function parseLengths(value: string) {
  const matches = [...value.matchAll(/(?:^|\D)(\d{1,2})\s*[″”"“](?=\D|$)/g)].map((match) => Number(match[1]));
  return [...new Set(matches.filter((item) => Number.isInteger(item) && item > 0 && item <= 100))].sort((a, b) => a - b);
}

function sectionName(value: string, current: TemplateSummary) {
  const match = value.match(/^\[\s*(.+?)\s*\]$/);
  if (match?.[1]?.trim()) return match[1].trim();
  const explicit = value.match(/^(?:section|分区|区域)\s*[:：-]\s*(.+)$/i)?.[1]?.trim();
  if (explicit) return explicit;
  const normalized = value.trim().toLowerCase();
  return current.sections.find((section) => section.label.trim().toLowerCase() === normalized)?.label ?? null;
}

function overlapX(left: Bounds, right: Bounds) {
  return Math.max(0, Math.min(left[2], right[2]) - Math.max(left[0], right[0]));
}

function rankedBelow(candidates: FlatLayer[], bounds: Bounds, maximumDistance: number) {
  return candidates
    .filter((item) => item.bounds && item.bounds[1] >= bounds[3] - 8 && item.bounds[1] - bounds[3] <= maximumDistance)
    .filter((item) => overlapX(item.bounds!, bounds) > 0 || Math.abs(centerX(item.bounds!) - centerX(bounds)) < width(bounds) * 0.65)
    .map((item) => {
      const vertical = Math.max(0, item.bounds![1] - bounds[3]);
      const horizontal = Math.abs(centerX(item.bounds!) - centerX(bounds));
      const overlapPenalty = overlapX(item.bounds!, bounds) > 0 ? 0 : width(bounds) * 0.4;
      return { item, score: vertical * 2 + horizontal + overlapPenalty };
    })
    .sort((a, b) => a.score - b.score || a.item.order - b.item.order);
}

function nearestBelow(candidates: FlatLayer[], bounds: Bounds, maximumDistance: number) {
  return rankedBelow(candidates, bounds, maximumDistance)[0]?.item ?? null;
}

function nearestBelowMatch(candidates: FlatLayer[], bounds: Bounds, maximumDistance: number) {
  const ranked = rankedBelow(candidates, bounds, maximumDistance);
  const first = ranked[0];
  const second = ranked[1];
  return {
    item: first?.item ?? null,
    ambiguous: Boolean(first && second && second.score - first.score <= Math.max(12, width(bounds) * 0.08)),
  };
}

function knownSectionKey(label: string, current: TemplateSummary) {
  const normalized = label.trim().toLowerCase();
  return current.sections.find((section) => section.label.trim().toLowerCase() === normalized)?.key ?? null;
}

function parsedSections(flat: FlatLayer[], current: TemplateSummary): Array<TemplateSection & { top: number }> {
  const result: Array<TemplateSection & { top: number }> = [];
  for (const item of flat) {
    if (item.hidden || !item.bounds || !item.text) continue;
    const label = sectionName(item.text, current);
    if (!label) continue;
    const key = knownSectionKey(label, current) ?? `section-${slug(label)}-${hash(label).slice(0, 5)}`;
    if (!result.some((section) => section.key === key)) result.push({ key, label, top: item.bounds[1] });
  }
  return result.sort((a, b) => a.top - b.top);
}

function sectionFor(bounds: Bounds, sections: Array<TemplateSection & { top: number }>) {
  const candidates = sections.filter((section) => section.top < bounds[1]);
  return candidates.at(-1)?.key ?? (sections.length === 1 ? sections[0].key : null);
}

function oldSemanticMap(
  selection: Selection,
  colors: StockColor[],
  template: TemplateSummary,
) {
  const byColorSection = new Map<string, string[]>();
  const byColor = new Map<string, string[]>();
  for (const entry of selection.filter((value) => value.lengths.length)) {
    const code = colorForId(colors, template, entry.colorId)?.code ?? entry.colorId;
    const colorKey = semanticColorKey(code);
    const section = template.sections.find((value) => value.key === entry.section)?.label ?? '';
    const key = `${colorKey}\u001f${section.trim().toLowerCase()}`;
    const entries = byColorSection.get(key) ?? [];
    entries.push(entry.entryId);
    byColorSection.set(key, entries);
    const colorEntries = byColor.get(colorKey) ?? [];
    colorEntries.push(entry.entryId);
    byColor.set(colorKey, colorEntries);
  }
  return { byColorSection, byColor };
}

function colorIdFor(code: string, colors: StockColor[], sourceVersionId: string) {
  const matches = colors.filter((color) => semanticColorKey(color.code) === semanticColorKey(code));
  if (matches.length === 1) return matches[0].id;
  return `source-color-${slug(code)}-${hash(`${sourceVersionId}:${semanticColorKey(code)}`).slice(0, 7)}`;
}

function canvas(widthValue: number, heightValue: number) {
  const target = document.createElement('canvas');
  target.width = Math.max(1, Math.round(widthValue));
  target.height = Math.max(1, Math.round(heightValue));
  return target;
}

const CANVAS_BLEND_MODES: Record<string, GlobalCompositeOperation> = {
  normal: 'source-over', multiply: 'multiply', screen: 'screen', overlay: 'overlay', darken: 'darken', lighten: 'lighten',
  difference: 'difference', exclusion: 'exclusion', hue: 'hue', saturation: 'saturation', color: 'color', luminosity: 'luminosity',
};

function drawLayer(target: CanvasRenderingContext2D, item: FlatLayer, offsetX = 0, offsetY = 0) {
  if (!item.layer.canvas || !item.bounds || item.hidden) return;
  target.save();
  const opacity = Number(item.layer.opacity);
  target.globalAlpha = Number.isFinite(opacity) ? Math.max(0, Math.min(1, opacity)) : 1;
  target.globalCompositeOperation = CANVAS_BLEND_MODES[item.layer.blendMode || 'normal'] ?? 'source-over';
  target.drawImage(item.layer.canvas, item.bounds[0] - offsetX, item.bounds[1] - offsetY, width(item.bounds), height(item.bounds));
  target.restore();
}

function canvasBlob(value: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => {
    value.toBlob((blob) => blob ? resolve(blob) : reject(new Error('无法生成解析后的 PNG 素材。')), 'image/png');
  });
}

function imageDimensions(file: File) {
  return createImageBitmap(file).then((bitmap) => {
    const dimensions = { width: bitmap.width, height: bitmap.height };
    bitmap.close();
    return dimensions;
  });
}

function isDecorative(item: FlatLayer) {
  const decoration = /(?:^|[\s_-])(?:title|header|footer|logo|decoration|decorative|ornament|bottom|headline|branding)(?:$|[\s_\-\d])|标题|页眉|页脚|底部|装饰|标志|页头/i;
  const name = cleanText(item.layer.name);
  // Explicit color identities still take precedence over a decorative parent.
  if (name.startsWith('#') || normalizedColorCode(item.text)) return false;
  if (decoration.test(name)) return true;
  if (normalizedColorCode(name)) return false;
  const opacity = Number(item.layer.opacity);
  if (item.layer.placedLayer && Number.isFinite(opacity) && opacity < 0.2) return true;
  return item.path.some((part) => decoration.test(part));
}

function looksLikeSwatchGeometry(item: FlatLayer, psd: Psd) {
  if (isDecorative(item) || !item.bounds || item.layer.children?.length || item.hidden || item.text || !item.layer.canvas) return false;
  const opacity = Number(item.layer.opacity);
  if (item.layer.placedLayer && Number.isFinite(opacity) && opacity < 0.2) return false;
  if (item.layer.placedLayer && (
    item.bounds[0] < 0 || item.bounds[1] < 0 || item.bounds[2] > psd.width || item.bounds[3] > psd.height
  )) return false;
  const itemWidth = width(item.bounds);
  const itemHeight = height(item.bounds);
  const ratio = itemWidth / itemHeight;
  return ratio >= 0.72 && ratio <= 1.38 && itemWidth >= 40 && itemHeight >= 40 &&
    itemWidth <= psd.width * 0.48 && itemHeight <= psd.height * 0.48;
}

function isCandidateSwatch(item: FlatLayer, psd: Psd) {
  return looksLikeSwatchGeometry(item, psd) && Boolean(normalizedColorCode(item.layer.name || ''));
}

function boundsUnion(values: Bounds[], documentWidth: number, documentHeight: number): Bounds {
  const left = Math.max(0, Math.floor(Math.min(...values.map((value) => value[0]))));
  const top = Math.max(0, Math.floor(Math.min(...values.map((value) => value[1]))));
  const right = Math.min(documentWidth, Math.ceil(Math.max(...values.map((value) => value[2]))));
  const bottom = Math.min(documentHeight, Math.ceil(Math.max(...values.map((value) => value[3]))));
  return [left, top, right, bottom];
}

function hotPath(item: FlatLayer) {
  const index = item.path.findIndex((part) => /(^|\s)hot(?:\s|$)/i.test(part));
  return index >= 0 ? item.path.slice(0, index + 1).join('\u001f') : null;
}

async function hotAsset(flat: FlatLayer[], hotText: FlatLayer[]) {
  const root = hotText.map(hotPath).find(Boolean);
  if (!root) return null;
  const related = flat.filter((item) => !item.hidden && item.layer.canvas && item.bounds && item.path.join('\u001f').startsWith(root));
  if (!related.length) return null;
  const bounds = boundsUnion(related.map((item) => item.bounds!), 100000, 100000);
  const output = canvas(width(bounds), height(bounds));
  const context = output.getContext('2d');
  if (!context) return null;
  for (const item of [...related].reverse()) drawLayer(context, item, bounds[0], bounds[1]);
  return canvasBlob(output);
}

export async function parseTemplateSource(args: {
  psdFile: File;
  jpgFile: File;
  sourceVersionId: string;
  currentTemplate: TemplateSummary;
  currentColors: StockColor[];
  currentSelection: Selection;
}): Promise<ParsedTemplateSource> {
  const { psdFile, jpgFile, sourceVersionId, currentTemplate, currentColors, currentSelection } = args;
  const psd = readPsd(await psdFile.arrayBuffer(), {
    skipThumbnail: true,
    skipLinkedFilesData: true,
    totalMemoryLimit: 768 * 1024 * 1024,
  });
  if (!psd.children?.length) throw new Error('PSD 没有可解析图层；原版本保持使用。');
  const jpg = await imageDimensions(jpgFile);
  if (jpg.width !== psd.width || jpg.height !== psd.height) {
    throw new Error(`PSD 画布为 ${psd.width}×${psd.height}，对应 JPG 为 ${jpg.width}×${jpg.height}，尺寸不一致。`);
  }

  const flat = flatten(psd.children);
  const issues: SourceParseIssue[] = [];
  for (const item of flat) {
    if (item.hidden || isDecorative(item)) continue;
    const reasons: string[] = [];
    if (item.layer.adjustment) reasons.push('调整图层');
    if (item.layer.effects) reasons.push('图层效果');
    if (item.layer.mask || item.layer.realMask || item.layer.vectorMask || item.layer.filterMask) reasons.push('图层蒙版');
    if (item.layer.placedLayer) reasons.push('智能对象／置入图层');
    if (item.layer.patterns?.length) reasons.push('图案素材');
    if (item.layer.clipping) reasons.push('剪贴图层');
    if (item.layer.blendMode && item.layer.blendMode !== 'pass through' && !CANVAS_BLEND_MODES[item.layer.blendMode]) {
      reasons.push(`不支持的混合模式 ${item.layer.blendMode}`);
    }
    const opacity = Number(item.layer.opacity);
    if (item.layer.children?.length && (
      (Number.isFinite(opacity) && opacity < 0.999) ||
      (item.layer.blendMode && item.layer.blendMode !== 'pass through')
    )) reasons.push('非透传的组混合／透明度');
    if (reasons.length) {
      issues.push({
        code: 'UNSUPPORTED_LAYER_STRUCTURE',
        message: `图层“${item.path.join(' › ')}”包含${reasons.join('、')}，浏览器无法保证与 Photoshop 合成结果完全一致。请对照新版 JPG 人工确认，或栅格化／简化结构后重新上传。`,
        blocking: true,
        details: {
          layerCount: 1,
          layerNames: [item.path.join(' › ')],
          structureTypes: reasons,
        },
      });
    }
  }
  for (const item of flat) {
    if (item.hidden || isDecorative(item) || item.layer.children?.length || item.text || !item.bounds) continue;
    if (normalizedColorCode(item.layer.name || '') && (
      item.bounds[0] < 0 || item.bounds[1] < 0 || item.bounds[2] > psd.width || item.bounds[3] > psd.height
    )) throw new Error(`业务色块“${item.path.join(' › ')}”超出新版 PSD 画布 ${psd.width}×${psd.height}，请修正后重新上传。`);
  }
  const swatches = flat.filter((item) => isCandidateSwatch(item, psd));
  if (!swatches.length) throw new Error('没有识别到可用颜色图层。请保留以色号命名的独立色块图层。');
  if (swatches.length > 100) throw new Error('识别到的颜色图层超过 100 个，无法安全建立母版。');

  const sectionsWithTop = parsedSections(flat, currentTemplate);
  const detectedSections = sectionsWithTop.map(({ key, label }) => ({ key, label }));
  const sections = [...detectedSections];
  for (const section of currentTemplate.sections) {
    if (!sections.some((item) => item.key === section.key)) sections.push(section);
  }
  const currentSectionLabels = currentTemplate.sections.map((section) => section.label.trim().toLowerCase());
  const detectedSectionLabels = detectedSections.map((section) => section.label.trim().toLowerCase());
  if (currentTemplate.sections.length && !detectedSections.length) {
    issues.push({
      code: 'SECTIONS_NOT_RECOGNIZED',
      message: '新版 PSD 没有可靠识别到分区标题。已保留旧分区作为人工映射选项；每个颜色必须重新确认分区，不能静默清空。',
      blocking: true,
    });
  } else if (
    currentSectionLabels.length !== detectedSectionLabels.length ||
    currentSectionLabels.some((label, index) => label !== detectedSectionLabels[index])
  ) {
    issues.push({
      code: 'SECTION_STRUCTURE_CHANGED',
      message: `分区结构发生变化：旧版为“${currentTemplate.sections.map((section) => section.label).join('／') || '无'}”，新版识别为“${detectedSections.map((section) => section.label).join('／') || '无'}”。请核对每个颜色的分区。`,
      blocking: true,
    });
  }
  const colorText = flat.filter((item) => !item.hidden && item.bounds && item.text && normalizedColorCode(item.text));
  const lengthText = flat.filter((item) => !item.hidden && item.bounds && item.text && parseLengths(item.text).length);
  const hotText = flat.filter((item) => !item.hidden && item.bounds && /^hot$/i.test(item.text));
  const sizeMatches = new Map<Layer, ReturnType<typeof nearestBelowMatch>>();
  const sizeLabelUsage = new Map<Layer, number>();
  for (const swatch of swatches) {
    const match = nearestBelowMatch(lengthText, swatch.bounds!, 190);
    sizeMatches.set(swatch.layer, match);
    if (match.item && !match.ambiguous) {
      sizeLabelUsage.set(match.item.layer, (sizeLabelUsage.get(match.item.layer) ?? 0) + 1);
    }
  }
  const oldMaps = oldSemanticMap(currentSelection, currentColors, currentTemplate);
  const excluded = new Set<Layer>();
  const colorsById = new Map<string, StockColor>();
  const assets: ParsedSourceAsset[] = [];

  const cards: SourceCard[] = [];
  for (const [index, swatch] of [...swatches].sort((a, b) => (
    (a.bounds![1] - b.bounds![1]) || (a.bounds![0] - b.bounds![0]) || (a.order - b.order)
  )).entries()) {
    const bounds = swatch.bounds!;
    if (bounds[0] < 0 || bounds[1] < 0 || bounds[2] > psd.width || bounds[3] > psd.height) {
      throw new Error(`业务色块“${swatch.path.join(' › ')}”超出新版 PSD 画布 ${psd.width}×${psd.height}，请修正后重新上传。`);
    }
    const colorCode = displayColorCode(swatch.layer.name || '', currentColors);
    const section = sectionFor(bounds, sectionsWithTop);
    const sectionLabel = sections.find((value) => value.key === section)?.label ?? '';
    const semanticKey = `${semanticColorKey(colorCode)}\u001f${sectionLabel.trim().toLowerCase()}`;
    const oldMatches = oldMaps.byColorSection.get(semanticKey) ?? [];
    const sameColorMatches = oldMaps.byColor.get(semanticColorKey(colorCode)) ?? [];
    const colorLabel = nearestBelow(
      colorText.filter((item) => semanticColorKey(item.text) === semanticColorKey(colorCode)),
      bounds,
      130,
    );
    const sizeMatch = sizeMatches.get(swatch.layer) ?? { item: null, ambiguous: false };
    const sizeLabelShared = Boolean(sizeMatch.item && (sizeLabelUsage.get(sizeMatch.item.layer) ?? 0) > 1);
    const sizeLabelAmbiguous = sizeMatch.ambiguous || sizeLabelShared;
    const sizeLabel = sizeLabelAmbiguous ? null : sizeMatch.item;
    const matchedEntryId = oldMatches.length === 1 ? oldMatches[0] : null;
    const currentEntry = matchedEntryId ? currentSelection.find((entry) => entry.entryId === matchedEntryId) : null;
    const parsedLengthValues = sizeLabel ? parseLengths(sizeLabel.text) : [];
    const fallbackLengths = currentEntry?.lengths.length ? currentEntry.lengths : lengthsForTemplate(currentTemplate).slice(0, 1);
    const lengths = parsedLengthValues.length ? parsedLengthValues : fallbackLengths;
    const candidateId = `candidate-${swatch.layer.id ?? hash(`${swatch.path.join('/')}:${colorCode}:${index}`)}`;
    if (sizeLabelAmbiguous) {
      issues.push({
        code: 'AMBIGUOUS_SIZE_LABEL',
        message: `${colorCode} 附近的尺寸文字同时可能对应多个色块或存在同等候选，不能自动带入。请人工确认尺寸。`,
        candidateId,
        blocking: true,
      });
    } else if (!sizeLabel) {
      issues.push({
        code: 'SIZE_LABEL_NOT_FOUND',
        message: `${colorCode} 没有可靠识别到尺寸文字，当前仅作为待确认值显示。`,
        candidateId,
        blocking: true,
      });
    }
    if (!colorLabel) {
      issues.push({
        code: 'COLOR_LABEL_NOT_FOUND',
        message: `${colorCode} 找到色块图层，但没有找到相符的色号文字，请人工核对。`,
        candidateId,
        blocking: false,
      });
    }
    if (sections.length && !section) {
      issues.push({
        code: 'SECTION_NOT_RELIABLE',
        message: `${colorCode} 无法可靠归入已识别分区。`,
        candidateId,
        blocking: true,
      });
    }
    const matchState: SourceCard['matchState'] = oldMatches.length === 1
      ? 'exact'
      : oldMatches.length === 0 && sameColorMatches.length === 0
        ? 'new'
        : 'unresolved';
    if (matchState === 'unresolved') {
      issues.push({
        code: 'AMBIGUOUS_ENTRY_MATCH',
        message: oldMatches.length > 1
          ? `${colorCode} 在同一分区对应多个旧条目，不能按位置自动迁移库存。`
          : `${colorCode} 在旧版存在，但新版分区不同或分区无法唯一对应，必须人工确认。`,
        candidateId,
        blocking: true,
      });
    }
    const colorId = colorIdFor(colorCode, currentColors, sourceVersionId);
    const assetName = `colors/${slug(colorCode)}-${hash(`${colorCode}:${index}`).slice(0, 6)}.png`;
    const colorCanvas = canvas(width(bounds), height(bounds));
    const colorContext = colorCanvas.getContext('2d');
    if (!colorContext || !swatch.layer.canvas) throw new Error(`${colorCode} 色块像素无法读取。`);
    colorContext.drawImage(swatch.layer.canvas, 0, 0, colorCanvas.width, colorCanvas.height);
    assets.push({ name: assetName, blob: await canvasBlob(colorCanvas) });
    if (!colorsById.has(colorId)) {
      colorsById.set(colorId, {
        id: colorId,
        code: colorCode,
        image: sourceAssetUrl(sourceVersionId, assetName),
        sourceVersionId,
      });
    } else {
      issues.push({
        code: 'DUPLICATE_COLOR_ASSET',
        message: `${colorCode} 在多个位置出现；工作台将保留分区条目，并共用本版本第一张同色素材。`,
        candidateId,
        blocking: false,
      });
    }
    const isHot = hotText.some((item) => item.bounds && (
      Math.abs(centerX(item.bounds) - bounds[2]) < width(bounds) * 0.55 &&
      item.bounds[1] >= bounds[1] - height(bounds) * 0.35 && item.bounds[1] <= bounds[1] + height(bounds) * 0.45
    ));
    cards.push({
      candidateId,
      entryId: matchedEntryId ?? `source-entry-${hash(`${sourceVersionId}:${candidateId}`)}`,
      colorId,
      colorCode,
      lengths: [...new Set(lengths)].sort((a, b) => a - b),
      hot: isHot,
      section,
      order: index,
      geometry: {
        swatch: bounds,
        colorLabel: colorLabel?.bounds ?? null,
        sizeLabel: sizeLabel?.bounds ?? null,
        hotBadge: null,
      },
      matchState,
      matchedEntryId,
      matchReason: matchState === 'exact'
        ? '按唯一规范色号＋稳定分区对应旧条目'
        : matchState === 'new'
          ? '当前母版中没有同色号＋同分区条目'
          : '同色号存在多个候选或分区发生变化，需人工映射',
    });
    excluded.add(swatch.layer);
    if (colorLabel) excluded.add(colorLabel.layer);
    if (sizeMatch.item) excluded.add(sizeMatch.item.layer);
  }

  const swatchBounds = swatches.map((item) => item.bounds!);
  const swatchEnvelope: Bounds = [
    0,
    Math.max(0, Math.min(...swatchBounds.map((bounds) => bounds[1])) - Math.max(...swatchBounds.map(height))),
    psd.width,
    Math.min(psd.height, Math.max(...swatchBounds.map((bounds) => bounds[3])) + Math.max(...swatchBounds.map(height)) * 2.4),
  ];
  const intersects = (left: Bounds, right: Bounds) => (
    Math.min(left[2], right[2]) > Math.max(left[0], right[0]) &&
    Math.min(left[3], right[3]) > Math.max(left[1], right[1])
  );
  const currentDynamicBounds = currentTemplate.dynamicBounds.map((value, index) => (
    value * (index % 2 === 0 ? psd.width / currentTemplate.width : psd.height / currentTemplate.height)
  )) as Bounds;
  for (const item of flat) {
    if (hotPath(item)) excluded.add(item.layer);
  }

  for (const item of flat) {
    if (item.hidden || excluded.has(item.layer) || isDecorative(item)) continue;
    const layerCode = normalizedColorCode(item.layer.name || '');
    const textCode = normalizedColorCode(item.text);
    const textLengths = parseLengths(item.text);
    if (!layerCode && looksLikeSwatchGeometry(item, psd)) {
      issues.push({
        code: 'UNRECOGNIZED_SWATCH_LAYER',
        message: `图层“${item.path.join(' › ')}”在几何上像颜色素材，但名称无法识别为色号。请人工核对。`,
        blocking: true,
      });
    } else if (layerCode && !item.text) {
      issues.push({
        code: 'UNPARSED_COLOR_LAYER',
        message: `图层“${item.path.join(' › ')}”像颜色素材，但因图层类型、比例、尺寸或像素结构不符合要求而未被解析。请人工核对，系统不会静默当作业务颜色。`,
        blocking: true,
      });
    } else if (textCode) {
      issues.push({
        code: 'UNMATCHED_COLOR_TEXT',
        message: `色号文字“${item.text}”（${item.path.join(' › ')}）没有可靠对应到颜色素材。`,
        blocking: true,
      });
    } else if (textLengths.length) {
      issues.push({
        code: 'UNMATCHED_SIZE_TEXT',
        message: `尺寸文字“${item.text}”（${item.path.join(' › ')}）没有可靠对应到颜色素材。`,
        blocking: true,
      });
    } else if (
      item.bounds && item.layer.canvas && !item.layer.children?.length && !item.text &&
      width(item.bounds) * height(item.bounds) < psd.width * psd.height * 0.32 &&
      width(item.bounds) < psd.width * 0.78 && height(item.bounds) < psd.height * 0.78 &&
      (intersects(item.bounds, swatchEnvelope) || intersects(item.bounds, currentDynamicBounds))
    ) {
      issues.push({
        code: 'UNCLASSIFIED_VISIBLE_LAYER',
        message: `可见图层“${item.path.join(' › ')}”位于业务排版区域，但无法可靠判断是颜色素材还是固定装饰。它会保留在底图预览中，但不会自动建立业务规格；请对照 PSD/JPG 确认它确为背景／装饰，否则修正图层名称后重新上传。`,
        blocking: true,
      });
    }
  }

  const baseCanvas = canvas(psd.width, psd.height);
  const baseContext = baseCanvas.getContext('2d');
  if (!baseContext) throw new Error('当前浏览器无法生成新版底图。');
  baseContext.clearRect(0, 0, psd.width, psd.height);
  const fixedLeaves = flat.filter((item) => !item.hidden && item.layer.canvas && !item.layer.children?.length && !excluded.has(item.layer));
  for (const item of [...fixedLeaves].reverse()) drawLayer(baseContext, item);
  assets.push({ name: 'base.png', blob: await canvasBlob(baseCanvas) });
  const parsedHot = await hotAsset(flat, hotText);
  if (parsedHot) assets.push({ name: 'hot.png', blob: parsedHot });
  else if (hotText.length) issues.push({
    code: 'HOT_ASSET_UNAVAILABLE',
    message: '识别到 Hot 标记文字，但无法可靠提取对应图形素材，请人工核对。',
    blocking: true,
  });

  const geometryBounds = cards.flatMap((card) => [
    card.geometry.swatch,
    ...(card.geometry.colorLabel ? [card.geometry.colorLabel] : []),
    ...(card.geometry.sizeLabel ? [card.geometry.sizeLabel] : []),
  ]);
  const dynamicBounds = boundsUnion(geometryBounds, psd.width, psd.height);
  const availableLengths = lengthsForTemplate(currentTemplate);
  const identifiedIssues = sourceReviewIssues(issues, cards, currentColors, availableLengths).map((issue, index) => ({
    ...issue,
    issueId: issue.issueId || `issue-${index + 1}-${hash(`${issue.code}:${issue.candidateId || ''}:${issue.message}`).slice(0, 8)}`,
  }));
  const config: SourceTemplateConfig = {
    schemaVersion: 1,
    template: {
      ...currentTemplate,
      width: psd.width,
      height: psd.height,
      initialColorCount: cards.length,
      sourcePsdName: psdFile.name,
      referenceJpgName: jpgFile.name,
      referenceUrl: sourceAssetUrl(sourceVersionId, 'reference.jpg'),
      baseUrl: sourceAssetUrl(sourceVersionId, 'base.png'),
      hotUrl: parsedHot ? sourceAssetUrl(sourceVersionId, 'hot.png') : undefined,
      dynamicBounds,
      availableLengths,
      sourceVersionId,
      sections,
      initialCards: cards,
      legacyColors: [],
      warnings: identifiedIssues.map((issue) => issue.message),
    },
    colors: [...colorsById.values()],
    availableLengths,
    parseIssues: identifiedIssues,
    parseSummary: {
      layerCount: flat.length,
      parsedColorCount: cards.length,
      parsedSpecCount: cards.reduce((sum, card) => sum + card.lengths.length, 0),
      sectionCount: detectedSections.length,
      documentWidth: psd.width,
      documentHeight: psd.height,
    },
  };
  return { config, assets };
}
