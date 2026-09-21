import { createHash } from 'node:crypto';
import { copyFile, link, mkdir, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import sharp from 'sharp';

const projectDir = path.resolve(import.meta.dirname, '..');
const workspaceDir = path.resolve(
  process.env.COLORWORK_ASSET_WORKSPACE || path.resolve(projectDir, '..'),
);
const stagingDir = path.join(workspaceDir, 'generated-assets-staging');
const extractedDir = path.resolve(process.argv[2] || path.join(stagingDir, 'full-assets'));
const initialPath = path.join(stagingDir, 'initial-configs.json');
const sourceDir = path.join(workspaceDir, '加程专属目录');

const [extracted, initial] = await Promise.all([
  readFile(path.join(extractedDir, 'catalog.json'), 'utf8').then(JSON.parse),
  readFile(initialPath, 'utf8').then(JSON.parse),
]);

if (initial.validation?.passed !== true) throw new Error('初始配置验证未通过，已停止导入。');
if (extracted.templates?.length !== 23) throw new Error(`底图数量应为 23，实际为 ${extracted.templates?.length ?? 0}。`);

const bootstrapDir = path.join(workspaceDir, '首次上线导入包');
const runtimeAssetsDir = path.join(bootstrapDir, '工作台素材', 'assets');
const sourcePackageDir = path.join(bootstrapDir, '源文件');
for (const target of [runtimeAssetsDir, sourcePackageDir]) {
  const resolved = path.resolve(target);
  if (!resolved.startsWith(`${path.resolve(bootstrapDir)}${path.sep}`)) throw new Error(`拒绝清理目录外路径：${resolved}`);
  await rm(resolved, { recursive: true, force: true });
}
const swatchDir = path.join(runtimeAssetsDir, 'swatches');
await mkdir(swatchDir, { recursive: true });

function runtimeUrl(key) {
  return `/api/runtime-assets/${key.split('/').map(encodeURIComponent).join('/')}`;
}

const colors = [];
for (const color of extracted.colors) {
  const destination = path.join(swatchDir, `${color.key}.jpg`);
  await copyFile(path.join(extractedDir, color.asset), destination);
  colors.push({ id: color.key, code: color.code, image: runtimeUrl(`swatches/${color.key}.jpg`) });
}

const extractedByPsd = new Map(extracted.templates.map((item) => [item.sourceFiles.psd, item]));
const templates = [];
for (const source of initial.templates) {
  const asset = extractedByPsd.get(source.sourceFiles.psd);
  if (!asset) throw new Error(`没有找到 ${source.sourceFiles.psd} 的底图。`);
  const templateDir = path.join(runtimeAssetsDir, 'templates', source.id);
  await mkdir(templateDir, { recursive: true });
  const referenceJpg = path.join(sourceDir, source.sourceFiles.jpg);
  const referenceMetadata = await sharp(referenceJpg).metadata();
  if (referenceMetadata.width !== source.canvas.width || referenceMetadata.height !== source.canvas.height) {
    throw new Error(`${source.sourceFiles.jpg} 尺寸 ${referenceMetadata.width}x${referenceMetadata.height} 与画布 ${source.canvas.width}x${source.canvas.height} 不一致。`);
  }
  await Promise.all([
    copyFile(path.join(extractedDir, asset.baseAsset), path.join(templateDir, 'base.png')),
    copyFile(referenceJpg, path.join(templateDir, 'reference.jpg')),
  ]);

  const legacyColors = [];
  const initialCards = [];
  for (const card of source.initialCards) {
    let colorId = card.colorKey;
    if (!colorId) {
      const legacyIndex = legacyColors.length + 1;
      colorId = `legacy-${source.id}-${legacyIndex}`;
      const imageName = `${colorId}.jpg`;
      const [left, top, right, bottom] = card.sourceGeometry.swatch;
      await sharp(path.join(sourceDir, source.sourceFiles.jpg))
        .extract({ left, top, width: right - left, height: bottom - top })
        .jpeg({ quality: 96, chromaSubsampling: '4:4:4' })
        .toFile(path.join(templateDir, imageName));
      legacyColors.push({
        id: colorId,
        code: card.colorCode,
        image: runtimeUrl(`templates/${source.id}/${imageName}`),
        legacy: true,
      });
    }
    initialCards.push({
      entryId: `${source.id}:${card.order}:${colorId}`,
      colorId,
      colorCode: card.colorCode,
      lengths: card.sizes,
      hot: card.hot,
      section: card.section,
      order: card.order,
      geometry: card.sourceGeometry,
    });
  }

  const unresolved = legacyColors.map((color) => `${color.code} 暂不在 38 色主库中，当前按历史色保留。`);
  templates.push({
    id: source.id,
    productName: source.productName,
    radio: source.radio,
    width: source.canvas.width,
    height: source.canvas.height,
    initialColorCount: initialCards.length,
    sourcePsdName: source.sourceFiles.psd,
    referenceJpgName: source.sourceFiles.jpg,
    referenceUrl: runtimeUrl(`templates/${source.id}/reference.jpg`),
    baseUrl: runtimeUrl(`templates/${source.id}/base.png`),
    dynamicBounds: asset.dynamicBounds,
    sections: source.sections,
    initialCards,
    legacyColors,
    warnings: [...(asset.warnings || []), ...unresolved],
  });
}

await copyFile(path.join(extractedDir, 'hot.png'), path.join(runtimeAssetsDir, 'hot.png'));

await mkdir(sourcePackageDir, { recursive: true });
for (const template of templates) {
  for (const name of [template.sourcePsdName, template.referenceJpgName]) {
    const source = path.join(sourceDir, name);
    const destination = path.join(sourcePackageDir, name);
    try {
      await link(source, destination);
    } catch {
      await copyFile(source, destination);
    }
  }
}

async function listFiles(directory, prefix = '') {
  const entries = await readdir(directory, { withFileTypes: true });
  const result = [];
  for (const entry of entries) {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) result.push(...await listFiles(path.join(directory, entry.name), relative));
    else if (entry.isFile()) result.push(relative);
  }
  return result;
}

const runtimeAssets = [];
for (const key of (await listFiles(runtimeAssetsDir)).sort()) {
  const file = path.join(runtimeAssetsDir, ...key.split('/'));
  const [buffer, metadata] = await Promise.all([readFile(file), stat(file)]);
  runtimeAssets.push({
    key,
    relativePath: `工作台素材/assets/${key}`,
    size: metadata.size,
    sha256: createHash('sha256').update(buffer).digest('hex'),
    contentType: key.endsWith('.png') ? 'image/png' : 'image/jpeg',
  });
}

const output = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  colors,
  templates,
  validation: {
    templateCount: templates.length,
    colorCount: colors.length,
    initialCardCount: templates.reduce((sum, item) => sum + item.initialCards.length, 0),
    legacyColorCount: templates.reduce((sum, item) => sum + item.legacyColors.length, 0),
    runtimeAssetCount: runtimeAssets.length,
  },
};

if (output.validation.colorCount !== 38 || output.validation.initialCardCount !== 341 || output.validation.runtimeAssetCount !== 87) {
  throw new Error(`导入校验失败：${JSON.stringify(output.validation)}`);
}

await writeFile(path.join(projectDir, 'lib', 'generated-catalog.json'), `${JSON.stringify(output, null, 2)}\n`, 'utf8');
await writeFile(path.join(projectDir, 'lib', 'generated-runtime-assets.json'), `${JSON.stringify({ schemaVersion: 1, assets: runtimeAssets }, null, 2)}\n`, 'utf8');
await writeFile(path.join(projectDir, 'ASSET-IMPORT-REPORT.json'), `${JSON.stringify(output.validation, null, 2)}\n`, 'utf8');
process.stdout.write(`${JSON.stringify(output.validation)}\n`);
