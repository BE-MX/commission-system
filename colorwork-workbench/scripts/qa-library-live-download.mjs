import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const catalog = JSON.parse(readFileSync(resolve(root, 'lib/generated-catalog.json'), 'utf8'));
const user = { role: 'member', displayName: 'Download member', views: ['library'] };

// Execute actual route/component bodies with controlled IO and hook state; no production services.
function load(file, mocks = {}, globals = {}) {
  const filename = resolve(root, file);
  const source = ts.transpileModule(readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(source, {
    module, exports: module.exports, Response, Request, Error, console, URL, Blob, Intl, Date,
    require: (name) => {
      if (name in mocks) return mocks[name];
      if (name.startsWith('@/')) return load(name.slice(2) + '.ts', mocks, globals);
      return require(name);
    }, ...globals,
  }, { filename });
  return module.exports;
}

function routes(views, failValidation = false) {
  const calls = [];
  const mocks = {
    '@/lib/server/auth': {
      requireView: async (view) => {
        if (views === null) throw new Error('UNAUTHORIZED');
        if (!views.includes(view)) throw new Error('VIEW_FORBIDDEN');
        return user;
      },
      authErrorResponse: (error) => Response.json({ error: error.message }, { status: error.message === 'UNAUTHORIZED' ? 401 : 403 }),
    },
    '@/lib/server/master-inventory': {
      getInventorySnapshot: async (...args) => { calls.push(args); return { templateId: args[0], specs: [{ status: 'restocking' }] }; },
      updateInventory: async () => { throw new Error('Unexpected write'); },
      validateInventoryForGeneration: async (...args) => {
        calls.push(args);
        if (failValidation) throw new Error('GENERATION_REVISION_CONFLICT');
        return { valid: true };
      },
      masterInventoryErrorResponse: (error) => error.message === 'GENERATION_REVISION_CONFLICT'
        ? Response.json({ code: error.message }, { status: 409 }) : null,
    },
  };
  return {
    calls,
    snapshot: load('app/api/templates/[id]/inventory/route.ts', mocks),
    validation: load('app/api/templates/[id]/inventory/validate/route.ts', mocks),
    editor: load('app/api/inventory/[templateId]/route.ts', mocks),
  };
}
const context = { params: Promise.resolve({ id: 'tape-hair-super' }) };
const payload = { expectedMasterRevision: 3, expectedInventoryRevision: 5, expectedSourceVersionId: 'source-1', specIds: ['spec-1'] };
const validationRequest = () => new Request('http://localhost/validate', { method: 'POST', body: JSON.stringify(payload) });

test('library-only account reads live data and validates exports without gaining inventory writes', async () => {
  const { snapshot, validation, editor, calls } = routes(['library']);
  const response = await snapshot.GET(new Request('http://localhost/inventory'), context);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).specs[0].status, 'restocking');
  assert.equal(response.headers.get('cache-control'), 'private, no-store');
  assert.equal((await validation.POST(validationRequest(), context)).status, 200);
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1][2])), payload);
  assert.equal(calls[1][1], user);
  assert.equal(snapshot.PATCH, undefined);
  assert.equal((await editor.PATCH(validationRequest(), { params: Promise.resolve({ templateId: 'tape-hair-super' }) })).status, 403);
});

test('unauthenticated and non-library accounts cannot read or validate library exports', async () => {
  for (const [views, status] of [[null, 401], [['inventory'], 403]]) {
    const { snapshot, validation, calls } = routes(views);
    assert.equal((await snapshot.GET(new Request('http://localhost/inventory'), context)).status, status);
    assert.equal((await validation.POST(validationRequest(), context)).status, status);
    assert.equal(calls.length, 0);
  }
});

test('malformed requests and stale export versions remain blocked', async () => {
  const { validation } = routes(['library'], true);
  assert.equal((await validation.POST(new Request('http://localhost/validate', { method: 'POST', body: '{' }), context)).status, 400);
  const stale = await validation.POST(validationRequest(), context);
  assert.equal(stale.status, 409);
  assert.equal((await stale.json()).code, 'GENERATION_REVISION_CONFLICT');
});

function nodes(element) {
  if (!element || typeof element !== 'object') return [];
  const children = [element.props?.children].flat(Infinity);
  return [element, ...children.flatMap(nodes)];
}
function label(element) {
  if (typeof element === 'string') return element;
  if (!element || typeof element !== 'object') return '';
  return [element?.props?.children].flat(Infinity).map((child) => typeof child === 'string' ? child : label(child)).join('');
}
function hooks(initials = new Map()) {
  let index = 0;
  const updates = new Map();
  return {
    updates,
    react: {
      useState: (initial) => { const key = index++; return [initials.has(key) ? initials.get(key) : initial, (value) => updates.set(key, value)]; },
      useRef: (value) => ({ current: value }), useMemo: (fn) => fn(), useCallback: (fn) => fn, useEffect: () => {},
    },
  };
}

test('library lists only templates and selects the clicked product for live preview', () => {
  const state = hooks();
  const { FileLibrary } = load('components/file-library.tsx', {
    react: state.react, '@/components/inventory-board': { InventoryBoard: () => null },
  });
  const tree = FileLibrary({ user, catalog });
  const elements = nodes(tree);
  assert.ok(!label(tree).includes('业务修改图'));
  assert.ok(label(tree).includes('库存图JPG'));
  const liveButtons = elements.filter((e) => e.type === 'button' && label(e) === '下载实时库存图JPG');
  const originals = elements.filter((e) => e.type === 'a' && label(e) === '下载原始库存图JPG');
  assert.equal(liveButtons.length, 23);
  assert.equal(originals.length, 23);
  liveButtons[7].props.onClick();
  assert.equal(state.updates.get(3).template.id, catalog.templates[7].id);
  assert.equal(state.updates.get(3).kind, 'live');
  assert.equal(originals[7].props.href, `/api/colorwork/workbench/api/templates/${catalog.templates[7].id}/download/jpg`);
});

test('preview-only board uses shared painter and validates before and after download without writing artifacts', async () => {
  const item = catalog.templates[7];
  const card = item.initialCards[0];
  const snapshot = { templateId: item.id, template: item, colors: catalog.colors, selection: [card],
    specs: card.lengths.map((length) => ({ specId: `spec-${length}`, entryId: card.entryId, colorId: card.colorId, length, status: 'restocking' })),
    availableLengths: card.lengths, sourceVersion: { id: 'source-1', number: 1 }, masterRevision: 3, inventoryRevision: 5,
  };
  const state = hooks(new Map([[1, snapshot], [5, false], [8, true]]));
  const calls = [];
  const anchor = { click: () => calls.push('download') };
  const { InventoryBoard } = load('components/inventory-board.tsx', {
    react: state.react, '@/components/ui/select': {},
    '@/lib/workbench-url': { workbenchFetch: async (path, init) => { calls.push({ path, init }); return Response.json({ valid: true }); } },
    '@/lib/poster': { paintPoster: async (...args) => {
      calls.push({ paint: args });
      return { toBlob: (callback) => callback(new Blob(['jpg'], { type: 'image/jpeg' })) };
    } },
  }, { document: { createElement: () => anchor }, window: { setTimeout: () => {} }, URL: { createObjectURL: () => 'blob:download' } });
  const tree = InventoryBoard({ user, catalog, previewOnly: true, initialTemplateId: item.id });
  assert.ok(!label(tree).includes('维护当前库存与补货状态'));
  assert.ok(!label(tree).includes('保存成品并下载'));
  const button = nodes(tree).find((e) => e.type === 'button' && label(e) === '下载实时库存图JPG');
  assert.equal(button.props.disabled, false);
  button.props.onClick();
  // onClick intentionally dispatches an async operation without returning its promise.
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(calls.length, 4);
  assert.equal(calls[0].path, `/api/templates/${item.id}/inventory/validate`);
  assert.equal(calls[2].path, calls[0].path);
  assert.equal(calls[1].paint[1].id, item.id);
  assert.equal(calls[1].paint[3][card.entryId][card.lengths[0]], 'restocking');
  assert.equal(calls[3], 'download');
  assert.ok(anchor.download.endsWith('.jpg'));
});
