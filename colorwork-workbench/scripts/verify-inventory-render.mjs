import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { access, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';
import { build } from 'vite';

const projectDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
);
const workspaceDir = path.resolve(projectDir, '..');
const runtimeAssetsDir = path.join(
  workspaceDir,
  '首次上线导入包',
  '工作台素材',
  'assets',
);
const keepOutput = process.argv.includes('--keep');
const tempDir = await mkdtemp(path.join(tmpdir(), 'inventory-render-verify-'));
const browserProfile = path.join(tempDir, 'chrome-profile');
const entryFile = path.join(tempDir, 'entry.mjs');
const bundleDir = path.join(tempDir, 'bundle');
const catalog = await readFile(
  path.join(projectDir, 'lib', 'generated-catalog.json'),
);
const captures = new Map();
let browser;
let server;

const entrySource = String.raw`
import { activeColorsFor, layoutFor, paintPoster } from '@/lib/poster.ts';
import { createInventoryOverlayPlan } from '@/lib/inventory-overlay.ts';

const CASES = [
  '20g-genius-weft-super',
  'i-tip-hair-regular',
  'silk-genius-weft-regular',
];

function selectionFor(template) {
  return template.initialCards.map((card) => ({
    entryId: card.entryId,
    colorId: card.colorId,
    lengths: [...card.lengths],
    hot: card.hot,
    section: card.section,
    order: card.order,
  }));
}

function inventoryFor(selection) {
  const inventory = {};
  const first = selection[0];
  const second = selection[1];
  const third = selection[2];
  if (first?.lengths.length) {
    inventory[first.entryId] = { [first.lengths[0]]: 'out_of_stock' };
    if (first.lengths[1]) inventory[first.entryId][first.lengths[1]] = 'low_stock';
  }
  if (second?.lengths.length) {
    inventory[second.entryId] = Object.fromEntries(second.lengths.map((length) => [length, 'restocking']));
  }
  if (third?.lengths.length > 1) {
    inventory[third.entryId] = {
      [third.lengths[0]]: 'out_of_stock',
      [third.lengths[1]]: 'restocking',
    };
    if (third.lengths[2]) inventory[third.entryId][third.lengths[2]] = 'low_stock';
  }
  return inventory;
}

function normalInventoryFor(selection) {
  return Object.fromEntries(selection.map((entry) => [
    entry.entryId,
    Object.fromEntries(entry.lengths.map((length) => [length, 'normal'])),
  ]));
}

async function canvasBlob(canvas, type, quality) {
  return new Promise((resolve, reject) => canvas.toBlob(
    (blob) => blob ? resolve(blob) : reject(new Error('Canvas 编码失败。')),
    type,
    quality,
  ));
}

async function sendCapture(id, kind, blob) {
  const response = await fetch('/capture/' + encodeURIComponent(id) + '/' + kind, {
    method: 'POST',
    body: blob,
  });
  if (!response.ok) throw new Error('验证图片回传失败：' + id + '/' + kind);
}

try {
  const catalog = await fetch('/catalog.json').then((response) => response.json());
  const plans = {};
  for (const id of CASES) {
    const template = catalog.templates.find((item) => item.id === id);
    if (!template) throw new Error('找不到验证模板：' + id);
    const selection = selectionFor(template);
    const inventory = inventoryFor(selection);
    const baseline = await paintPoster(catalog.colors, template, selection);
    const normal = await paintPoster(catalog.colors, template, selection, normalInventoryFor(selection));
    const rendered = await paintPoster(catalog.colors, template, selection, inventory);
    const active = activeColorsFor(catalog.colors, template, selection);
    const slots = layoutFor(template, active);
    plans[id] = active.flatMap(({ entry }, index) => {
      const plan = createInventoryOverlayPlan(slots[index], entry, inventory);
      return plan.badges.length ? [{ entryId: entry.entryId, ...plan }] : [];
    });
    await Promise.all([
      sendCapture(id, 'baseline.png', await canvasBlob(baseline, 'image/png')),
      sendCapture(id, 'normal.png', await canvasBlob(normal, 'image/png')),
      sendCapture(id, 'inventory.png', await canvasBlob(rendered, 'image/png')),
      sendCapture(id, 'inventory.jpg', await canvasBlob(rendered, 'image/jpeg', 0.94)),
    ]);
  }
  await fetch('/plans', { method: 'POST', body: JSON.stringify(plans) });
  await fetch('/done', { method: 'POST' });
  document.body.textContent = 'Inventory render verification complete';
} catch (error) {
  await fetch('/error', { method: 'POST', body: error instanceof Error ? error.stack || error.message : String(error) });
}
`;

function bodyBuffer(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => resolve(Buffer.concat(chunks)));
    request.on('error', reject);
  });
}

async function chromePath() {
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
      // Try the next installed browser location.
    }
  }
  return null;
}

function waitForBrowserResult() {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('浏览器渲染验证超时。')),
      90_000,
    );
    const finish = (value, error = false) => {
      clearTimeout(timeout);
      if (error) reject(value);
      else resolve(value);
    };
    captures.set('__finish', finish);
  });
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

async function comparePngs(baselinePath, renderedPath, plans) {
  const baseline = await sharp(baselinePath)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const rendered = await sharp(renderedPath)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  if (
    baseline.info.width !== rendered.info.width ||
    baseline.info.height !== rendered.info.height
  ) {
    throw new Error('覆盖前后画布尺寸发生变化。');
  }

  const rectangles = plans.flatMap((plan) =>
    plan.badges.map((badge) => ({
      left: badge.x - 1,
      top: badge.y - 1,
      right: badge.x + badge.width + 1,
      bottom: badge.y + badge.height + 1,
    })),
  );
  let changedPixels = 0;
  let changedOutsideOverlay = 0;
  const channels = baseline.info.channels;
  for (
    let pixel = 0;
    pixel < baseline.info.width * baseline.info.height;
    pixel += 1
  ) {
    const offset = pixel * channels;
    let changed = false;
    for (let channel = 0; channel < channels; channel += 1) {
      if (baseline.data[offset + channel] !== rendered.data[offset + channel]) {
        changed = true;
        break;
      }
    }
    if (!changed) continue;
    changedPixels += 1;
    const x = pixel % baseline.info.width;
    const y = Math.floor(pixel / baseline.info.width);
    if (
      !rectangles.some(
        (rect) =>
          x >= rect.left &&
          x <= rect.right &&
          y >= rect.top &&
          y <= rect.bottom,
      )
    ) {
      changedOutsideOverlay += 1;
    }
  }
  return { changedPixels, changedOutsideOverlay };
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
      if (request.method === 'GET' && url.pathname === '/') {
        response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
        response.end(
          '<!doctype html><html><body><script type="module" src="/bundle.js"></script></body></html>',
        );
        return;
      }
      if (request.method === 'GET' && url.pathname === '/bundle.js') {
        response.writeHead(200, {
          'content-type': 'text/javascript; charset=utf-8',
        });
        response.end(await readFile(path.join(bundleDir, 'bundle.js')));
        return;
      }
      if (request.method === 'GET' && url.pathname === '/catalog.json') {
        response.writeHead(200, { 'content-type': 'application/json' });
        response.end(catalog);
        return;
      }
      if (
        request.method === 'GET' &&
        url.pathname.startsWith('/api/runtime-assets/')
      ) {
        const key = url.pathname
          .slice('/api/runtime-assets/'.length)
          .split('/')
          .map(decodeURIComponent)
          .join('/');
        const assetPath = path.resolve(runtimeAssetsDir, ...key.split('/'));
        if (
          !assetPath.startsWith(`${path.resolve(runtimeAssetsDir)}${path.sep}`)
        )
          throw new Error('非法素材路径。');
        const data = await readFile(assetPath);
        response.writeHead(200, {
          'content-type': key.endsWith('.png') ? 'image/png' : 'image/jpeg',
        });
        response.end(data);
        return;
      }
      if (request.method === 'POST' && url.pathname.startsWith('/capture/')) {
        const [, , encodedId, kind] = url.pathname.split('/');
        const id = decodeURIComponent(encodedId);
        const outputPath = path.join(tempDir, `${id}-${kind}`);
        await writeFile(outputPath, await bodyBuffer(request));
        captures.set(`${id}/${kind}`, outputPath);
        response.writeHead(204).end();
        return;
      }
      if (request.method === 'POST' && url.pathname === '/plans') {
        captures.set(
          '__plans',
          JSON.parse((await bodyBuffer(request)).toString('utf8')),
        );
        response.writeHead(204).end();
        return;
      }
      if (request.method === 'POST' && url.pathname === '/done') {
        response.writeHead(204).end();
        captures.get('__finish')?.(true);
        return;
      }
      if (request.method === 'POST' && url.pathname === '/error') {
        const message = (await bodyBuffer(request)).toString('utf8');
        response.writeHead(204).end();
        captures.get('__finish')?.(new Error(message), true);
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
  if (!address || typeof address === 'string')
    throw new Error('无法取得验证服务端口。');

  const executable = await chromePath();
  if (!executable) throw new Error('没有找到 Chrome 或 Edge。');
  const browserResult = waitForBrowserResult();
  browser = spawn(
    executable,
    [
      '--headless=new',
      '--disable-gpu',
      '--disable-breakpad',
      '--disable-crash-reporter',
      '--disable-dev-shm-usage',
      '--no-sandbox',
      '--hide-scrollbars',
      `--user-data-dir=${browserProfile}`,
      `http://127.0.0.1:${address.port}/`,
    ],
    { stdio: ['ignore', 'ignore', 'pipe'] },
  );
  let browserErrors = '';
  browser.stderr.on('data', (chunk) => {
    browserErrors += chunk.toString();
  });
  browser.once('error', (error) => captures.get('__finish')?.(error, true));
  browser.once('exit', (code) => {
    if (code && !captures.has('__plans')) {
      captures.get('__finish')?.(
        new Error(`浏览器异常退出（${code}）：${browserErrors.slice(-1000)}`),
        true,
      );
    }
  });
  await browserResult;

  const plansByTemplate = captures.get('__plans');
  const sourceCatalog = JSON.parse(catalog.toString('utf8'));
  const results = [];
  for (const id of [
    '20g-genius-weft-super',
    'i-tip-hair-regular',
    'silk-genius-weft-regular',
  ]) {
    const template = sourceCatalog.templates.find((item) => item.id === id);
    const baselinePath = captures.get(`${id}/baseline.png`);
    const normalPath = captures.get(`${id}/normal.png`);
    const pngPath = captures.get(`${id}/inventory.png`);
    const jpgPath = captures.get(`${id}/inventory.jpg`);
    if (!baselinePath || !normalPath || !pngPath || !jpgPath)
      throw new Error(`${id} 的验证输出不完整。`);
    const [pngMetadata, jpgMetadata, normalDifference, difference] =
      await Promise.all([
        sharp(pngPath).metadata(),
        sharp(jpgPath).metadata(),
        comparePngs(baselinePath, normalPath, []),
        comparePngs(baselinePath, pngPath, plansByTemplate[id]),
      ]);
    if (
      pngMetadata.width !== template.width ||
      pngMetadata.height !== template.height
    ) {
      throw new Error(`${id} 的预览尺寸改变。`);
    }
    if (
      jpgMetadata.width !== template.width ||
      jpgMetadata.height !== template.height
    ) {
      throw new Error(`${id} 的 JPG 尺寸改变。`);
    }
    if (!difference.changedPixels || difference.changedOutsideOverlay) {
      throw new Error(
        `${id} 的像素变化超出库存提示区域：${JSON.stringify(difference)}`,
      );
    }
    if (normalDifference.changedPixels) {
      throw new Error(
        `${id} 的 normal 状态改变了原图：${JSON.stringify(normalDifference)}`,
      );
    }
    const badgeTexts = plansByTemplate[id].flatMap((plan) =>
      plan.badges.map((badge) => badge.text),
    );
    if (
      !badgeTexts.every((text) =>
        /^(?:.+″ · )?(?:Low Stock|Restocking)$/.test(text),
      )
    ) {
      throw new Error(
        `${id} 含有非指定英文提示：${JSON.stringify(badgeTexts)}`,
      );
    }
    if (
      !badgeTexts.some((text) =>
        /^\d+″ · (?:Low Stock|Restocking)$/.test(text),
      )
    ) {
      throw new Error(`${id} 没有生成只指向对应单尺寸的英文提示。`);
    }
    if (!badgeTexts.some((text) => text.includes('Low Stock'))) {
      throw new Error(`${id} 没有生成 Low Stock 提示。`);
    }
    if (badgeTexts.some((text) => text.includes('No stock'))) {
      throw new Error(`${id} 不应生成 No stock 提示。`);
    }
    results.push({
      templateId: id,
      width: template.width,
      height: template.height,
      badgeTexts,
      badgeCount: plansByTemplate[id].reduce(
        (sum, plan) => sum + plan.badges.length,
        0,
      ),
      ...difference,
      normalChangedPixels: normalDifference.changedPixels,
      previewPng: keepOutput ? pngPath : undefined,
      outputJpg: keepOutput ? jpgPath : undefined,
    });
  }
  process.stdout.write(
    `${JSON.stringify({ passed: true, tempDir: keepOutput ? tempDir : undefined, cases: results }, null, 2)}\n`,
  );
} finally {
  await stopBrowser(browser);
  if (server) await new Promise((resolve) => server.close(resolve));
  if (!keepOutput)
    await rm(tempDir, {
      recursive: true,
      force: true,
      maxRetries: 20,
      retryDelay: 150,
    });
}
