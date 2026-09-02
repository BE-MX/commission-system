import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  attributeOptions,
  clearNonstandardAttributes,
  normalizeItemAttrs,
  requiredAttributeFields,
  routeForItem,
  validateItemAttributes,
  visibleAttributeFields,
} from '../src/views/domestic/domesticAttributeRules.js'
import { createLatestRequestRunner } from '../src/views/domestic/composables/latestRequest.js'

const options = {
  attr_dicts: {
    cap: {
      craft: 'domestic_cap_craft',
      net_color: 'domestic_cap_net_color',
      size: 'domestic_cap_size',
      length: 'domestic_cap_length',
      density: 'domestic_cap_density',
      hair_style_series: 'domestic_cap_hair_style_series',
    },
    piece: {
      craft: 'domestic_piece_craft_size',
      length: 'domestic_piece_length',
    },
  },
  special_attr_dicts: {
    cap: {
      craft: 'domestic_cap_craft_special',
      net_color: 'domestic_cap_net_color_special',
      size: 'domestic_cap_size_special',
      length: 'domestic_cap_length_special',
      density: 'domestic_cap_density_special',
      hair_style_series: 'domestic_cap_hair_style_series_special',
    },
    piece: {
      craft: 'domestic_piece_craft_size_special',
      length: 'domestic_piece_length_special',
    },
  },
  standard_values: {
    domestic_cap_craft: ['递旋'],
    domestic_cap_net_color: ['紫网全头套'],
    domestic_cap_size: ['M'],
    domestic_cap_length: ['15厘米', '20厘米'],
    domestic_cap_density: ['65%'],
    domestic_cap_hair_style_series: ['直发'],
    domestic_piece_craft_size: ['U型13*15'],
    domestic_piece_length: ['20'],
  },
  special_values: {
    domestic_cap_craft_special: ['手工递针'],
    domestic_cap_length_special: ['18'],
  },
  default_routes: {
    cap: { id: 8, name: '头套网帽（递针）', step_count: 4 },
    piece: { id: 9, name: '发片网底（递针）', step_count: 3 },
  },
}

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('头套仅在 15cm 时显示发量', () => {
  assert.deepEqual(visibleAttributeFields({ product_type: 'cap', length: '15厘米' }), [
    'craft', 'length', 'net_color', 'size', 'hair_style_series', 'density',
  ])
  assert.deepEqual(visibleAttributeFields({ product_type: 'cap', length: '20厘米' }), [
    'craft', 'length', 'net_color', 'size', 'hair_style_series',
  ])
})

test('发片只显示合并工艺尺寸和发长', () => {
  assert.deepEqual(visibleAttributeFields({ product_type: 'piece', length: '20' }), [
    'craft', 'length',
  ])
})

test('网帽颜色显示但不强制填写', () => {
  assert.deepEqual(requiredAttributeFields({ product_type: 'cap', length: '15厘米' }), [
    'craft', 'length', 'size', 'hair_style_series', 'density',
  ])
  assert.deepEqual(requiredAttributeFields({ product_type: 'cap', length: '20厘米' }), [
    'craft', 'length', 'size', 'hair_style_series',
  ])
})

test('特单选项合并标准值和特单值，普货只返回标准值', () => {
  assert.deepEqual(attributeOptions(options, 'normal', 'cap', 'craft'), ['递旋'])
  assert.deepEqual(attributeOptions(options, 'special', 'cap', 'craft'), ['递旋', '手工递针'])
})

test('特单切回普货只清除非标准值并保留标准值', () => {
  const attrs = {
    product_type: 'cap', craft: '手工递针', length: '15厘米', net_color: '紫网全头套',
    size: 'M', density: '65%', hair_style_series: '直发',
  }

  const removedFields = clearNonstandardAttributes(attrs, options)

  assert.deepEqual(attrs, {
    product_type: 'cap', craft: '', length: '15厘米', net_color: '紫网全头套',
    size: 'M', density: '65%', hair_style_series: '直发',
  })
  assert.deepEqual(removedFields, ['craft'])
})

test('属性校验会 trim，把空白视为空并报告长度上限', () => {
  const blank = {
    product_type: 'piece', craft: '   ', length: ' 20厘米 ',
  }
  assert.equal(validateItemAttributes(blank), '工艺/尺寸不能为空')

  const overlongCraft = {
    product_type: 'piece', craft: '工'.repeat(65), length: '20厘米',
  }
  assert.equal(validateItemAttributes(overlongCraft), '工艺/尺寸最多输入64个字符')

  const overlong = {
    product_type: 'cap', craft: '递旋', length: '20厘米', size: 'M',
    net_color: '', density: '', hair_style_series: ` ${'直'.repeat(65)} `,
  }
  assert.equal(validateItemAttributes(overlong), '发型系列最多输入64个字符')
})

test('载荷不发送非当前产品字段或非 15cm 发量', () => {
  assert.deepEqual(normalizeItemAttrs({
    product_type: 'cap', craft: '递旋', length: '20厘米', net_color: '紫网全头套',
    size: 'M', density: '65%', hair_style_series: '直发',
  }), {
    product_type: 'cap', craft: '递旋', length: '20厘米', net_color: '紫网全头套',
    size: 'M', hair_style_series: '直发',
  })
  assert.deepEqual(normalizeItemAttrs({
    product_type: 'piece', craft: 'U型13*15', length: '20', net_color: '紫网全头套',
    size: 'M', density: '65%', hair_style_series: '直发',
  }), {
    product_type: 'piece', craft: 'U型13*15', length: '20',
  })
})

test('载荷统一 trim 可见属性并丢弃空白选填值', () => {
  assert.deepEqual(normalizeItemAttrs({
    product_type: 'cap', craft: ' 递旋 ', length: ' 20厘米 ', net_color: '   ',
    size: ' M ', density: '65%', hair_style_series: ' 直发 ',
  }), {
    product_type: 'cap', craft: '递旋', length: '20厘米', size: 'M',
    hair_style_series: '直发',
  })
})

test('特单自定义工艺没有精确映射时预览产品默认路线', () => {
  const item = { attrs: { product_type: 'cap', craft: '手工递针' } }
  assert.deepEqual(routeForItem(item, 'special', [], options.default_routes), {
    route_id: 8, route_name: '头套网帽（递针）', step_count: 4, is_default: true,
  })
  assert.equal(routeForItem(item, 'normal', [], options.default_routes), null)
})

test('精确工艺映射优先于特单默认路线', () => {
  const item = { attrs: { product_type: 'cap', craft: ' 递旋 ' } }
  const mappings = [{ product_type: 'cap', craft: '递旋', route_id: 3, route_name: '递旋路线' }]
  assert.deepEqual(routeForItem(item, 'special', mappings, options.default_routes), mappings[0])
})

test('特单中的标准工艺未配映射时不假报默认路线', () => {
  const item = { attrs: { product_type: 'cap', craft: '递旋' } }
  assert.equal(routeForItem(item, 'special', [], options.default_routes, ['递旋']), null)
})

test('下单、列表和产品页保持新属性合约', () => {
  const createView = read('../src/views/domestic/DomesticOrderCreate.vue')
  const createLogic = read('../src/views/domestic/composables/useDomesticOrderCreate.js')
  const ordersView = read('../src/views/domestic/DomesticOrders.vue')
  const ordersLogic = read('../src/views/domestic/composables/useDomesticOrders.js')
  const productsView = read('../src/views/domestic/DomesticProducts.vue')

  assert.match(createView, /v-model="form\.order_category"/)
  assert.match(createView, /v-model="form\.order_type"/)
  assert.match(createView, /v-model="form\.order_channel"/)
  assert.match(createView, /:allow-create="form\.order_category === 'special'"/)
  assert.match(createView, /可直接输入新选项/)
  assert.doesNotMatch(createView, /v-model="form\.order_(?:type|channel)"[\s\S]{0,160}allow-create/)
  assert.match(createView, /发片工艺\/尺寸/)
  assert.match(createView, /visibleFields\(item\)\.includes\('density'\)/)
  assert.match(createLogic, /buildCreateItems\(form\.items, normalizeItemAttrs\)/)
  assert.match(createLogic, /buildQuoteRequest\(form, normalizeItemAttrs\)/)
  assert.match(createLogic, /ElMessage\.info/)
  assert.match(createLogic, /order_type: ''/)
  assert.match(createLogic, /order_channel: ''/)
  assert.doesNotMatch(createLogic, /form\.order_(?:type|channel) \|\|=/)

  for (const field of ['order_category', 'order_type', 'order_channel']) {
    assert.match(ordersView, new RegExp(`searchForm\\.${field}`))
    assert.match(ordersLogic, new RegExp(`'${field}'`))
  }
  assert.match(productsView, /label="工艺\/尺寸"/)
  assert.match(productsView, /prop="hair_style_series"/)
  assert.match(productsView, /row\.product_type === 'cap'/)
})

test('客户远程搜索只允许最新请求更新结果和 loading', async () => {
  const deferred = () => {
    let resolve
    const promise = new Promise(done => { resolve = done })
    return { promise, resolve }
  }
  const first = deferred()
  const second = deferred()
  const runLatest = createLatestRequestRunner()
  let customers = []
  let loading = false
  const search = request => {
    loading = true
    return runLatest(
      () => request,
      value => { customers = value },
      () => { loading = false },
    )
  }

  const firstRun = search(first.promise)
  const secondRun = search(second.promise)
  second.resolve(['新结果'])
  await secondRun
  assert.deepEqual(customers, ['新结果'])
  assert.equal(loading, false)

  first.resolve(['过期结果'])
  await firstRun
  assert.deepEqual(customers, ['新结果'])
  assert.equal(loading, false)

  const createLogic = read('../src/views/domestic/composables/useDomesticOrderCreate.js')
  assert.match(createLogic, /createLatestRequestRunner/)
})
