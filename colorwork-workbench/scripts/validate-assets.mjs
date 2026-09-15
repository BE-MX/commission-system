import { createHash } from 'node:crypto';
import { access, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';

const projectDir = path.resolve(import.meta.dirname, '..');
const workspaceDir = path.resolve(projectDir, '..');
const runtimeAssetsDir = path.join(workspaceDir, '首次上线导入包', '工作台素材', 'assets');
const sourcePackageDir = path.join(workspaceDir, '首次上线导入包', '源文件');
const catalog = JSON.parse(await readFile(path.join(projectDir, 'lib', 'generated-catalog.json'), 'utf8'));
const runtimeManifest = JSON.parse(await readFile(path.join(projectDir, 'lib', 'generated-runtime-assets.json'), 'utf8'));
const allowedRadios = new Set(['Regular Double Drawn', 'Super Double Drawn', 'Ultra Double Drawn']);
const allowedSizes = new Set([16, 18, 20, 22, 24]);
const errors = [];

function check(condition, message) { if (!condition) errors.push(message); }
async function imageMetadata(url) {
  const key = url.replace(/^\/api\/runtime-assets\//, '').split('/').map(decodeURIComponent).join('/');
  const file = path.join(runtimeAssetsDir, ...key.split('/'));
  await access(file);
  return sharp(file).metadata();
}

check(catalog.colors.length === 38, `标准色应为 38，实际为 ${catalog.colors.length}`);
check(catalog.templates.length === 23, `模板应为 23，实际为 ${catalog.templates.length}`);
check(new Set(catalog.colors.map((color) => color.id)).size === 38, '标准色 ID 存在重复');
check(new Set(catalog.colors.map((color) => color.code.toLowerCase())).size === 38, '标准色号存在重复');
check(runtimeManifest.assets.length === 87, `运行素材应为 87，实际为 ${runtimeManifest.assets.length}`);

for (const color of catalog.colors) {
  const metadata = await imageMetadata(color.image);
  check(metadata.format === 'jpeg' && metadata.width > 0 && metadata.height > 0, `${color.code} 色块文件不可读`);
}

const templatePairs = new Set();
const entryIds = new Set();
let cardCount = 0;
let hotCount = 0;
let legacyCount = 0;
for (const template of catalog.templates) {
  const pair = `${template.productName}\0${template.radio}`;
  check(!templatePairs.has(pair), `${template.productName} ${template.radio} 重复`);
  templatePairs.add(pair);
  check(allowedRadios.has(template.radio), `${template.id} Radio 无效`);
  check(template.width === 1000 && template.height > 0, `${template.id} 画布尺寸无效`);
  check(template.initialColorCount === template.initialCards.length, `${template.id} 初始数量不一致`);
  const [left, top, right, bottom] = template.dynamicBounds;
  check(left >= 0 && top >= 0 && right <= template.width && bottom <= template.height && right > left && bottom > top, `${template.id} 动态区域越界`);
  const base = await imageMetadata(template.baseUrl);
  check(base.format === 'png' && base.width === template.width && base.height === template.height, `${template.id} 底图尺寸不一致`);
  const reference = await imageMetadata(template.referenceUrl);
  check(reference.format === 'jpeg' && reference.width > 0 && reference.height > 0, `${template.id} 参考缩略图不可读`);
  await Promise.all([
    access(path.join(workspaceDir, '加程专属目录', template.sourcePsdName)),
    access(path.join(workspaceDir, '加程专属目录', template.referenceJpgName)),
    access(path.join(sourcePackageDir, template.sourcePsdName)),
    access(path.join(sourcePackageDir, template.referenceJpgName)),
  ]);
  const availableColors = new Set([...catalog.colors, ...template.legacyColors].map((color) => color.id));
  for (const legacy of template.legacyColors) {
    legacyCount += 1;
    const metadata = await imageMetadata(legacy.image);
    check(metadata.format === 'jpeg' && metadata.width > 0 && metadata.height > 0, `${template.id} 历史色不可读`);
  }
  for (const card of template.initialCards) {
    cardCount += 1;
    if (card.hot) hotCount += 1;
    check(!entryIds.has(card.entryId), `${card.entryId} 色卡 ID 重复`);
    entryIds.add(card.entryId);
    check(availableColors.has(card.colorId), `${card.entryId} 找不到色块素材`);
    check(card.lengths.length > 0 && card.lengths.every((size) => allowedSizes.has(size)), `${card.entryId} 尺寸无效`);
    const [x1, y1, x2, y2] = card.geometry.swatch;
    check(x1 >= 0 && y1 >= 0 && x2 <= template.width && y2 <= template.height && x2 > x1 && y2 > y1, `${card.entryId} 几何位置越界`);
    if (card.section) check(template.sections.some((section) => section.key === card.section), `${card.entryId} 分区无效`);
  }
}

for (const asset of runtimeManifest.assets) {
  const file = path.join(runtimeAssetsDir, ...asset.key.split('/'));
  const buffer = await readFile(file);
  check(buffer.length === asset.size, `${asset.key} 大小与清单不一致`);
  check(createHash('sha256').update(buffer).digest('hex') === asset.sha256, `${asset.key} 校验值不一致`);
}
await imageMetadata('/api/runtime-assets/hot.png');

const iTip = catalog.templates.find((template) => template.id === 'i-tip-hair-regular');
const iTipSections = Object.fromEntries(iTip.sections.map((section) => [
  section.label,
  iTip.initialCards.filter((card) => card.section === section.key).length,
]));
check(cardCount === 341, `初始色卡应为 341，实际为 ${cardCount}`);
check(hotCount === 44, `Hot 标记应为 44，实际为 ${hotCount}`);
check(legacyCount === 2, `历史色应为 2，实际为 ${legacyCount}`);
check(iTip.initialCards.length === 8 && new Set(iTip.initialCards.map((card) => card.colorId)).size === 6, 'I Tip Regular 重复色卡结构未保留');
check(iTipSections['Regular I Tip Hair'] === 3 && iTipSections['New Upgraded I Tip Hair'] === 5, 'I Tip Regular 分区数量不正确');

const result = {
  passed: errors.length === 0,
  templateCount: catalog.templates.length,
  productCount: new Set(catalog.templates.map((template) => template.productName)).size,
  canonicalColorCount: catalog.colors.length,
  initialCardCount: cardCount,
  hotCount,
  legacyColorCount: legacyCount,
  iTipRegularSections: iTipSections,
  errors,
};
await writeFile(path.join(projectDir, 'VALIDATION.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
if (errors.length) throw new Error(`素材校验失败：\n${errors.join('\n')}`);
process.stdout.write(`${JSON.stringify(result)}\n`);
