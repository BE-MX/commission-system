import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { viewController } from './helpers/viewController.mjs'
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }
function colorApi(client) {
  const source = readFileSync(new URL('../src/api/color.js', import.meta.url), 'utf8')
    .replace(/import[^\n]+\n/, '').replace(/export /g, '')
  return new Function('colorClient', source + '\nreturn { getAllColorsForSelection, getColorFilterOptions, getBlendFilterOptions };')(client)
}

test('color selectors gather all legal 200-row pages with the same abort signal and no global toast', async () => {
  const calls = [], controller = new AbortController()
  const api = colorApi({ get: async (path, config) => {
    calls.push(config); assert.equal(path, '/colors'); assert.equal(config.signal, controller.signal)
    const start = (config.params.page - 1) * 200
    return { ok: true, data: { total: 401, items: Array.from({ length: Math.min(200, 401 - start) }, (_, index) => ({ id: start + index + 1 })) } }
  } })
  const items = await api.getAllColorsForSelection({ signal: controller.signal, suppressToast: true })
  assert.equal(items.length, 401); assert.deepEqual(calls.map(call => call.params), [{ page: 1, page_size: 200 }, { page: 2, page_size: 200 }, { page: 3, page_size: 200 }])
  assert.ok(calls.every(call => call.suppressToast && call.showLoading === false))
})

test('incomplete or cancelled color catalog cannot become successful partial options', async () => {
  const api = colorApi({ get: async (_, config) => ({ data: { total: 201, items: config.params.page === 1 ? [{ id: 1 }] : [] } }) })
  await assert.rejects(api.getAllColorsForSelection(), /未完整读取/)
  const duplicate = colorApi({ get: async (_, config) => ({ data: { total: 201, items: config.params.page === 1 ? Array.from({ length: 200 }, (_, index) => ({ id: index + 1 })) : [{ id: 200 }] } }) })
  await assert.rejects(duplicate.getAllColorsForSelection(), /未完整读取/)
  const controller = new AbortController(); let calls = 0
  const cancelled = colorApi({ get: async () => { calls++; controller.abort(); return { data: { total: 201, items: [{ id: 1 }] } } } })
  await assert.rejects(cancelled.getAllColorsForSelection({ signal: controller.signal }), { name: 'AbortError' })
  assert.equal(calls, 1)
})

test('blend catalog and filter options fail independently, retain successful options and reject late catalogs', async t => {
  let fail = true, slow; const { vm } = viewController(t, '../../src/views/color/BlendView.vue', 'paletteResource,paletteOptions,loadPaletteOptions,filterResource,loadFilterOptions', {
    '@/api/color': {
      getBlendFilterOptions: async config => { assert.equal(config.suppressToast, true); if (fail) throw Error('filter offline'); return { ok: true, data: { sources: ['leshine'], blend_types: ['piano'] } } },
      getAllColorsForSelection: async config => { assert.ok(config.signal); if (slow) return slow.promise; return [{ id: 1 }] },
    },
  })
  assert.equal(await vm.loadFilterOptions(), false); assert.equal(await vm.loadPaletteOptions(), true)
  assert.deepEqual(vm.paletteOptions.value, [{ id: 1 }]); assert.equal(vm.filterResource.hasLoaded.value, false)
  fail = false; await vm.loadFilterOptions(); fail = true; await vm.loadFilterOptions()
  assert.equal(vm.filterResource.data.value.sources[0], 'leshine'); assert.equal(vm.filterResource.isStale.value, true)
  const old = deferred(); slow = old; const pending = vm.loadPaletteOptions(); slow = null; await vm.loadPaletteOptions()
  old.resolve([{ id: 999 }]); assert.equal(await pending, false)
  assert.deepEqual(vm.paletteOptions.value, [{ id: 1 }])
})

test('palette filter options use successful actual envelopes and swatch options recover first/stale failures', async t => {
  const palette = viewController(t, '../../src/views/color/PaletteView.vue', 'filterResource,loadFilterOptions', {
    '@/api/color': { getColorFilterOptions: async () => ({ ok: true, data: { color_families: ['brown'], sources: [], luminance_levels: [] } }) },
  }).vm
  await palette.loadFilterOptions(); assert.equal(palette.filterResource.data.value.color_families[0], 'brown')
  let fail = true
  const swatch = viewController(t, '../../src/views/color/SwatchGenerator.vue', 'colorResource,colorOptions,loadColorOptions', {
    '@/api/color': { getAllColorsForSelection: async () => { if (fail) throw Error('color offline'); return [{ id: 5, industry_code: '#5', display_name: 'brown' }] } },
  }).vm
  assert.equal(await swatch.loadColorOptions(), false); assert.equal(swatch.colorResource.hasLoaded.value, false)
  fail = false; await swatch.loadColorOptions(); fail = true; await swatch.loadColorOptions()
  assert.equal(swatch.colorOptions.value[0].value, 5); assert.equal(swatch.colorResource.isStale.value, true)
})
