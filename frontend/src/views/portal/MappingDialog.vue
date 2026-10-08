<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { portalAdminApi } from '@/api/portal'
import NotificationDialog from './NotificationDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { msgError, msgSuccess } from '@/utils/feedback'
import { invalidEntries, mappingConflicts, mappingKinds, mappingPayload, sourceOptions } from './mappingDraft.mjs'

const props = defineProps({ access: { type: Object, required: true } })
const emit = defineEmits(['close', 'changed'])
const auth = useAuthStore(), data = ref(null), entries = ref([]), preview = ref(null), previewBody = ref('')
const error = ref(''), notice = ref(''), loading = ref(false), previewing = ref(false), state = ref('idle'), confirmed = ref(false)
const notificationsVisible = ref(false), errorSummary = ref(null), previewSummary = ref(null), recoverySummary = ref(null)
const addKind = ref('model'), addSource = ref(''), keyword = ref(''), page = ref(1), previewPage = ref(1)
const notificationBusy = ref(false), notificationTrigger = ref(null)
let notificationFocusSequence = 0
function openNotifications() { ++notificationFocusSequence; notificationsVisible.value = true }
async function closeNotifications() {
  notificationsVisible.value = false
  const current = ++notificationFocusSequence
  await nextTick()
  if (disposed || current !== notificationFocusSequence || notificationsVisible.value) return
  const button = notificationTrigger.value?.$el
  if (button?.isConnected && !button.disabled && button.getClientRects().length) button.focus()
}
const locked = computed(() => notificationBusy.value || ['sending', 'uncertain'].includes(state.value))
const editable = computed(() => auth.hasPermission('portal_mapping:write') && !locked.value && !loading.value && !previewing.value)
const options = computed(() => sourceOptions(data.value?.sources || [], addKind.value))
const stale = computed(() => invalidEntries(data.value?.sources || [], entries.value))
const staleIndexes = computed(() => new Set(stale.value.map(row => row.index)))
const labelMaps = computed(() => Object.fromEntries(['model', 'color', 'sku'].map(kind => [kind, new Map(sourceOptions(data.value?.sources || [], kind).map(o => [o.value, o.label]))])))
const sourceLabel = entry => labelMaps.value[entry.kind]?.get(entry.source_key) || `已失效来源 · ${entry.source_key}`
const filtered = computed(() => entries.value.map((entry, index) => ({ entry, index })).filter(({ entry }) => `${sourceLabel(entry)} ${entry.display_value} ${entry.customer_sku || ''}`.toLocaleLowerCase().includes(keyword.value.toLocaleLowerCase())))
const visibleEntries = computed(() => filtered.value.slice((page.value - 1) * 20, page.value * 20))
const sourceById = computed(() => new Map((data.value?.sources || []).map(row => [row.item_id, row])))
const previewRows = computed(() => (preview.value?.items || []).slice((previewPage.value - 1) * 20, previewPage.value * 20))
const previewConflicts = computed(() => (preview.value?.conflicts || []).slice((conflictPage.value - 1) * 20, conflictPage.value * 20))
const conflictPage = ref(1), changePage = ref(1)
const changeRows = computed(() => (preview.value?.changes || []).slice((changePage.value - 1) * 20, changePage.value * 20))
const changeLabels = { added: '新增', modified: '修改', removed: '删除' }
const aliasLabel = value => value ? `${value.display_value}${value.customer_sku ? ' · 货号 ' + value.customer_sku : ''}` : '未设置（按默认规则展示）'
let generation = 0, loadSequence = 0, previewSequence = 0, loadController, previewController, disposed = false, errorSequence = 0
const message = e => e?.response?.data?.message || (e?.code === 'ERR_NETWORK' ? '网络连接中断，请按页面提示核对。' : e.message) || '操作失败，请重试。'
async function showError(value) {
  const current = ++errorSequence
  error.value = value
  await nextTick()
  if (!disposed && current === errorSequence && error.value === value) errorSummary.value?.$el?.focus()
}
function payload() { return mappingPayload(data.value.mapping_version, entries.value) }
function invalidatePreview() { previewSequence++; previewController?.abort(); preview.value = null; previewBody.value = ''; confirmed.value = false; previewing.value = false }
watch(entries, invalidatePreview, { deep: true, flush: 'sync' })
watch(keyword, () => { page.value = 1 })
watch(addKind, () => { addSource.value = '' })
watch(() => filtered.value.length, count => { page.value = Math.min(page.value, Math.max(1, Math.ceil(count / 20))) })
async function load() {
  if (notificationBusy.value || state.value === 'sending' || loading.value) return
  const wasUnknown = state.value === 'uncertain', current = ++loadSequence, identity = generation
  loadController?.abort(); loadController = new AbortController(); loading.value = true; error.value = ''; invalidatePreview()
  // Clear private projection before reads; drafts are kept until a successful replacement.
  data.value = null
  try {
    const result = await portalAdminApi.mapping(props.access.id, loadController.signal)
    if (identity !== generation || current !== loadSequence) return
    data.value = result; entries.value = structuredClone(result.entries); page.value = 1; previewPage.value = 1; state.value = 'idle'
    notice.value = wasUnknown ? '已读取当前已发布版本并替换草稿；这不能证明上次发布命令成功。请核对当前内容，后续修改必须重新预览。' : '草稿只保留在当前窗口；关闭或重新读取会舍弃未发布修改。'
    if (wasUnknown) { await nextTick(); if (!disposed && identity === generation && current === loadSequence) recoverySummary.value?.$el?.focus() }
  } catch (e) { if (identity === generation && current === loadSequence) { void showError(message(e)); entries.value = [] } }
  finally { if (identity === generation && current === loadSequence) loading.value = false }
}
function addEntry() {
  if (!editable.value || !addSource.value) return
  if (entries.value.some(e => e.kind === addKind.value && e.source_key === addSource.value)) { void showError('此来源已有映射，请编辑现有条目。'); return }
  const source = data.value.sources.find(s => (addKind.value === 'sku' ? s.item_id : s[`${addKind.value}_key`]) === addSource.value)
  if (!source) return
  const display = addKind.value === 'color' ? source.color_name : entries.value.find(e => e.kind === 'model' && e.source_key === source.model_key)?.display_value || source.model_name
  entries.value.push({ kind: addKind.value, source_key: addSource.value, display_value: display, ...(addKind.value === 'sku' ? { item_id: addSource.value, customer_sku: '' } : {}) })
  keyword.value = ''; page.value = Math.ceil(entries.value.length / 20); addSource.value = ''; error.value = ''
}
function removeStale() { if (editable.value) entries.value = entries.value.filter((_, index) => !staleIndexes.value.has(index)) }
async function runPreview() {
  if (!editable.value || !data.value || stale.value.length) return
  const body = payload(), fingerprint = JSON.stringify(body), current = ++previewSequence, identity = generation
  previewController?.abort(); previewController = new AbortController(); previewing.value = true; error.value = ''; preview.value = null; confirmed.value = false
  try {
    const result = await portalAdminApi.previewMapping(props.access.id, body, previewController.signal)
    if (identity !== generation || current !== previewSequence || JSON.stringify(payload()) !== fingerprint) return
    if (result.access_id !== props.access.id || result.base_version !== data.value.mapping_version || !Array.isArray(result.items) || !Array.isArray(result.conflicts) || !Array.isArray(result.changes) || !result.change_counts) throw new Error('预览数据不完整，请重新读取。')
    preview.value = result; previewBody.value = fingerprint; previewPage.value = 1; conflictPage.value = 1; changePage.value = 1
    await nextTick()
    if (!disposed && identity === generation && current === previewSequence && preview.value) previewSummary.value?.$el?.focus()
  } catch (e) {
    if (identity === generation && current === previewSequence) {
      const text = message(e)
      if ([401, 403, 404].includes(e?.response?.status)) clear()
      void showError(text)
    }
  }
  finally { if (identity === generation && current === previewSequence) previewing.value = false }
}
async function publish() {
  if (!editable.value || !confirmed.value || !preview.value?.valid || preview.value.conflicts.length) return
  const body = payload(), expected = preview.value.row_version, identity = generation
  if (JSON.stringify(body) !== previewBody.value) { invalidatePreview(); return }
  state.value = 'sending'; error.value = ''
  try {
    const receipt = await portalAdminApi.publishMapping(props.access.id, body, expected)
    if (identity !== generation) return
    if (!receipt.id || receipt.mapping_version !== body.base_version + 1 || !Number.isSafeInteger(receipt.row_version) || receipt.row_version <= expected) throw new Error('发布回执不完整，请读取当前版本核对。')
    state.value = 'success'; msgSuccess('发布客户映射'); emit('changed'); emit('close')
  } catch (e) {
    if (identity !== generation) return
    if ([401, 403, 404].includes(e?.response?.status)) { const text = message(e); clear(); void showError(text); return }
    state.value = !e?.response?.status || e.response.status >= 500 ? 'uncertain' : 'failed'
    void showError(message(e)); invalidatePreview()
  }
}
function close() { if (!locked.value) emit('close') }
function clear() { notificationFocusSequence++; errorSequence++; notificationsVisible.value = false; notificationBusy.value = false; generation++; loadSequence++; invalidatePreview(); loadController?.abort(); data.value = null; entries.value = []; state.value = 'idle'; loading.value = false; previewing.value = false; notice.value = '' }
watch(() => [auth.accessToken, auth.user], () => { clear(); emit('close') })
function beforeUnload(event) { if (locked.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(() => { if (locked.value) { msgError(notificationBusy.value ? '通知重试结果待核对，请先重放原重试命令。' : '映射发布结果待核对，请先读取当前版本。'); return false } })
onBeforeUnmount(() => { disposed = true; clear(); window.removeEventListener('beforeunload', beforeUnload) })
load()
</script>

<template>
  <el-dialog :model-value="true" :title="`客户映射 · ${access.company_display_name}`" width="1080px" class="portal-mapping-dialog" :close-on-click-modal="false" :close-on-press-escape="!locked" :show-close="!locked" @update:model-value="value => { if (!value) close() }">
    <p v-if="loading || previewing || state === 'sending'" class="mapping-status" role="status">{{ loading ? '正在读取客户映射…' : previewing ? '正在校验映射与展示效果…' : '正在发布客户映射，请等待回执…' }}</p>
    <div v-loading="loading" :aria-busy="loading || previewing || state === 'sending' || undefined">
      <p><strong>{{ access.company_display_name }}</strong><span v-if="data"> · 当前映射版本 {{ data.mapping_version }} · 已授权规格 {{ data.sources.length }}</span></p>
      <el-alert v-if="error" ref="errorSummary" id="portal-mapping-error" tabindex="-1" :title="error" type="error" :closable="false" />
      <el-alert v-if="notice" ref="recoverySummary" tabindex="-1" :title="notice" type="info" :closable="false" />
      <el-alert v-if="state === 'uncertain'" title="发布结果未知。不会自动重发；请读取当前已发布版本并核对，再决定后续修改。" type="warning" :closable="false" />
      <template v-if="data">
        <p>仅改变客户展示名称，标准 SKU、规格、库存与定价不变。单规格型号名优先于型号别名；颜色使用颜色别名。</p>
        <el-alert v-if="stale.length" :title="`${stale.length} 条映射的来源已撤下或取消授权，须从草稿移除后才能发布；历史订单保留原名。`" type="warning" :closable="false" />
        <GlassButton v-if="stale.length" v-permission="'portal_mapping:write'" :disabled="!editable" @click="removeStale">从草稿移除失效项</GlassButton>
        <el-form v-permission="'portal_mapping:write'" :disabled="!editable" label-position="top" class="mapping-add">
          <el-form-item label="映射类型"><el-select v-model="addKind" aria-label="映射类型"><el-option v-for="(label, value) in mappingKinds" :key="value" :label="label" :value="value" /></el-select></el-form-item>
          <el-form-item label="标准来源"><el-select-v2 v-model="addSource" :options="options" filterable aria-label="标准来源" placeholder="搜索标准型号、颜色或完整规格" /></el-form-item>
          <GlassButton :disabled="!editable || !addSource" @click="addEntry">添加映射</GlassButton>
        </el-form>
        <el-input v-model="keyword" clearable aria-label="筛选映射条目" placeholder="筛选标准来源、客户名称或货号" />
        <el-empty v-if="!filtered.length" description="没有匹配的映射条目；未配置的商品使用默认名称" />
        <el-form :disabled="!editable" label-position="top">
          <article v-for="({ entry, index }) in visibleEntries" :key="`${entry.kind}:${entry.source_key}:${index}`" class="mapping-entry">
            <div class="mapping-entry-title"><div><strong>{{ mappingKinds[entry.kind] }}</strong><p>{{ sourceLabel(entry) }}</p><el-tag v-if="staleIndexes.has(index)" type="warning">来源已失效</el-tag></div><GlassButton v-permission="'portal_mapping:write'" :disabled="!editable" variant="link" @click="entries.splice(index, 1)">移除</GlassButton></div>
            <div class="mapping-fields"><el-form-item :label="entry.kind === 'color' ? '客户颜色名' : entry.kind === 'sku' ? '此规格型号名（覆盖型号映射）' : '客户型号名'"><el-input v-model="entry.display_value" :aria-describedby="error ? 'portal-mapping-error' : undefined" :aria-label="`客户展示名 ${index + 1}`" maxlength="128" /></el-form-item><el-form-item v-if="entry.kind === 'sku'" label="客户货号（可留空）"><el-input v-model="entry.customer_sku" :aria-describedby="error ? 'portal-mapping-error' : undefined" :aria-label="`客户货号 ${index + 1}`" maxlength="64" /></el-form-item></div>
          </article>
        </el-form>
        <el-pagination v-model:current-page="page" :page-size="20" :total="filtered.length" layout="total, prev, pager, next" />
        <template v-if="preview">
          <h3>版本差异 · 已发布 v{{ preview.base_version }} → 待发布 v{{ preview.base_version + 1 }}</h3>
          <p>新增 {{ preview.change_counts.added }} · 修改 {{ preview.change_counts.modified }} · 删除 {{ preview.change_counts.removed }}。删除映射后按默认规则展示，历史订单保留原快照。</p>
          <el-table :data="changeRows" border class="list-table" empty-text="与当前发布版本相同，没有映射变更">
            <el-table-column label="变更 / 标准来源" min-width="200"><template #default="{ row }"><strong>{{ changeLabels[row.change] }} · {{ mappingKinds[row.kind] }}</strong><p>{{ sourceLabel(row) }}</p></template></el-table-column>
            <el-table-column label="当前发布版本" min-width="200"><template #default="{ row }">{{ aliasLabel(row.before) }}</template></el-table-column>
            <el-table-column label="本次待发布" min-width="200"><template #default="{ row }">{{ aliasLabel(row.after) }}</template></el-table-column>
          </el-table>
          <el-pagination v-if="preview.changes.length > 20" v-model:current-page="changePage" :page-size="20" :total="preview.changes.length" layout="total, prev, pager, next" />
          <h3>客户展示预览 · {{ preview.affected_sku_count }} 个规格</h3>
          <el-alert ref="previewSummary" tabindex="-1" :title="preview.valid ? '校验通过。请核对展示效果，发布将使旧报价失效，历史订单不变。' : `发现 ${preview.conflicts.length} 项冲突，发布已阻止。请根据下方标准规格调整名称或货号。`" :type="preview.valid ? 'success' : 'error'" :closable="false" />
          <ul v-if="preview.conflicts.length" class="mapping-conflicts"><li v-for="(conflict, index) in previewConflicts" :key="index"><strong>{{ mappingConflicts[conflict.code] || '映射冲突' }}</strong><div v-for="id in conflict.item_ids" :key="id">{{ sourceById.get(id)?.model_name }} / {{ sourceById.get(id)?.color_name }} · {{ id }}</div></li></ul>
          <el-pagination v-if="preview.conflicts.length > 20" v-model:current-page="conflictPage" :page-size="20" :total="preview.conflicts.length" layout="total, prev, pager, next" />
          <el-table :data="previewRows" border class="list-table">
            <el-table-column label="标准型号 / 颜色" min-width="190"><template #default="{ row }">{{ sourceById.get(row.item_id)?.model_name }} / {{ sourceById.get(row.item_id)?.color_name }}</template></el-table-column>
            <el-table-column prop="model_name" label="客户型号名" min-width="160" /><el-table-column prop="color_name" label="客户颜色名" min-width="150" />
            <el-table-column label="客户货号" min-width="150"><template #default="{ row }">{{ row.customer_sku || '未设置' }}</template></el-table-column>
            <el-table-column label="标准规格（不变）" min-width="200"><template #default="{ row }">长度 {{ row.length }} · 重量 {{ row.weight }} · {{ row.unit }}</template></el-table-column>
          </el-table>
          <el-pagination v-model:current-page="previewPage" :page-size="20" :total="preview.items.length" layout="total, prev, pager, next" />
          <el-checkbox v-if="preview.valid" v-model="confirmed" :disabled="!editable">我已核对完整展示效果，确认发布并使旧报价失效</el-checkbox>
        </template>
      </template>
    </div>
    <NotificationDialog v-if="notificationsVisible" :access-id="access.id" @busy="value => { notificationBusy = value }" @close="closeNotifications" />
    <template #footer><GlassButton ref="notificationTrigger" v-permission="'portal_mapping:read'" :disabled="locked || loading || previewing" @click="openNotifications">查看映射通知</GlassButton>
      <GlassButton :disabled="locked" @click="close">关闭</GlassButton>
      <GlassButton :disabled="notificationBusy || state === 'sending' || loading" @click="load">重新读取当前版本（舍弃草稿）</GlassButton>
      <GlassButton v-permission="'portal_mapping:write'" :loading="previewing" :disabled="!editable || !data || !!stale.length" @click="runPreview">校验并预览</GlassButton>
      <GlassButton v-permission="'portal_mapping:write'" variant="primary" :loading="state === 'sending'" :disabled="!editable || !preview?.valid || !confirmed" @click="publish">发布映射</GlassButton>
    </template>
  </el-dialog>
</template>

<style scoped>
.mapping-status { color: var(--text-secondary); line-height: 1.6; }
:deep(.list-table .cell) { white-space: normal !important; word-break: normal !important; overflow-wrap: anywhere; }
.el-alert { margin: 12px 0; }
p, .mapping-conflicts div { overflow-wrap: anywhere; color: var(--text-secondary); }
.mapping-add { display: grid; grid-template-columns: 220px minmax(0, 1fr) auto; gap: 12px; align-items: center; margin-top: 16px; }
.mapping-entry { padding: 16px; margin-top: 16px; border: 1px solid var(--border-color); border-radius: 12px; }
.mapping-entry-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.mapping-entry-title div { min-width: 0; }
.mapping-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.el-select, .el-select-v2 { width: 100%; }
.el-pagination { overflow-x: auto; padding: 16px 0; }
.mapping-conflicts { padding-left: 20px; }
.mapping-conflicts li { margin-bottom: 12px; }
.el-checkbox { height: auto; white-space: normal; margin: 16px 0; }
:deep(.el-checkbox__label) { white-space: normal; line-height: 1.6; }
@media (max-width: 600px) { .mapping-add, .mapping-fields { grid-template-columns: 1fr; } }
</style>
<style>.portal-mapping-dialog { max-width: calc(100vw - 24px); } .portal-mapping-dialog .el-dialog__footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; } .portal-mapping-dialog .el-dialog__footer button { margin-left: 0; }</style>
