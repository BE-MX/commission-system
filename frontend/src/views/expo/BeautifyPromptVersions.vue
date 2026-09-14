<template>
  <div class="beautify-page">
    <el-alert title="仅用于“美颜生成”的照片预处理。发布新版本只影响之后确认照片的新会话；最终生图不会再执行面部与皮肤处理。" type="info" :closable="false" show-icon />
    <div class="toolbar">
      <el-input v-model="searchForm.keyword" placeholder="搜索版本名称" clearable @keyup.enter="handleSearch" @clear="handleSearch" />
      <GlassButton variant="ghost" left-icon="Search" @click="handleSearch">查询</GlassButton>
      <GlassButton v-permission="'expo:admin'" variant="primary" left-icon="Plus" @click="openCreate">新建草稿</GlassButton>
    </div>
    <div class="table-card">
      <el-table v-loading="loading" :data="list" border class="list-table">
        <el-table-column prop="name" label="版本名称" min-width="190" />
        <el-table-column label="状态" min-width="110"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
        <el-table-column prop="revision" label="修订" min-width="80" />
        <el-table-column label="发布时间" min-width="170"><template #default="{ row }">{{ formatBeijingDateTime(row.published_at) || '—' }}</template></el-table-column>
        <el-table-column label="最后更新" min-width="170"><template #default="{ row }">{{ formatBeijingDateTime(row.updated_at) }}</template></el-table-column>
        <el-table-column label="操作" min-width="270" fixed="right"><template #default="{ row }">
          <GlassButton variant="link" @click="openVersion(row.id)">查看{{ row.status === 'draft' ? ' / 编辑' : '' }}</GlassButton>
          <GlassButton variant="link" @click="copyVersion(row.id)">复制草稿</GlassButton>
          <GlassButton v-if="row.status === 'draft'" variant="link" :disabled="busy" @click="publish(row)">发布</GlassButton>
          <GlassButton v-if="row.status === 'draft'" variant="link" :disabled="busy" @click="archive(row)">归档</GlassButton>
        </template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </div>

    <DetailDrawer :model-value="visible" :title="editId ? (readOnly ? '查看美颜提示词版本' : '编辑美颜提示词草稿') : '新建美颜提示词草稿'" width="min(900px, 100vw)" :loading="opening" :before-close="beforeClose" @update:model-value="visible = $event">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="drawer-alert" />
      <el-form v-if="form" label-position="top">
        <el-form-item label="版本名称" required><el-input v-model="form.name" maxlength="80" show-word-limit :disabled="readOnly" /></el-form-item>
        <el-form-item label="使用范围"><el-input model-value="仅用于美颜生成的照片预处理" disabled /></el-form-item>
        <el-form-item label="提示词正文" required>
          <el-input v-model="form.prompt_text" type="textarea" :autosize="{ minRows: 18, maxRows: 30 }" maxlength="30000" show-word-limit :disabled="readOnly" />
        </el-form-item>
        <div v-if="editId" class="preview-box">
          <p>真实图片预览使用已保存内容，会调用图片编辑服务并产生供应商成本；请先保存草稿。预览不创建客户会话，也不扣正式结果额度。</p>
          <input ref="previewInput" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="runPreview" />
          <GlassButton variant="ghost" :loading="previewing" :disabled="dirty" @click="previewInput?.click()">选择测试照片并预览</GlassButton>
          <img v-if="previewUrl" :src="previewUrl" alt="美颜提示词预览结果" />
        </div>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="close(false)">关闭</GlassButton>
        <GlassButton v-if="!readOnly" v-permission="'expo:admin'" variant="primary" :loading="saving" @click="save">保存草稿</GlassButton>
      </template>
    </DetailDrawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { useListPage } from '@/composables/useListPage'
import { msgError, msgSuccess } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'
import {
  archiveBeautifyPromptVersion, createBeautifyPromptVersion, getBeautifyPromptVersion,
  getBeautifyPromptVersions, previewBeautifyPromptVersion, publishBeautifyPromptVersion,
  updateBeautifyPromptVersion,
} from '@/api/expo'

const { list, loading, total, page, pageSize, searchForm, fetchList, handleSearch, handlePageChange, handleSizeChange } =
  useListPage(async params => (await getBeautifyPromptVersions(params)).data, { searchForm: { keyword: '' } })
const visible = ref(false), opening = ref(false), saving = ref(false), busy = ref(false)
const editId = ref(null), readOnly = ref(false), form = ref(null), baseline = ref(''), error = ref('')
const previewInput = ref(null), previewing = ref(false), previewUrl = ref('')
const dirty = computed(() => visible.value && !readOnly.value && form.value && JSON.stringify(form.value) !== baseline.value)
const statusLabel = status => ({ draft: '草稿', published: '已发布', archived: '已归档' }[status] || status)
const statusType = status => ({ draft: 'warning', published: 'success', archived: 'info' }[status] || 'info')
function message(exc) { const detail = exc?.response?.data?.detail; return typeof detail === 'string' ? detail : '请求失败，请重试' }

function openCreate() {
  editId.value = null; readOnly.value = false; form.value = { name: '', prompt_text: '' }
  baseline.value = JSON.stringify(form.value); error.value = ''; previewUrl.value = ''; visible.value = true
}
async function openVersion(id, copy = false) {
  visible.value = true; opening.value = true; error.value = ''; previewUrl.value = ''
  try {
    const row = (await getBeautifyPromptVersion(id)).data
    editId.value = copy ? null : id
    readOnly.value = !copy && row.status !== 'draft'
    form.value = { name: copy ? `${row.name} 副本` : row.name, prompt_text: row.prompt_text }
    if (!copy) form.value.expected_revision = row.revision
    baseline.value = JSON.stringify(form.value)
  } catch (exc) { error.value = message(exc) } finally { opening.value = false }
}
const copyVersion = id => openVersion(id, true)
async function save() {
  saving.value = true; error.value = ''
  try {
    if (editId.value) await updateBeautifyPromptVersion(editId.value, form.value)
    else await createBeautifyPromptVersion(form.value)
    baseline.value = JSON.stringify(form.value); visible.value = false; msgSuccess('草稿已保存'); await fetchList()
  } catch (exc) { error.value = message(exc) } finally { saving.value = false }
}
async function publish(row) {
  try { await ElMessageBox.confirm('发布后，新确认照片的美颜会话将使用此版本。确定发布？', '发布美颜提示词', { type: 'warning' }) }
  catch { return }
  busy.value = true
  try { await publishBeautifyPromptVersion(row.id, row.revision); msgSuccess('发布'); await fetchList() }
  catch (exc) { msgError(message(exc)) }
  finally { busy.value = false }
}
async function archive(row) {
  try { await ElMessageBox.confirm('归档后此草稿不能继续编辑，确定归档？', '归档美颜提示词', { type: 'warning' }) }
  catch { return }
  busy.value = true
  try { await archiveBeautifyPromptVersion(row.id, row.revision); msgSuccess('归档'); await fetchList() }
  catch (exc) { msgError(message(exc)) }
  finally { busy.value = false }
}
async function runPreview(event) {
  const file = event.target.files?.[0]; event.target.value = ''
  if (!file || !editId.value) return
  previewing.value = true; error.value = ''
  try { previewUrl.value = (await previewBeautifyPromptVersion(editId.value, form.value.expected_revision, file)).data.image_url }
  catch (exc) { error.value = message(exc) } finally { previewing.value = false }
}
async function discardChanges() {
  if (!dirty.value) return true
  try { await ElMessageBox.confirm('尚有未保存的修改，确定放弃？', '离开编辑', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning' }); return true }
  catch { return false }
}
async function beforeClose(done) { if (!saving.value && await discardChanges()) done() }
async function close(value) { if (!value && await discardChanges()) visible.value = false }
onBeforeRouteLeave(async () => !saving.value && await discardChanges())
function beforeUnload(event) { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>

<style scoped>
.beautify-page { display: flex; flex-direction: column; gap: 16px; }
.toolbar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.toolbar .el-input { width: 260px; }
.table-card { padding: 16px; overflow: hidden; border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight); }
.pager { justify-content: flex-end; margin-top: 16px; }
.drawer-alert { margin-bottom: 16px; }
.preview-box { padding: 16px; border: 1px solid var(--el-border-color); border-radius: 10px; }
.preview-box p { margin: 0 0 12px; color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.7; }
.preview-box img { display: block; width: min(100%, 480px); max-height: 520px; margin-top: 16px; border-radius: 10px; object-fit: contain; }
@media (max-width: 600px) { .toolbar .el-input { width: 100%; } }
</style>
