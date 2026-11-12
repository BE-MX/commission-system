import verifiedBackgrounds from '@/lib/verified-source-backgrounds.json';
import { RUNTIME_ASSET_BY_KEY, serverTemplateById } from '@/lib/server/catalog';
import type { TemplateSummary } from '@/lib/catalog';

/** Certification is tied to immutable artwork bytes, never a template id alone. */
export function verifiedSourceBackground(template: TemplateSummary, manifestJson: string): string | undefined {
  const original = serverTemplateById(template.id);
  if (!original || original.width !== template.width || original.height !== template.height) return undefined;
  let manifest: Array<{ name: string; sha256: string }>;
  try { manifest = JSON.parse(manifestJson); } catch { return undefined; }
  if (!Array.isArray(manifest)) return undefined;
  const reference = manifest.find((asset) => asset?.name === 'reference.jpg')?.sha256;
  const base = manifest.find((asset) => asset?.name === 'base.png')?.sha256;
  const clean = RUNTIME_ASSET_BY_KEY.get(`templates/${template.id}/base.png`);
  const verified = verifiedBackgrounds.some((entry) => entry.templateId === template.id &&
    entry.referenceSha256 === reference && entry.sourceBaseSha256 === base &&
    entry.cleanBaseSha256 === clean?.sha256);
  return verified ? original.baseUrl : undefined;
}
