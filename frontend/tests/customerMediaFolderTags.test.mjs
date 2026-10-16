import test from 'node:test'
import assert from 'node:assert/strict'
import { queueFolderFiles } from '../src/views/design/customer-media/folderUploadTags.js'

const oldTag = { dimension_id: 3, tag_value_id: 10, value: '旧标签' }
const wedding = { dimension_id: 3, tag_value_id: 11, value: '婚 纱' }
const raw = (name, ...pathSegments) => ({ file: { name }, pathSegments })

function setup(tags = [oldTag, wedding]) {
  const state = { tags: [...tags], selected: [oldTag], queued: [], prompts: [], created: [] }
  const options = {
    getCustomerTags: () => state.tags,
    getSelectedTags: () => state.selected,
    selectTag: tag => { state.selected = [tag] },
    confirmCreate: async name => { state.prompts.push(name); return true },
    createTag: async name => {
      state.created.push(name)
      const tag = { dimension_id: 3, tag_value_id: 20 + state.created.length, value: name }
      state.tags.push(tag)
      return tag
    },
    addFiles: (files, tags) => { state.queued.push({ files, tags: structuredClone(tags) }) },
  }
  return { state, options }
}

test('top folder name removes all whitespace, replaces selection and tags every nested file', async () => {
  const { state, options } = setup()
  const files = [raw('a.jpg', ' 婚　纱 '), raw('b.mp4', ' 婚　纱 ', '外景')]
  await queueFolderFiles(files, options)
  assert.deepEqual(state.selected, [wedding])
  assert.deepEqual(state.queued, [{ files, tags: [wedding] }])
  assert.deepEqual(state.prompts, [])
  assert.deepEqual(state.created, [])
})

test('a matching child directory cannot override a new top folder tag', async () => {
  const { state, options } = setup()
  await queueFolderFiles([raw('a.jpg', '新 客 户', '婚纱')], options)
  assert.deepEqual(state.prompts, ['新客户'])
  assert.deepEqual(state.created, ['新客户'])
  assert.equal(state.queued[0].tags[0].value, '新客户')
  assert.deepEqual(state.selected, state.queued[0].tags)
})

test('cancel skips the folder without creating, selecting or queuing it', async () => {
  const { state, options } = setup()
  options.confirmCreate = async () => false
  await queueFolderFiles([raw('a.jpg', '新标签')], options)
  assert.deepEqual(state.selected, [oldTag])
  assert.deepEqual(state.created, [])
  assert.deepEqual(state.queued, [])
})

test('multiple root folders keep distinct tags, with no previous selections on their files', async () => {
  const { state, options } = setup()
  await queueFolderFiles([raw('a.jpg', '婚纱'), raw('b.jpg', '外 景'), raw('c.jpg', '外 景', '婚纱')], options)
  assert.deepEqual(state.queued.map(group => group.tags.map(tag => tag.value)), [['婚 纱'], ['外景']])
  assert.deepEqual(state.queued.map(group => group.files.length), [1, 2])
  assert.equal(state.selected[0].value, '外景')
  assert.deepEqual(state.created, ['外景'])
})

test('folder drop with no prior label selection still matches and queues', async () => {
  const { state, options } = setup()
  state.selected = []
  await queueFolderFiles([raw('a.jpg', '婚纱')], options)
  assert.deepEqual(state.queued[0].tags, [wedding])
})

test('mixed loose files retain the original manual labels', async () => {
  const { state, options } = setup()
  await queueFolderFiles([raw('a.jpg', '婚纱'), raw('loose.jpg')], options)
  assert.deepEqual(state.queued[1].tags, [oldTag])
})

test('another customer/global labels are never candidates for automatic matching', async () => {
  const { state, options } = setup([oldTag])
  await queueFolderFiles([raw('a.jpg', '婚纱')], options)
  assert.deepEqual(state.created, ['婚纱'])
  assert.notEqual(state.queued[0].tags[0].tag_value_id, wedding.tag_value_id)
})

test('failed or uncertain creation never queues files under the previous tag', async () => {
  const { state, options } = setup()
  options.createTag = async () => { throw new Error('network error') }
  await assert.rejects(queueFolderFiles([raw('a.jpg', '新标签')], options), /network error/)
  assert.deepEqual(state.selected, [oldTag])
  assert.deepEqual(state.queued, [])
})

test('folders differing only by whitespace share one tag and confirmation', async () => {
  const { state, options } = setup()
  await queueFolderFiles([raw('a.jpg', '新标签'), raw('b.jpg', '新 标 签')], options)
  assert.deepEqual(state.created, ['新标签'])
  assert.equal(state.queued.length, 1)
  assert.equal(state.queued[0].files.length, 2)
})

test('blank folder name does not create a blank tag', async () => {
  const { state, options } = setup()
  await assert.rejects(queueFolderFiles([raw('a.jpg', '　 ')], options), /文件夹名称/)
  assert.deepEqual(state.created, [])
  assert.deepEqual(state.queued, [])
})
