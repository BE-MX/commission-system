<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useListPage } from '@/composables/useListPage'
import { portalAdminApi } from '@/api/portal'
import { createAccessMutation } from './customerAccess.mjs'
const props = defineProps({ itemId: { type: String, required: true } })
const emit = defineEmits(['close', 'changed'])
const auth = useAuthStore(), current = ref(null), selection = ref(undefined), preview = ref(''), reference = ref('')
const error = ref(''), reason = ref(''), confirmed = ref(false), state = ref('idle'), reading = ref(false), previewing = ref(false)
let generation = 0, listSequence = 0, previewSequence = 0, listController, previewController, readController
const mutation = createAccessMutation(value => portalAdminApi.bindImage(props.itemId, value.body, value.version))
const locked = computed(() => ['sending', 'uncertain'].includes(state.value))
const message = e => typeof e?.response?.data?.message === 'string' ? e.response.data.message : '图片操作失败，请刷新后重试。'
function clearPreview() { previewSequence++; previewController?.abort(); if (preview.value) URL.revokeObjectURL(preview.value); preview.value = ''; reference.value = ''; confirmed.value = false; previewing.value = false }
const { list, total, page, pageSize, loading, searchForm, fetchList, handleSearch, handlePageChange } = useListPage(async params => {
  const request = ++listSequence, identity = generation
  listController?.abort(); listController = new AbortController(); list.value = []; total.value = 0
  try { const data = await portalAdminApi.imageAssets(params, listController.signal); return identity === generation && request === listSequence ? data : { items: [], total: 0 } }
  catch (e) { if (identity === generation && request === listSequence) { if ([401,403,404].includes(e?.response?.status)) clear(); error.value = message(e) } return { items: [], total: 0 } }
}, { searchForm: { keyword: '' } })
async function load() {
  if (state.value === 'sending') return
  const identity = generation
  reading.value = true; current.value = null; selection.value = undefined; clearPreview(); error.value = ''
  readController?.abort(); readController = new AbortController()
  try { const data = await portalAdminApi.catalogItem(props.itemId, readController.signal); if (identity !== generation) return; current.value = data; mutation.clear(); state.value = 'idle'; reason.value = '' }
  catch (e) { if (identity === generation) error.value = message(e) }
  finally { if (identity === generation) reading.value = false }
}
async function choose(row) {
  if (locked.value) return
  clearPreview(); selection.value = row.id; previewing.value = true; error.value = ''
  const request = previewSequence, identity = generation
  previewController = new AbortController()
  try {
    const data = await portalAdminApi.previewImage(row.id, previewController.signal)
    if (identity !== generation || request !== previewSequence) return
    if (!(data.blob instanceof Blob) || data.blob.type !== 'image/jpeg' || !data.reference?.startsWith(row.id + ':')) throw new Error('Invalid image response')
    preview.value = URL.createObjectURL(data.blob); reference.value = data.reference
  } catch (e) { if (identity === generation && request === previewSequence) { if ([401,403,404].includes(e?.response?.status)) clear(); error.value = message(e) } }
  finally { if (identity === generation && request === previewSequence) previewing.value = false }
}
async function save() {
  if (locked.value || reading.value || previewing.value || loading.value || !current.value || !confirmed.value || !reason.value.trim() || selection.value === undefined || selection.value !== null && !reference.value) return
  // Auxiliary reads cannot clear an in-flight command or its uncertain result.
  listSequence++; listController?.abort(); readController?.abort()
  const identity = generation
  try {
    const promise = mutation.execute({ action: 'image', id: props.itemId, version: current.value.row_version, body: { asset_id: selection.value, asset_reference: selection.value === null ? null : reference.value, reason: reason.value.trim() } }); state.value = mutation.state
    const result = await promise
    if (identity !== generation || !result) return
    state.value = mutation.state; emit('changed', '商品图片已更新；素材版本更新后需重新预览并批准。'); emit('close')
  } catch (e) { if (identity === generation) { state.value = mutation.state; if ([401,403,404].includes(e?.response?.status)) clear(); error.value = message(e) } }
}
function clear() { generation++; listSequence++; clearPreview(); listController?.abort(); readController?.abort(); mutation.clear(); current.value = null; selection.value = undefined; list.value = []; total.value = 0; state.value = 'idle'; reading.value = false; previewing.value = false; reason.value = '' }
function close() { if (!locked.value) emit('close') }
watch(reason, () => { confirmed.value = false })
watch(() => [auth.accessToken, auth.user], () => { clear(); emit('close') }, { flush: 'sync' })
function beforeUnload(event) { if (locked.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(() => !locked.value)
onBeforeUnmount(() => { clear(); window.removeEventListener('beforeunload', beforeUnload) })
onMounted(load)
</script>
<template>
  <el-dialog :model-value="true" title="批准商品展示图片" width="900px" class="portal-image-binding" :close-on-click-modal="false" :close-on-press-escape="!locked" :show-close="!locked" @update:model-value="value => { if (!value) close() }">
    <el-alert title="仅展示允许预览和下载的全员图片素材。批准后供获授权客户查看；素材换版本后需重新批准。" type="info" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="state === 'uncertain'" title="保存结果未知，不能重发。请读取商品当前记录后重新核对。" type="warning" :closable="false" />
    <p v-if="current">{{ current.display_name }} / {{ current.color_name }} · 当前图片 {{ current.image_asset_id || '未绑定' }}</p>
    <div class="search"><el-input v-model="searchForm.keyword" aria-label="搜索图片素材" placeholder="按素材文件名搜索" :disabled="locked" @keyup.enter="handleSearch" /><GlassButton :disabled="locked || loading" @click="handleSearch">搜索</GlassButton></div>
    <el-table v-loading="loading" :data="list" border class="list-table" empty-text="没有符合公开展示条件的图片素材">
      <el-table-column prop="name" label="素材文件名" min-width="260" /><el-table-column prop="format" label="格式" min-width="80" />
      <el-table-column label="操作" min-width="100" fixed="right" class-name="table-action-column"><template #default="{ row }"><GlassButton v-permission="'asset:admin'" variant="link" :disabled="locked || previewing" @click="choose(row)">选择并预览</GlassButton></template></el-table-column>
    </el-table>
    <el-pagination :current-page="page" :page-size="pageSize" :total="total" :disabled="locked || loading" layout="total, prev, pager, next" @current-change="handlePageChange" />
    <div v-loading="previewing" class="image-preview"><img v-if="preview" :src="preview" alt="待批准的商品图片" /><p v-else>{{ selection === null ? '本次将移除商品图片。' : '请选择图片并核对展示内容。' }}</p></div>
    <GlassButton :disabled="locked" @click="clearPreview(); selection = null">移除当前图片</GlassButton>
    <el-form label-position="top" :disabled="locked || reading"><el-form-item label="操作原因"><el-input v-model="reason" aria-label="图片操作原因" maxlength="500" /></el-form-item><el-checkbox v-model="confirmed">确认此版本图片可以向获授权客户展示，或确认移除</el-checkbox></el-form>
    <template #footer><GlassButton :disabled="locked" @click="close">关闭</GlassButton><GlassButton :disabled="state === 'sending' || reading" @click="load">读取当前商品并放弃草稿</GlassButton><GlassButton v-permission="'asset:admin'" variant="primary" :disabled="locked || reading || previewing || loading || !current || !confirmed || !reason.trim() || selection === undefined || (selection !== null && !reference)" @click="save">确认图片设置</GlassButton></template>
  </el-dialog>
</template>
<style scoped>
.el-alert { margin-bottom: 16px; } .search { display: flex; gap: 12px; margin: 16px 0; } .el-pagination { overflow-x: auto; margin: 16px 0; }
.image-preview { min-height: 90px; margin: 20px 0; } .image-preview img { display: block; max-width: 100%; max-height: 300px; object-fit: contain; }
p { overflow-wrap: anywhere; color: var(--text-secondary); } .el-form { margin-top: 20px; } .el-checkbox { height: auto; white-space: normal; } :deep(.el-checkbox__label) { white-space: normal; }
</style>
<style>.portal-image-binding { max-width: calc(100vw - 24px); } .portal-image-binding .el-dialog__footer { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }</style>
