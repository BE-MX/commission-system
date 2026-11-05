import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as vue from 'vue'
import * as droppedFiles from '../src/views/design/customer-media/droppedFiles.js'
import { queueFolderFiles } from '../src/views/design/customer-media/folderUploadTags.js'

const source = readFileSync(new URL('../src/views/design/customer-media/composables/useCustomerMediaFolderUpload.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replace('export function', 'function')
const dimensions = [
  { id: 1, name: 'product_type', label: 'Product type' },
  { id: 2, name: 'textures_type', label: 'Textures type' },
  { id: 3, name: 'color_names', label: 'Color names' },
]

function setup({ dims = dimensions, confirm, failCreate = false } = {}) {
  const tags = [], calls = [], queued = [], errors = [], warnings = [], prompts = []
  const imports = { ref: vue.ref, h: vue.h, ...droppedFiles, queueFolderFiles, ElSelect: 'select', ElOption: 'option',
    createCustomerTagValue: async (...args) => {
      calls.push(args)
      if (failCreate) throw new Error('network error')
      return { data: { id: 10 + calls.length, value: args[2] } }
    },
    confirmAction: async (message, title, options) => { prompts.push({ message, options }); await confirm?.(message, options) },
    isFeedbackCancelled: error => ['cancel', 'close'].includes(error),
    msgError: message => errors.push(message), msgWarning: message => warnings.push(message),
  }
  const useUpload = new Function(...Object.keys(imports), `${source}; return useCustomerMediaFolderUpload`)(...Object.values(imports))
  const upload = useUpload({ getContext: () => ({ customerId: 'fixture', taskId: 42 }),
    getCustomerTags: () => tags, getTagDimensions: () => dims, getSelectedTags: () => [],
    selectFolderTag: tag => [tag], onTagCreated: ({ dimension_id, value }) => tags.push({ dimension_id, tag_value_id: value.id, value: value.value }),
    refreshTags: async () => {}, addFiles: (files, selected) => queued.push({ files, selected }), isBlocked: () => false,
  })
  const select = (message, id) => {
    const node = typeof message === 'function' ? message() : message
    const field = node.children.find(child => child.type === 'select')
    assert.ok(field, 'creation confirmation must offer a dimension selector')
    if (id != null) field.props['onUpdate:modelValue'](id)
    return field
  }
  return { ...upload, calls, queued, errors, warnings, prompts, select,
    add: (...names) => upload.onFolderSelected({ target: { value: 'fixture', files: names.map(name => ({ name: 'a.jpg', webkitRelativePath: `${name}/nested/a.jpg` })) } }),
  }
}

test('multiple dimensions without customer_general create in the explicitly selected dimension and queue files', async () => {
  const state = setup({ confirm: message => state.select(message, 3) })
  await state.add('新 颜色')
  assert.deepEqual(state.errors, [])
  assert.deepEqual(state.calls, [[{ customerId: 'fixture', taskId: 42 }, 3, '新颜色']])
  assert.equal(state.queued[0].selected[0].dimension_id, 3)
  assert.equal(state.queued[0].files[0].pathSegments[1], 'nested')
  assert.equal(state.preparingFolders.value, false)
})

test('ambiguous dimension blocks confirmation until a valid choice is made', async () => {
  const state = setup({ confirm: (message, options) => {
    assert.equal(state.select(message).props.modelValue, null)
    let closed = false
    options.beforeClose('confirm', {}, () => { closed = true })
    assert.equal(closed, false)
    assert.equal(state.warnings.length, 1)
    state.select(message, 2)
    options.beforeClose('confirm', {}, () => { closed = true })
    assert.equal(closed, true)
  } })
  await state.add('新纹理')
  assert.deepEqual(state.errors, [])
  assert.equal(state.calls[0][1], 2)
})

test('dragging a directory follows the same dimension selection and creation flow', async () => {
  const state = setup({ confirm: message => state.select(message, 3) })
  let read = false, prevented = false, stopped = false
  const entry = { name: '新 颜色', isDirectory: true, createReader: () => ({ readEntries: resolve => {
    const entries = read ? [] : [{ isFile: true, file: resolveFile => resolveFile({ name: 'a.jpg' }) }]
    read = true
    resolve(entries)
  } }) }
  await state.onDropFolders({
    dataTransfer: { items: [{ webkitGetAsEntry: () => entry }] },
    preventDefault: () => { prevented = true }, stopPropagation: () => { stopped = true },
  })
  assert.equal(prevented && stopped, true)
  assert.deepEqual(state.errors, [])
  assert.equal(state.calls[0][1], 3)
  assert.equal(state.calls[0][2], '新颜色')
  assert.equal(state.queued.length, 1)
})

for (const action of ['cancel', 'close']) test(`${action} creates and queues nothing`, async () => {
  const state = setup({ confirm: () => { throw action } })
  await state.add('新颜色')
  assert.deepEqual(state.calls, [])
  assert.deepEqual(state.queued, [])
  assert.deepEqual(state.errors, [])
  assert.equal(state.preparingFolders.value, false)
})

test('managed and hidden dimensions are excluded; the only writable dimension is preselected', async () => {
  const state = setup({ dims: [{ ...dimensions[0], is_managed: 1 }, { ...dimensions[1], is_visible: 0 }, dimensions[2]],
    confirm: message => {
      const field = state.select(message)
      assert.equal(field.props.modelValue, 3)
      assert.deepEqual(field.children.default().map(option => option.props.value), [3])
    },
  })
  await state.add('新颜色')
  assert.deepEqual(state.errors, [])
  assert.equal(state.calls[0][1], 3)
})

test('configured general dimension remains the default', async () => {
  const state = setup({ dims: [...dimensions, { id: 4, name: 'customer_general', label: '客户标签' }] })
  await state.add('新标签')
  assert.equal(state.calls[0][1], 4)
})

test('no writable dimension reports configuration issue before offering creation', async () => {
  const state = setup({ dims: [{ ...dimensions[0], is_managed: 1 }] })
  await state.add('新标签')
  assert.equal(state.prompts.length, 0)
  assert.equal(state.errors.length, 1)
  assert.deepEqual(state.calls, [])
})

test('each new folder has its own dimension choice', async () => {
  let index = 0
  const state = setup({ confirm: message => state.select(message, [2, 3][index++]) })
  await state.add('新纹理', '新颜色')
  assert.deepEqual(state.errors, [])
  assert.deepEqual(state.calls.map(call => call[1]), [2, 3])
  assert.deepEqual(state.queued.map(item => item.selected[0].dimension_id), [2, 3])
})

test('creation failure releases busy state and never queues under an old tag', async () => {
  const state = setup({ failCreate: true, confirm: message => state.select(message, 3) })
  await state.add('新颜色')
  assert.equal(state.calls.length, 1)
  assert.match(state.errors[0], /network error/)
  assert.deepEqual(state.queued, [])
  assert.equal(state.preparingFolders.value, false)
})
