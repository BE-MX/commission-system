import test from 'node:test'
import assert from 'node:assert/strict'
import { ref } from 'vue'
import { useCustomerMediaTagSelection } from '../src/views/design/customer-media/composables/useCustomerMediaTagSelection.js'
import { queueFolderFiles } from '../src/views/design/customer-media/folderUploadTags.js'

const baseTag = { dimension_id: 3, tag_value_id: 11, value: '固定标签' }
const folderTag = { dimension_id: 3, tag_value_id: 12, value: '文件夹标签' }
const otherTag = { dimension_id: 3, tag_value_id: 13, value: '临时标签' }
const singleA = { dimension_id: 4, tag_value_id: 21, value: 'A' }
const singleB = { dimension_id: 4, tag_value_id: 22, value: 'B' }

function setup() {
  const customerTags = ref([baseTag, folderTag, otherTag, singleA, singleB])
  const tagDimensions = ref([{ id: 3, is_single_select: 0 }, { id: 4, is_single_select: 1 }])
  const blocked = ref(false)
  const warnings = []
  const selection = useCustomerMediaTagSelection({ customerTags, tagDimensions,
    isBlocked: () => blocked.value, onConflict: message => warnings.push(message) })
  return { ...selection, customerTags, blocked, warnings }
}

test('only selected tags can be locked and a locked tag stays selected on manual toggle', () => {
  const state = setup()
  state.toggleTagLock(baseTag)
  assert.deepEqual(state.lockedTagIds.value, [])
  state.toggleTag(baseTag)
  state.toggleTagLock(baseTag)
  state.toggleTag(baseTag)
  assert.deepEqual(state.lockedTagIds.value, [11])
  assert.deepEqual(state.selectedTagIds.value, [11])
})

test('folder selection keeps all locked labels and replaces only unlocked selections', () => {
  const state = setup()
  for (const tag of [baseTag, singleA]) { state.toggleTag(tag); state.toggleTagLock(tag) }
  state.toggleTag(otherTag)
  const tags = state.selectFolderTag(folderTag)
  assert.deepEqual(tags.map(tag => tag.tag_value_id), [11, 21, 12])
  assert.deepEqual(state.selectedTagIds.value, [11, 21, 12])
  assert.deepEqual(state.selectFolderTag(baseTag).map(tag => tag.tag_value_id), [11, 21])
})

test('unlocking keeps current selection but the next folder can replace it', () => {
  const state = setup()
  state.toggleTag(baseTag)
  state.toggleTagLock(baseTag)
  state.toggleTagLock(baseTag)
  assert.deepEqual(state.selectedTagIds.value, [11])
  assert.deepEqual(state.lockedTagIds.value, [])
  state.selectFolderTag(folderTag)
  assert.deepEqual(state.selectedTagIds.value, [12])
})

test('closing the upload dialog clears locks without rewriting queued label snapshots', () => {
  const state = setup()
  state.toggleTag(baseTag)
  state.toggleTagLock(baseTag)
  const queuedTags = state.selectFolderTag(folderTag)
  state.clearTagLocks()
  state.selectFolderTag(otherTag)
  assert.deepEqual(state.lockedTagIds.value, [])
  assert.deepEqual(state.selectedTagIds.value, [13])
  assert.deepEqual(queuedTags.map(tag => tag.tag_value_id), [11, 12])
})

test('customer tag refresh retains locks by ID and prunes removed labels', () => {
  const state = setup()
  state.toggleTag(baseTag)
  state.toggleTagLock(baseTag)
  state.customerTags.value = [{ ...baseTag, value: '新名字' }, folderTag]
  assert.deepEqual(state.lockedTagIds.value, [11])
  assert.equal(state.selectFolderTag(folderTag)[0].value, '新名字')
  state.customerTags.value = [folderTag]
  assert.deepEqual(state.lockedTagIds.value, [])
  assert.deepEqual(state.selectedTagIds.value, [12])
})

test('a locked single-choice tag cannot be replaced manually or combined with a conflicting folder tag', () => {
  const state = setup()
  state.toggleTag(singleA)
  state.toggleTagLock(singleA)
  state.toggleTag(singleB)
  assert.deepEqual(state.selectedTagIds.value, [21])
  assert.equal(state.warnings.length, 1)
  assert.throws(() => state.selectFolderTag(singleB), /单选.*解锁/)
  assert.deepEqual(state.selectedTagIds.value, [21])
  state.toggleTagLock(singleA)
  state.toggleTag(singleB)
  assert.deepEqual(state.selectedTagIds.value, [22])
})

test('selection and lock controls do nothing while files are being prepared or uploaded', () => {
  const state = setup()
  state.toggleTag(baseTag)
  state.blocked.value = true
  state.toggleTagLock(baseTag)
  state.toggleTag(otherTag)
  assert.deepEqual(state.lockedTagIds.value, [])
  assert.deepEqual(state.selectedTagIds.value, [11])
})

test('new page instance starts without persisted lock state', () => {
  const first = setup()
  first.toggleTag(baseTag)
  first.toggleTagLock(baseTag)
  assert.deepEqual(setup().lockedTagIds.value, [])
})

test('folder queue uses the locked-plus-folder selection for each matched or created root', async () => {
  const state = setup()
  state.toggleTag(baseTag)
  state.toggleTagLock(baseTag)
  state.toggleTag(otherTag)
  const queued = []
  await queueFolderFiles([
    { file: { name: 'a.png' }, pathSegments: [folderTag.value] },
    { file: { name: 'b.png' }, pathSegments: ['新标签'] },
  ], {
    getCustomerTags: () => state.customerTags.value,
    getSelectedTags: () => state.selectedTags.value,
    selectFolderTag: state.selectFolderTag,
    confirmCreate: async () => true,
    createTag: async name => {
      const tag = { dimension_id: 3, tag_value_id: 14, value: name }
      state.customerTags.value.push(tag)
      return tag
    },
    addFiles: (files, tags) => queued.push({ files, ids: tags.map(tag => tag.tag_value_id) }),
  })
  assert.deepEqual(queued.map(group => group.ids), [[11, 12], [11, 14]])
  assert.deepEqual(state.selectedTagIds.value, [11, 14])
})

test('single-choice conflict stops the folder from being queued with incompatible labels', async () => {
  const state = setup()
  state.toggleTag(singleA)
  state.toggleTagLock(singleA)
  const queued = []
  await assert.rejects(queueFolderFiles([{ file: { name: 'a.png' }, pathSegments: ['B'] }], {
    getCustomerTags: () => state.customerTags.value,
    getSelectedTags: () => state.selectedTags.value,
    selectFolderTag: state.selectFolderTag,
    addFiles: files => queued.push(files),
  }), /单选.*解锁/)
  assert.deepEqual(queued, [])
})
