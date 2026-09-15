import generatedCatalog from '@/lib/generated-catalog.json';
import generatedRuntimeAssets from '@/lib/generated-runtime-assets.json';
import type { CatalogData, RuntimeAsset, TemplateSummary } from '@/lib/catalog';

type GeneratedCatalog = {
  colors: CatalogData['colors'];
  templates: TemplateSummary[];
};

const sourceCatalog = generatedCatalog as unknown as GeneratedCatalog;
const runtimeAssets = (generatedRuntimeAssets as { assets: RuntimeAsset[] }).assets;

export const CATALOG: CatalogData = {
  colors: sourceCatalog.colors,
  templates: sourceCatalog.templates,
  runtimeAssets,
};

export const SERVER_TEMPLATES = CATALOG.templates;
export const RUNTIME_ASSETS = CATALOG.runtimeAssets;
export const RUNTIME_ASSET_BY_KEY = new Map(RUNTIME_ASSETS.map((asset) => [asset.key, asset]));

export function serverTemplateById(id: string) {
  return SERVER_TEMPLATES.find((template) => template.id === id);
}
