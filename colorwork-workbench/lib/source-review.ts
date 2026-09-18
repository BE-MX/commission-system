import type { StockColor } from '@/lib/catalog';
import type { SourceCard, SourceParseIssue } from '@/lib/source-versions';

/** Rebuilt on the server too: browser-supplied issues cannot waive review rules. */
export function sourceReviewIssues(
  issues: SourceParseIssue[], cards: SourceCard[], knownColors: StockColor[], allowedLengths: number[],
): SourceParseIssue[] {
  const structure = issues.filter((issue) => issue.code === 'UNSUPPORTED_LAYER_STRUCTURE');
  const result = issues.filter((issue) => ![
    'UNSUPPORTED_LAYER_STRUCTURE', 'NEW_COLOR_SWATCH_REVIEW', 'LENGTH_OUTSIDE_S1',
  ].includes(issue.code));
  if (structure.length) {
    const layerNames = [...new Set(structure.flatMap((issue) => issue.details?.layerNames ?? []))];
    const structureTypes = [...new Set(structure.flatMap((issue) => issue.details?.structureTypes ?? []))];
    const layerCount = structure.reduce((count, issue) => count + (issue.details?.layerCount ?? 1), 0);
    const exampleText = layerNames.slice(0, 8).join('、') || '未命名结构图层';
    const typeText = structureTypes.join('、') || '智能对象、蒙版或图层效果';
    result.push({
      issueId: 'structure-visual-review', code: 'UNSUPPORTED_LAYER_STRUCTURE', blocking: true,
      details: {
        layerCount,
        layerNames: layerNames.slice(0, 8),
        structureTypes: structureTypes.slice(0, 8),
      },
      message: `检测到 ${layerCount} 个需要整体视觉确认的图层结构；代表图层：${exampleText}；涉及结构：${typeText}。请整体对照新版 JPG 确认视觉一致。本类问题只需统一勾选一次；勾选仅代表确认处理结果，不会自动修复。`,
    });
  }
  const key = (code: string) => code.trim().replace(/^#/, '').replace(/[／\\-]/g, '/').replace(/\s/g, '').toUpperCase();
  for (const card of cards) {
    const isNewColor = card.matchState === 'new' || (!card.matchedEntryId && !knownColors.some((color) => key(color.code) === key(card.colorCode)));
    if (isNewColor) result.push({
      issueId: `new-color-${card.candidateId}`, code: 'NEW_COLOR_SWATCH_REVIEW', candidateId: card.candidateId, blocking: true,
      details: { swatchStatus: '待确认／待补充色块图' },
      message: `${card.colorCode}：这是新版新增颜色，请确认色块图；如需独立色块图，请补充上传。当前候选色块由新版 PSD 提取，人工确认前不会继承旧颜色库存身份或自动启用。`,
    });
    const invalid = card.lengths.filter((length) => !allowedLengths.includes(length));
    if (invalid.length) result.push({
      issueId: `length-${card.candidateId}`, code: 'LENGTH_OUTSIDE_S1', candidateId: card.candidateId, blocking: true,
      message: `${card.colorCode} 的 ${invalid.join('／')}″ 超出旧母版 S1 允许集合（${allowedLengths.join('／')}″）。请人工改成允许尺寸或排除该颜色；勾选提醒不能绕过长度校验。`,
    });
  }
  return result;
}
