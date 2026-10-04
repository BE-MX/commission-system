import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { sortTableRows } from '../src/utils/tableSort.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const hairTable = read('../src/views/invoice/components/InvoiceHairTable.vue')
const accessoryTable = read('../src/views/invoice/components/InvoiceAccessoryTable.vue')

// 明细可能几十上百行：两张表都吃当前页切片、固定窗口高度、窗内分页
for (const [name, source] of [['hair', hairTable], ['accessory', accessoryTable]]) {
  test(`${name} detail table paginates within a fixed-height window`, () => {
    assert.match(source, /:data="pagedItems"/)
    assert.match(source, /max-height="560"/)
    assert.match(source, /@sort-change="sortLines"/)
    assert.match(source, /const sortedItems = computed\(\(\) => sortTableRows\(props\.items,/)
    assert.match(source, /const pagedItems = computed\(\(\) => sortedItems\.value\.slice\(\(page\.value - 1\) \* pageSize\.value, page\.value \* pageSize\.value\)\)/)
    // 行号跨页连续（不因翻页从 1 重排）
    assert.match(source, /type="index" :index="indexBase"/)
    assert.match(source, /const indexBase = computed\(\(\) => \(page\.value - 1\) \* pageSize\.value \+ 1\)/)
    // 窗内分页器
    assert.match(source, /v-model:current-page="page"/)
    assert.match(source, /v-model:page-size="pageSize"/)
    assert.match(source, /:page-sizes="\[20, 50, 100\]"/)
    assert.match(source, /:total="items\.length"/)
    // 页码策略：初次装载回第一页；新增/导入跟到末页；删行后收敛页码
    assert.match(source, /if \(!before\) page\.value = 1/)
    assert.match(source, /else if \(now > before\) page\.value = pages/)
    assert.match(source, /else if \(page\.value > pages\) page\.value = pages/)
  })

  test(`${name} detail sort covers all pages, preserves editable rows and clears to original order`, async t => {
    const scope = Vue.effectScope()
    t.after(() => scope.stop())
    const props = Vue.reactive({ items: [
      ...Array.from({ length: 43 }, (_, index) => ({ id: index + 1, quantity: 43 - index })),
      { id: 44, quantity: 2 }, { id: 45, quantity: null },
    ] })
    const originalRows = [...props.items]
    const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
      .replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, binding, key) => {
        const declaration = binding.trim().startsWith('{') ? binding.replace(/\bas\b/g, ':') : `{ default: ${binding} }`
        return `const ${declaration} = modules[${JSON.stringify(key)}] || {};`
      })
    const state = scope.run(() => new Function('modules', 'defineProps', 'defineEmits', `${script}\nreturn { page, pageSize, pagedItems, indexBase, sortLines };`)(
      { vue: Vue, '@/utils/tableSort': { sortTableRows } }, () => props, () => () => {},
    ))
    state.page.value = 3
    assert.equal(state.pagedItems.value[0].id, 41)
    state.sortLines({ prop: 'quantity', order: 'ascending' })
    assert.equal(state.page.value, 1)
    assert.deepEqual(state.pagedItems.value.slice(0, 3).map(row => row.id), [43, 42, 44])
    for (const direction of ['ascending', 'descending']) {
      state.sortLines({ prop: 'quantity', order: direction })
      const actual = []
      for (let page = 1; page <= 3; page++) {
        state.page.value = page
        assert.equal(state.indexBase.value, (page - 1) * 20 + 1)
        assert.ok(state.pagedItems.value.length <= 20)
        actual.push(...state.pagedItems.value)
      }
      assert.equal(actual.length, originalRows.length)
      assert.equal(new Set(actual.map(row => row.id)).size, originalRows.length)
      assert.equal(actual.at(-1).id, 45)
      const quantities = actual.slice(0, -1).map(row => row.quantity)
      assert.ok(quantities.every((value, index) => index === 0 || (direction === 'ascending' ? quantities[index - 1] <= value : quantities[index - 1] >= value)))
      assert.deepEqual(actual.filter(row => row.quantity === 2).map(row => row.id), [42, 44])
    }
    const editable = state.pagedItems.value.find(row => row.id === 43)
    assert.equal(editable, originalRows[42])
    editable.quantity = 99
    assert.equal(props.items[42].quantity, 99)
    state.sortLines({ prop: 'quantity', order: null })
    assert.equal(state.page.value, 1)
    assert.deepEqual(state.pagedItems.value.map(row => row.id), originalRows.slice(0, 20).map(row => row.id))
    assert.deepEqual([...props.items], originalRows)
    props.items.splice(0, props.items.length)
    await Vue.nextTick()
    props.items.push(...originalRows)
    await Vue.nextTick()
    assert.equal(state.page.value, 1)
    props.items.push({ id: 46, quantity: 0 })
    await Vue.nextTick()
    assert.equal(state.page.value, 3)
    props.items.splice(20)
    await Vue.nextTick()
    assert.equal(state.page.value, 1)
  })
}
