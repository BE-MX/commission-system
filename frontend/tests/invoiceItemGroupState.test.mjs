import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive } from 'vue'

import { emptyHairRow, emptyInvoiceForm, normalizeHairRow } from '../src/views/invoice/composables/invoiceEditorState.js'
import { ALL_ITEM_GROUPS, itemGroupNameError, suggestedItemGroupName, useInvoiceItemGroups } from '../src/views/invoice/composables/useInvoiceItemGroups.js'

function setup(form, prompts = [], names = []) {
  let sequence = 0
  return useInvoiceItemGroups(form, {
    today: () => '2026-10-27',
    newKey: () => `new-${++sequence}`,
    prompt: async (message, title, options) => {
      prompts.push(options)
      return { value: names.length ? names.shift() : options.inputValue }
    },
    confirm: async () => true,
    warn: () => {},
  })
}

test('new editor creates a Beijing-date default group and assigns imported rows', () => {
  const form = reactive({ ...emptyInvoiceForm(), items: [normalizeHairRow({ product_display: 'Imported' }), emptyHairRow()] })
  const api = setup(form)
  api.resetItemGroups({ id: null })

  assert.equal(form.item_groups.length, 1)
  assert.equal(form.item_groups[0].name, '2026-10-27')
  assert.equal(api.activeGroupKey.value, form.item_groups[0].key)
  assert.ok(form.items.every(row => row.group_key === form.item_groups[0].key))
  assert.equal(api.getTargetGroupKey(), form.item_groups[0].key)
  assert.equal(suggestedItemGroupName(form.item_groups, '2026-10-27'), '2026-10-27 追加 2')
})

test('custom create, rename and move preserve stable keys and only change display assignment', async () => {
  const form = reactive(emptyInvoiceForm())
  const prompts = []
  const api = setup(form, prompts, ['二次补单', '补单改名'])
  api.resetItemGroups({ id: null })
  const firstKey = form.item_groups[0].key
  form.items.push({ ...normalizeHairRow({ group_key: firstKey, product_display: 'Product' }), created_at: '2026-10-01T09:00:00' })

  const second = await api.createItemGroup()
  assert.equal(api.activeGroupKey.value, second.key)
  assert.equal(second.name, '二次补单')
  assert.equal(await api.renameItemGroup(second.key), true)
  assert.equal(second.key, form.item_groups[1].key)
  assert.equal(form.item_groups[1].name, '补单改名')
  assert.equal(api.moveRowsToGroup(form.items, second.key), true)
  assert.equal(form.items[0].group_key, second.key)
  assert.equal(form.items[0].created_at, '2026-10-01T09:00:00')
  assert.equal(itemGroupNameError('首批', form.item_groups, second.key), '')
})

test('non-empty groups cannot be deleted and saved editor keeps the active stable key', async () => {
  const form = reactive(emptyInvoiceForm())
  const api = setup(form)
  api.resetItemGroups({ id: null })
  const firstKey = form.item_groups[0].key
  form.items.push(normalizeHairRow({ group_key: firstKey, product_display: 'Product' }))
  assert.equal(await api.deleteItemGroup(firstKey), false)

  const second = await api.createItemGroup()
  api.moveRowsToGroup(form.items, second.key)
  assert.equal(await api.deleteItemGroup(firstKey), true)
  assert.equal(api.activeGroupKey.value, second.key)
  assert.equal(await api.deleteItemGroup(second.key), false)
  api.moveRowsToGroup(form.items, second.key)
  form.items.splice(0)
  api.resetItemGroups({ id: 42, item_groups: form.item_groups })
  assert.equal(api.activeGroupKey.value, second.key)
  api.resetItemGroups({ id: 42, item_groups: form.item_groups })
  assert.equal(api.activeGroupKey.value, second.key)
})
