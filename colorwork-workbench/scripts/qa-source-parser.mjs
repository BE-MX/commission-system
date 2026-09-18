import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { access, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { writePsdBuffer } from 'ag-psd';
import sharp from 'sharp';
import { build } from 'vite';

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputPath = path.join(projectDir, 'outputs', 'qa-source-parser.json');
const tempDir = await mkdtemp(path.join(tmpdir(), 'source-parser-qa-'));
const profileDir = path.join(tempDir, 'browser-profile');
const entryFile = path.join(tempDir, 'entry.mjs');
const bundleDir = path.join(tempDir, 'bundle');
const width = 820;
const height = 620;
let browser;
let server;

function imageData(imageWidth, imageHeight, [red, green, blue, alpha = 255]) {
  const data = new Uint8ClampedArray(imageWidth * imageHeight * 4);
  for (let offset = 0; offset < data.length; offset += 4) {
    data[offset] = red;
    data[offset + 1] = green;
    data[offset + 2] = blue;
    data[offset + 3] = alpha;
  }
  return { width: imageWidth, height: imageHeight, data };
}

function pixelLayer(name, left, top, layerWidth, layerHeight, color, extra = {}) {
  return { name, left, top, imageData: imageData(layerWidth, layerHeight, color), ...extra };
}

function textLayer(name, text, left, top, layerWidth = 120) {
  return {
    name,
    left,
    top,
    imageData: imageData(layerWidth, 24, [20, 20, 20, 255]),
    text: {
      text,
      transform: [1, 0, 0, 1, left, top + 18],
      style: {
        font: { name: 'ArialMT' },
        fontSize: 18,
        fillColor: { r: 20, g: 20, b: 20 },
      },
    },
  };
}

const psd = {
  width,
  height,
  imageData: imageData(width, height, [247, 245, 240, 255]),
  children: [
    pixelLayer('Background', 0, 0, width, height, [247, 245, 240, 255]),
    pixelLayer('#1006', 40, 180, 120, 120, [211, 180, 140, 255]),
    textLayer('color label 1006', '#1006', 60, 310, 80),
    textLayer('size label 1006', '18″, 22″', 40, 342),
    pixelLayer('#1B', 200, 180, 120, 120, [50, 35, 30, 255]),
    textLayer('color label 1B', '#1B', 220, 310, 80),
    textLayer('size label 1B', '18″, 24″', 200, 342),
    pixelLayer('#62', 360, 180, 120, 120, [225, 210, 185, 255]),
    textLayer('color label 62', '#62', 380, 310, 80),
    textLayer('size label 62', '20″, 24″', 360, 342),
    pixelLayer('Layer 1', 40, 450, 80, 80, [220, 80, 80, 255]),
    pixelLayer('mystery strip', 200, 470, 160, 30, [80, 120, 220, 255]),
    { name: 'QA brightness adjustment', adjustment: { type: 'brightness/contrast', brightness: 10, contrast: 5 } },
    {
      name: 'hidden old color',
      hidden: true,
      children: [pixelLayer('#2B', 520, 180, 120, 120, [70, 50, 40, 255])],
    },
  ],
};

const psdBuffer = writePsdBuffer(psd);
const rulesChildren = psd.children.map((layer) => layer.name === '#62' ? { ...layer, name: '#999' }
  : layer.name === 'color label 62' ? textLayer('color label 999', '#999', 380, 310, 80)
  : layer.name === 'size label 62' ? textLayer('size label 999', '28″', 360, 342) : layer);
const rulesPsdBuffer = writePsdBuffer({ ...psd, children: [...rulesChildren,
  { name: 'Header', children: [pixelLayer('Decorative 1', -40, -40, 100, 100, [0, 0, 0], { effects: { disabled: true } })] },
  { name: 'Another adjustment', adjustment: { type: 'brightness/contrast', brightness: 5, contrast: 5 } },
] });
const outsidePsdBuffer = writePsdBuffer({ ...psd, children: [...psd.children,
  pixelLayer('#999', -20, 100, 120, 120, [0, 0, 0]),
] });
const ambiguousPsdBuffer = writePsdBuffer({
  width,
  height,
  imageData: imageData(width, height, [247, 245, 240, 255]),
  children: [
    pixelLayer('Background', 0, 0, width, height, [247, 245, 240, 255]),
    pixelLayer('#1B', 40, 180, 120, 120, [50, 35, 30, 255]),
    textLayer('color label 1B', '#1B', 60, 310, 80),
    pixelLayer('#2', 200, 180, 120, 120, [70, 50, 40, 255]),
    textLayer('color label 2', '#2', 220, 310, 80),
    textLayer('shared size label', '18″, 24″', 140, 342, 120),
  ],
});
const jpgBuffer = await sharp({
  create: { width, height, channels: 3, background: { r: 247, g: 245, b: 240 } },
}).jpeg({ quality: 92 }).toBuffer();
const catalogBuffer = await readFile(path.join(projectDir, 'lib', 'generated-catalog.json'));

const entrySource = String.raw`
import { parseTemplateSource } from '@/lib/source-template-parser.ts';
import { computeSourceChanges } from '@/lib/source-diff.ts';
import { paintPoster } from '@/lib/poster.ts';

function fileFrom(path, name, type) {
  return fetch(path).then(async (response) => new File([await response.arrayBuffer()], name, { type }));
}

function assetName(url) {
  return url.split('/').slice(4).map(decodeURIComponent).join('/');
}

try {
  const [catalog, psdFile, jpgFile, ambiguousPsdFile] = await Promise.all([
    fetch('/catalog.json').then((response) => response.json()),
    fileFrom('/fixture.psd', 'Tape Hair-Super Double Drawn-v2.psd', 'image/vnd.adobe.photoshop'),
    fileFrom('/fixture.jpg', 'Tape Hair-Super Double Drawn-v2.jpg', 'image/jpeg'),
    fileFrom('/ambiguous.psd', 'Tape Hair-Super Double Drawn-ambiguous.psd', 'image/vnd.adobe.photoshop'),
  ]);
  const currentTemplate = catalog.templates.find((item) => item.id === 'tape-hair-super');
  const currentSelection = currentTemplate.initialCards.map((card) => ({
    entryId: card.entryId,
    colorId: card.colorId,
    lengths: [...card.lengths],
    hot: card.hot,
    section: card.section,
    order: card.order,
  }));
  const parsed = await parseTemplateSource({
    psdFile,
    jpgFile,
    sourceVersionId: 'browser-parser-fixture-v2',
    currentTemplate,
    currentColors: catalog.colors,
    currentSelection,
  });
  const ambiguous = await parseTemplateSource({
    psdFile: ambiguousPsdFile,
    jpgFile,
    sourceVersionId: 'browser-parser-ambiguous-v2',
    currentTemplate,
    currentColors: catalog.colors,
    currentSelection,
  });
  const rules = await parseTemplateSource({
    psdFile: await fileFrom('/rules.psd', 'rules.psd', 'image/vnd.adobe.photoshop'), jpgFile,
    sourceVersionId: 'rules', currentTemplate, currentColors: catalog.colors, currentSelection,
  });
  let outsideError = '';
  try {
    await parseTemplateSource({ psdFile: await fileFrom('/outside.psd', 'outside.psd', 'image/vnd.adobe.photoshop'),
      jpgFile, sourceVersionId: 'outside', currentTemplate, currentColors: catalog.colors, currentSelection });
  } catch (error) { outsideError = error.message; }
  const mismatchCanvas = document.createElement('canvas');
  mismatchCanvas.width = 300; mismatchCanvas.height = 300;
  const mismatchBlob = await new Promise((resolve) => mismatchCanvas.toBlob(resolve, 'image/jpeg'));
  let mismatchError = '';
  try {
    await parseTemplateSource({ psdFile, jpgFile: new File([mismatchBlob], 'mismatch.jpg', { type: 'image/jpeg' }),
      sourceVersionId: 'mismatch', currentTemplate, currentColors: catalog.colors, currentSelection });
  } catch (error) { mismatchError = error.message; }
  const diff = computeSourceChanges(currentTemplate, catalog.colors, currentSelection, parsed.config);
  const urls = Object.fromEntries(parsed.assets.map((asset) => [asset.name, URL.createObjectURL(asset.blob)]));
  const previewColors = parsed.config.colors.map((color) => ({ ...color, image: urls[assetName(color.image)] }));
  const previewTemplate = { ...parsed.config.template, baseUrl: urls['base.png'], hotUrl: undefined };
  const previewSelection = previewTemplate.initialCards.map((card) => ({
    entryId: card.entryId,
    colorId: card.colorId,
    lengths: [...card.lengths],
    hot: false,
    section: card.section,
    order: card.order,
  }));
  const preview = await paintPoster(previewColors, previewTemplate, previewSelection);
  const previewBlob = await new Promise((resolve, reject) => preview.toBlob(
    (blob) => blob ? resolve(blob) : reject(new Error('预览编码失败。')),
    'image/png',
  ));
  const result = {
    config: {
      width: parsed.config.template.width,
      height: parsed.config.template.height,
      cards: parsed.config.template.initialCards.map((card) => ({
        candidateId: card.candidateId,
        colorCode: card.colorCode,
        lengths: card.lengths,
        matchState: card.matchState,
        matchedEntryId: card.matchedEntryId,
        order: card.order,
      })),
      issues: parsed.config.parseIssues,
      assets: parsed.assets.map((asset) => ({ name: asset.name, size: asset.blob.size })),
      summary: parsed.config.parseSummary,
    },
    rules: { issues: rules.config.parseIssues, availableLengths: rules.config.availableLengths,
      cards: rules.config.template.initialCards, assets: rules.assets.map((asset) => asset.name), outsideError, mismatchError },
    diff,
    preview: { width: preview.width, height: preview.height, bytes: previewBlob.size },
    ambiguity: {
      cards: ambiguous.config.template.initialCards.map((card) => ({ candidateId: card.candidateId, colorCode: card.colorCode, lengths: card.lengths })),
      issues: ambiguous.config.parseIssues,
    },
  };
  await fetch('/result', { method: 'POST', body: JSON.stringify(result) });
  document.body.textContent = 'Source parser QA complete';
} catch (error) {
  await fetch('/error', {
    method: 'POST',
    body: error instanceof Error ? error.stack || error.message : String(error),
  });
}
`;

function requestBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => resolve(Buffer.concat(chunks)));
    request.on('error', reject);
  });
}

async function browserPath() {
  const candidates = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  ];
  for (const candidate of candidates) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      // Continue with the next installed browser.
    }
  }
  throw new Error('没有找到 Chrome 或 Edge，无法执行真实浏览器解析。');
}

function listenForResult() {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('真实 PSD 解析验证超时。')), 90_000);
    globalThis.__finishSourceParserQa = (value, failed = false) => {
      clearTimeout(timeout);
      if (failed) reject(value);
      else resolve(value);
    };
  });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function stopBrowser(child) {
  if (!child || child.exitCode !== null || child.killed) return;
  await new Promise((resolve) => {
    const timeout = setTimeout(resolve, 2_000);
    child.once('exit', () => {
      clearTimeout(timeout);
      resolve();
    });
    child.kill();
  });
}

try {
  await writeFile(entryFile, entrySource);
  await build({
    configFile: false,
    logLevel: 'error',
    resolve: { alias: { '@': projectDir } },
    build: {
      emptyOutDir: true,
      minify: false,
      outDir: bundleDir,
      lib: { entry: entryFile, formats: ['es'], fileName: () => 'bundle.js' },
    },
  });

  server = createServer(async (request, response) => {
    try {
      const url = new URL(request.url || '/', 'http://127.0.0.1');
      const staticFiles = {
        '/bundle.js': ['text/javascript; charset=utf-8', await readFile(path.join(bundleDir, 'bundle.js'))],
        '/catalog.json': ['application/json', catalogBuffer],
        '/rules.psd': ['image/vnd.adobe.photoshop', rulesPsdBuffer],
        '/outside.psd': ['image/vnd.adobe.photoshop', outsidePsdBuffer],
        '/fixture.psd': ['image/vnd.adobe.photoshop', psdBuffer],
        '/ambiguous.psd': ['image/vnd.adobe.photoshop', ambiguousPsdBuffer],
        '/fixture.jpg': ['image/jpeg', jpgBuffer],
      };
      if (request.method === 'GET' && url.pathname === '/') {
        response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
        response.end('<!doctype html><html><body><script type="module" src="/bundle.js"></script></body></html>');
        return;
      }
      if (request.method === 'GET' && staticFiles[url.pathname]) {
        const [contentType, body] = staticFiles[url.pathname];
        response.writeHead(200, { 'content-type': contentType });
        response.end(body);
        return;
      }
      if (request.method === 'POST' && url.pathname === '/result') {
        const result = JSON.parse((await requestBody(request)).toString('utf8'));
        response.writeHead(204).end();
        globalThis.__finishSourceParserQa?.(result);
        return;
      }
      if (request.method === 'POST' && url.pathname === '/error') {
        const message = (await requestBody(request)).toString('utf8');
        response.writeHead(204).end();
        globalThis.__finishSourceParserQa?.(new Error(message), true);
        return;
      }
      response.writeHead(404).end();
    } catch (error) {
      response.writeHead(500, { 'content-type': 'text/plain; charset=utf-8' });
      response.end(error instanceof Error ? error.stack : String(error));
    }
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('无法取得验证服务端口。');
  const resultPromise = listenForResult();
  browser = spawn(await browserPath(), [
    '--headless=new', '--disable-gpu', '--disable-breakpad', '--disable-crash-reporter',
    '--disable-dev-shm-usage', '--no-sandbox', `--user-data-dir=${profileDir}`,
    `http://127.0.0.1:${address.port}/`,
  ], { stdio: ['ignore', 'ignore', 'pipe'] });
  let browserErrors = '';
  browser.stderr.on('data', (chunk) => { browserErrors += chunk.toString(); });
  browser.once('error', (error) => globalThis.__finishSourceParserQa?.(error, true));
  browser.once('exit', (code) => {
    if (code) globalThis.__finishSourceParserQa?.(new Error(`浏览器异常退出（${code}）：${browserErrors.slice(-1200)}`), true);
  });
  const result = await resultPromise;
  const codes = result.config.cards.map((card) => card.colorCode);
  const issueCodes = result.config.issues.map((issue) => issue.code);
  const issueIds = result.config.issues.map((issue) => issue.issueId);
  const ambiguousSizeIssues = result.ambiguity.issues.filter((issue) => issue.code === 'AMBIGUOUS_SIZE_LABEL');
  assert(JSON.stringify(codes) === JSON.stringify(['#1006', '#1B', '#62']), `颜色或重排解析错误：${JSON.stringify(codes)}`);
  assert(!codes.includes('#2B'), '隐藏父组中的 #2B 被错误解析。');
  assert(!codes.includes('#LAYER1'), '默认图层名 Layer 1 被错误解析为色号。');
  assert(new Set(issueIds).size === issueIds.length && issueIds.every(Boolean), '解析问题缺少逐项唯一 ID。');
  assert(issueCodes.includes('UNRECOGNIZED_SWATCH_LAYER'), '未报告无法识别的方形图层。');
  assert(issueCodes.includes('UNCLASSIFIED_VISIBLE_LAYER'), '未报告业务区内无法分类的可见图层。');
  const parserStructureIssue = result.config.issues.find((issue) => issue.code === 'UNSUPPORTED_LAYER_STRUCTURE');
  assert(issueCodes.includes('UNSUPPORTED_LAYER_STRUCTURE') && parserStructureIssue?.blocking, '不支持的 Photoshop 图层结构没有被阻断并要求人工确认。');
  assert(parserStructureIssue?.details?.layerCount >= 1 && parserStructureIssue.details.layerNames?.length && parserStructureIssue.details.structureTypes?.length, '批量结构提醒缺少数量、代表图层或结构类型。');
  assert(result.diff.added.some((item) => item.colorCode === '#62'), '变化清单未识别新增颜色 #62。');
  assert(result.diff.removed.some((item) => item.colorCode === '#2'), '变化清单未识别移除颜色 #2。');
  assert(result.diff.unchanged.some((item) => item.colorCode === '#1006'), '变化清单未识别保持不变的 #1006。');
  assert(result.diff.resized.some((item) => item.colorCode === '#1B' && item.nextLengths.includes(24)), '变化清单未识别 #1B 尺寸改为 18／24。');
  assert(result.diff.addedLengths.some((item) => item.colorCode === '#1B' && item.lengths.includes(24)), '变化清单未识别新增尺寸。');
  assert(result.diff.removedLengths.some((item) => item.colorCode === '#1B' && item.lengths.includes(22)), '变化清单未识别移除尺寸。');
  assert(result.diff.reordered.some((item) => item.colorCode === '#1006'), '变化清单未识别 #1006 重排。');
  assert(result.diff.dimensionsChanged?.after.width === width && result.diff.dimensionsChanged?.after.height === height, '变化清单未识别画布尺寸调整。');
  assert(result.preview.width === width && result.preview.height === height && result.preview.bytes > 1000, '新版母版预览未成功渲染。');
  assert(result.config.assets.some((asset) => asset.name === 'base.png' && asset.size > 0), '解析后的底图素材缺失。');
  assert(ambiguousSizeIssues.length === 2 && ambiguousSizeIssues.every((issue) => issue.blocking), '共享尺寸文字没有逐色阻断并要求人工确认。');
  assert(new Set(ambiguousSizeIssues.map((issue) => issue.candidateId)).size === 2, '共享尺寸文字的阻断问题未绑定到两个独立色块。');

  const serverStructureIssue = result.rules.issues.find((issue) => issue.code === 'UNSUPPORTED_LAYER_STRUCTURE');
  assert(result.rules.issues.filter((issue) => issue.code === 'UNSUPPORTED_LAYER_STRUCTURE').length === 1, '结构问题没有合并');
  assert(serverStructureIssue?.details?.layerCount >= 1 && serverStructureIssue.details.layerNames?.length && serverStructureIssue.details.structureTypes?.length, '服务端批量结构提醒缺少详情');
  assert(result.rules.issues.some((issue) => issue.code === 'NEW_COLOR_SWATCH_REVIEW' && issue.blocking), '新颜色缺少人工确认提醒');
  assert(result.rules.issues.some((issue) => issue.code === 'LENGTH_OUTSIDE_S1' && issue.blocking), '超长缺少提醒');
  assert(!result.rules.availableLengths.includes(28), '新版自动扩展了允许长度');
  assert(result.rules.cards.some((card) => card.colorCode === '#999' && card.lengths.includes(28)), '新颜色或待纠正的原始长度丢失');
  assert(result.rules.assets.some((name) => name.startsWith('colors/999-')), '新颜色候选色块没有提取');
  assert(!result.rules.issues.some((issue) => issue.message.includes('Header') || issue.message.includes('Logo')), '装饰被误判为业务色块');
  assert(result.rules.outsideError.includes('超出新版 PSD'), '真实业务色块越界未阻止');
  assert(result.rules.mismatchError.includes('尺寸不一致'), 'PSD/JPG 不一致未阻止');
  assert(result.diff.removed.some((item) => item.colorCode === '#1B' && item.lengths.includes(22)), '删除尺寸未进入移除项目');
  const report = {
    passed: true,
    fixture: { psdBytes: psdBuffer.length, ambiguousPsdBytes: ambiguousPsdBuffer.length, jpgBytes: jpgBuffer.length, width, height },
    ...result,
  };
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({ passed: true, reportPath: outputPath, cards: codes, issues: issueCodes, preview: result.preview }, null, 2)}\n`);
} finally {
  delete globalThis.__finishSourceParserQa;
  await stopBrowser(browser);
  if (server) await new Promise((resolve) => server.close(resolve));
  await rm(tempDir, { recursive: true, force: true, maxRetries: 20, retryDelay: 150 });
}
