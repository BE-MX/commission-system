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
  if (structure.length) result.push({
    issueId: 'structure-visual-review', code: 'UNSUPPORTED_LAYER_STRUCTURE', blocking: true,
    message: '新版包含智能对象、蒙版、效果或其他无法可靠合成的图层结构。请对照新版 JPG 确认整体视觉一致；本类问题只需统一勾选一次。不一致时请栅格化／简化结构后重新上传。',
  });
  const key = (code: string) => code.trim().replace(/^#/, '').replace(/[／\\-]/g, '/').replace(/\s/g, '').toUpperCase();
  for (const card of cards) {
    if (!knownColors.some((color) => key(color.code) === key(card.colorCode))) result.push({
      issueId: `new-color-${card.candidateId}`, code: 'NEW_COLOR_SWATCH_REVIEW', candidateId: card.candidateId, blocking: true,
      message: `${card.colorCode} 是新颜色，已从新版 PSD 提取候选色块图。请对照 JPG 确认色块图；如需要独立色块图，请补充上传后重新解析。人工确认前不会成为已确认规格。`,
    });
    const invalid = card.lengths.filter((length) => !allowedLengths.includes(length));
    if (invalid.length) result.push({
      issueId: `length-${card.candidateId}`, code: 'LENGTH_OUTSIDE_S1', candidateId: card.candidateId, blocking: true,
      message: `${card.colorCode} 的 ${invalid.join('／')}″ 超出旧母版 S1 允许集合（${allowedLengths.join('／')}″）。请人工改成允许尺寸或排除该颜色；勾选提醒不能绕过长度校验。`,
    });
  }
  return result;
}
