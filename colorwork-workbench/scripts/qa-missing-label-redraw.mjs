import assert from 'node:assert/strict';
import { createServer } from 'vite';

const vite = await createServer({
  configFile: false,
  resolve: { alias: { '@': process.cwd() } },
  server: { middlewareMode: true },
});

try {
  const { paintPoster } = await vite.ssrLoadModule('/lib/poster.ts');
  const cases = [
    { name: '20g #6 size', field: 'sizeLabel', oldBounds: [833, 357, 969, 371],
      swatch: [832, 189, 970, 326], colorLabel: [891, 338, 909, 351], sizeLabel: null,
      peer: { swatch: [673, 189, 810, 326], colorLabel: [732, 338, 750, 350], sizeLabel: [673, 357, 809, 371] } },
    { name: 'Butterfly #8 size', field: 'sizeLabel', oldBounds: [851, 357, 954, 371],
      swatch: [834, 189, 971, 326], colorLabel: [893, 338, 911, 351], sizeLabel: null,
      peer: { swatch: [674, 189, 811, 326], colorLabel: [732, 338, 750, 350], sizeLabel: [709, 357, 773, 371] } },
    { name: 'Butterfly Cookies Cream color', field: 'colorLabel', oldBounds: [843, 1161, 963, 1175],
      swatch: [835, 1013, 971, 1150], colorLabel: null, sizeLabel: [851, 1180, 954, 1194],
      peer: { swatch: [674, 1013, 811, 1150], colorLabel: [691, 1161, 793, 1175], sizeLabel: [708, 1180, 776, 1194] } },
  ];

  for (const fixture of cases) {
    const cards = [fixture.peer, fixture].map((geometry, index) => ({
      entryId: `entry-${index}`, colorId: `color-${index}`, kind: 'stock',
      lengths: [18, 22], hot: false, section: null, order: index,
      geometry: { ...geometry, hotBadge: null },
    }));
    const colors = cards.map((card) => ({ id: card.colorId, code: '#test', image: `/photo-${card.colorId}.png` }));
    const template = { id: fixture.name, width: 1000, height: 1600,
      referenceUrl: `/reference-${fixture.name}.jpg`, baseUrl: '/base.png', cleanBaseUrl: '/base.png',
      initialCards: cards, legacyColors: [], sections: [], dynamicBounds: [0, 180, 1000, 1400] };
    const [left, top, right, bottom] = fixture.oldBounds;
    const pixels = [[left, top], [right - 1, top], [left, bottom - 1], [right - 1, bottom - 1], [(left + right) / 2, (top + bottom) / 2]];
    let oldInk = new Set();
    const textCalls = [];
    const context = {
      save() {}, restore() {}, strokeRect() {},
      measureText: (value) => ({ width: value.length * 7 }),
      drawImage(image) {
        if (image.src.includes('reference-')) oldInk = new Set(pixels.map((_, index) => index));
        else if (image.src.endsWith('/base.png')) oldInk.clear();
      },
      getImageData() {
        const data = new Uint8ClampedArray(template.width * template.height * 4);
        data.fill(255);
        return { data, width: template.width, height: template.height };
      },
      fillRect(x, y, width, height) {
        for (const index of oldInk) {
          const [px, py] = pixels[index];
          if (px >= x && px < x + width && py >= y && py < y + height) oldInk.delete(index);
        }
      },
      fillText: (text, x, y) => textCalls.push({ text, x, y }),
    };
    globalThis.Image = class {
      width = 1000; height = 1600;
      set src(value) { this._src = value; queueMicrotask(() => this.onload?.()); }
      get src() { return this._src; }
    };
    globalThis.document = { createElement: () => ({ width: 0, height: 0, getContext: () => context }) };
    await paintPoster(colors, template, cards);
    assert.equal(oldInk.size, pixels.length, 'unchanged reference must remain intact');
    assert.equal(textCalls.length, 0, 'unchanged reference must not redraw labels');

    const selection = cards.map((card, index) => ({ ...card, lengths: index ? [18, 20, 22] : card.lengths }));
    await paintPoster(colors, template, selection);
    assert.equal(oldInk.size, 0, `${fixture.name}: original label ink must be removed before repaint`);
    const label = textCalls.find((call) => call.x > 830 && (fixture.field === 'sizeLabel' ? call.text.includes('20') : call.text === '#test'));
    assert.ok(label, 'updated label must still be drawn');
    assert.ok(label.y >= top && label.y <= bottom, `${fixture.name}: replacement must align with the original row`);
    console.log(`PASS ${fixture.name}: old ink cleared and label aligned`);
  }
} finally {
  await vite.close();
}
