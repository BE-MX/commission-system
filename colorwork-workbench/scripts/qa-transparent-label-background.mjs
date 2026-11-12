import assert from 'node:assert/strict';
import { createServer } from 'vite';

const vite = await createServer({ configFile: false,
  resolve: { alias: { '@': process.cwd() } }, server: { middlewareMode: true } });
try {
  const { paintPoster } = await vite.ssrLoadModule('/lib/poster.ts');
  const { verifiedSourceBackground } = await vite.ssrLoadModule('/lib/server/source-background.ts');
  const { CATALOG } = await vite.ssrLoadModule('/lib/server/catalog.ts');
  const verified = (await import('../lib/verified-source-backgrounds.json', { with: { type: 'json' } })).default;
  for (const certificate of verified) {
    const source = CATALOG.templates.find((item) => item.id === certificate.templateId);
    const manifest = [{ name: 'reference.jpg', sha256: certificate.referenceSha256 },
      { name: 'base.png', sha256: certificate.sourceBaseSha256 }];
    assert.equal(verifiedSourceBackground(source, JSON.stringify(manifest)), source.baseUrl);
    assert.equal(verifiedSourceBackground({ ...source, width: source.width + 1 }, JSON.stringify(manifest)), undefined);
    manifest[0].sha256 = 'a-new-jpg-even-if-only-one-title-changed';
    assert.equal(verifiedSourceBackground(source, JSON.stringify(manifest)), undefined, 'new titles must not inherit old artwork');
    assert.equal(verifiedSourceBackground(source, '{}'), undefined, 'legacy unsealed manifests remain unverified');
  }
  const images = new Map();
  const contexts = [];
  globalThis.Image = class {
    width = 200; height = 200;
    set src(value) {
      this._src = value;
      Object.assign(this, images.get(value.replace('/api/colorwork/workbench', '')));
      queueMicrotask(() => this.failed ? this.onerror?.() : this.onload?.());
    }
    get src() { return this._src; }
  };
  globalThis.document = { createElement() {
    const element = { width: 200, height: 200 };
    const context = { fills: [], drawings: [], texts: [], image: null,
      save() {}, restore() {}, strokeRect() {},
      fillRect(...args) { this.fills.push(args); },
      drawImage(image) { this.drawings.push(image.src); this.image = image; },
      fillText(text) { this.texts.push(text); },
      measureText: (text) => ({ width: text.length * 6 }),
      getImageData() {
        const data = new Uint8ClampedArray(element.width * element.height * 4);
        const rgb = this.image?.rgb ?? [180, 190, 200];
        for (let index = 0; index < data.length; index += 4) data.set([...rgb, 255], index);
        if (this.image?.hole) data[(100 * element.width + 40) * 4 + 3] = 0;
        return { data, width: element.width, height: element.height };
      },
    };
    contexts.push(context); element.getContext = () => context; return element;
  } };
  const card = { entryId: 'e', colorId: 'c', kind: 'stock', lengths: [18, 22],
    hot: false, section: null, order: 0,
    geometry: { swatch: [20, 20, 80, 80], colorLabel: [40, 85, 60, 95], sizeLabel: [35, 100, 65, 110] } };
  const colors = [{ id: 'c', code: '#30', image: '/photo.png' }];
  function template(id) {
    return { id, width: 200, height: 200, referenceUrl: `/${id}-reference.jpg`,
      baseUrl: `/${id}-source-base.png`, cleanBaseUrl: `/${id}-clean.png`,
      initialCards: [card], legacyColors: [], sections: [], dynamicBounds: [0, 0, 200, 200] };
  }
  const selected = [{ ...card, lengths: [18, 20, 22, 24] }];
  const good = template('good');
  const output = await paintPoster(colors, good, selected);
  const painted = output.getContext('2d');
  assert.ok(painted.drawings.some((src) => src.endsWith('/good-clean.png')), 'redraw must use the real texture background');
  assert.equal(painted.fills.length, 1, 'only flatten the canvas once; do not paint white label rectangles');
  assert.ok(painted.texts.some((text) => text.includes('24')), 'new sizes must remain visible');

  const hole = template('transparent-hole'); images.set('/transparent-hole-clean.png', { hole: true });
  await assert.rejects(paintPoster(colors, hole, selected), /底图.*不完整/,
    'clearing labels to transparency is not a replacement for restoring the texture');
  const resized = template('resized'); images.set('/resized-clean.png', { width: 201 });
  await assert.rejects(paintPoster(colors, resized, selected), /底图.*尺寸/);
  const ordinaryUser = template('base-only'); images.set('/base-only-reference.jpg', { failed: true });
  images.set('/base-only-source-base.png', { hole: true });
  await paintPoster(colors, ordinaryUser, selected);
  const newSource = { ...template('new-source'), cleanBaseUrl: undefined, width: 220, height: 240 };
  images.set('/new-source-reference.jpg', { width: 220, height: 240, rgb: [100, 150, 200] });
  images.set('/new-source-source-base.png', { width: 220, height: 240, hole: true });
  const newSourceOutput = await paintPoster(colors, newSource, selected);
  assert.ok(newSourceOutput.getContext('2d').drawings.some((src) => src.endsWith('/new-source-reference.jpg')));
  assert.equal(newSourceOutput.getContext('2d').drawings.some((src) => src.endsWith('/new-source-clean.png')), false);
  const unchanged = await paintPoster(colors, template('unchanged'), [card]);
  assert.equal(unchanged.getContext('2d').texts.length, 0, 'unchanged source composition must stay intact');
  const thumbnail = { ...template('thumbnail'), cleanBaseUrl: undefined, baseUrl: '/api/runtime-assets/templates/static/base.png' };
  images.set('/thumbnail-reference.jpg', { width: 84, height: 84 });
  await paintPoster(colors, thumbnail, selected);
  console.log('PASS texture redraw: four immutable source bindings; no white panels for verified art; base-only access and new source contracts preserved');
} finally { await vite.close(); }
