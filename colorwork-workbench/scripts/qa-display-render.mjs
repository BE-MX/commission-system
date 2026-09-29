import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { initializeCanvas, readPsd } from 'ag-psd';

const vite = await createServer({
  configFile: false,
  resolve: { alias: { '@': process.cwd() } },
  server: { middlewareMode: true },
});

try {
  const { activeMasterSelection } = await vite.ssrLoadModule('/lib/catalog.ts');
  const { activeColorsFor, layoutFor, paintPoster } = await vite.ssrLoadModule('/lib/poster.ts');
  const { createInventoryOverlayPlan } = await vite.ssrLoadModule('/lib/inventory-overlay.ts');
  const { computeSourceChanges } = await vite.ssrLoadModule('/lib/source-diff.ts');
  const card = {
    entryId: 'source:photo:candidate-859', colorId: 'source-color-048a5346', kind: 'display',
    lengths: [], hot: false, section: null, order: 0,
    geometry: { swatch: [864, 56, 988, 180], colorLabel: null, sizeLabel: null, hotBadge: null },
  };
  const selection = activeMasterSelection([card]);
  const template = {
    id: '20g-genius-weft-regular', width: 1000, height: 1500,
    baseUrl: '/base.png', referenceUrl: '', dynamicBounds: [0, 0, 1000, 1500],
    initialCards: [card], legacyColors: [], sections: [],
  };
  const colors = [{ id: card.colorId, code: '#048A5346', image: '/photo.png' }];
  const inventory = { [card.entryId]: { 16: 'restocking' } };
  assert.equal(selection.length, 1, 'display image must remain visible');
  assert.equal(activeColorsFor(colors, template, selection).length, 1);
  assert.equal(createInventoryOverlayPlan({ x: 864, y: 56, size: 124 }, card, inventory).badges.length, 0);
  const diff = computeSourceChanges({ ...template, initialCards: [] }, colors, [], {
    template: { ...template, initialCards: [{ ...card, candidateId: 'display-candidate', colorCode: '#048A5346', matchedEntryId: null }] },
  });
  assert.equal(diff.added.length, 0, 'display images must not count as added stock colors');

  const calls = [];
  const context = {
    fillRect: () => {}, save: () => {}, restore: () => {}, strokeRect: () => {}, scale: () => {},
    drawImage: (image, ...args) => calls.push({ src: image.src, args }),
    fillText: (value) => calls.push({ text: value }),
    getImageData: (_x, _y, width, height) => ({ data: new Uint8ClampedArray(width * height * 4), width, height }),
  };
  globalThis.Image = class {
    width = 124; height = 124;
    set src(value) { this._src = value; queueMicrotask(() => this.onload?.()); }
    get src() { return this._src; }
  };
  const fakeDocument = { createElement: () => ({ width: 0, height: 0, getContext: () => context }) };
  Object.assign(globalThis, { document: fakeDocument });
  initializeCanvas((width, height) => ({ width, height, getContext: () => context }));
  await paintPoster(colors, template, selection, inventory);
  const photo = calls.find((call) => call.src?.endsWith('/photo.png'));
  assert.deepEqual(photo?.args, [864, 56, 124, 124], 'photo must stay in the upper-right slot');
  assert.equal(calls.some((call) => call.text?.includes('16') || call.text?.includes('Restocking')), false);
  calls.length = 0;
  await paintPoster(colors, { ...template, referenceUrl: '/reference.jpg' }, selection, inventory);
  assert.equal(calls.some((call) => call.src?.endsWith('/reference.jpg')), true, 'original JPG with its photo must remain');
  assert.equal(calls.some((call) => call.text?.includes('16') || call.text?.includes('Restocking')), false);
  calls.length = 0;
  await paintPoster(colors, { ...template, referenceUrl: '/reference.jpg', initialCards: [{ ...card, kind: 'stock', lengths: [16] }] }, selection, inventory);
  assert.equal(calls.some((call) => call.src?.endsWith('/photo.png')), true, 'a type change must repaint instead of retaining stale reference labels');
  assert.equal(calls.some((call) => call.text?.includes('16') || call.text?.includes('Restocking')), false);
  const secondCard = { ...card, entryId: 'second-photo', colorId: 'second-color', order: 1,
    geometry: { ...card.geometry, swatch: [700, 56, 824, 180] } };
  const reordered = activeColorsFor([...colors, { id: 'second-color', code: '#second', image: '/second.png' }],
    { ...template, initialCards: [card, secondCard] },
    [{ ...card, order: 1 }, { ...secondCard, order: 0 }]);
  assert.deepEqual(layoutFor({ ...template, initialCards: [card, secondCard] }, reordered).map((slot) => slot.x),
    [864, 700], 'changing display order must swap the output positions');
  const { createLayeredPsd } = await vite.ssrLoadModule('/lib/psd-export.ts');
  const psdBlob = await createLayeredPsd(colors, template, selection, { width: 1000, height: 1500 }, inventory);
  const parsedPsd = readPsd(new Uint8Array(await psdBlob.arrayBuffer()), { skipLayerImageData: true, skipCompositeImageData: true });
  const layers = parsedPsd.children[0].children[0].children.map((layer) => layer.name);
  assert.deepEqual(layers, ['展示图片（可替换）'], 'PSD must retain the editable photo layer without labels');
  console.log('20g Genius Weft display render: upper-right photo retained in JPG and PSD; no size, Restocking, Low Stock, or Hot label');
} finally {
  await vite.close();
}
