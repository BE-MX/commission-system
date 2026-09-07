<template>
  <div class="prompt-page">
    <p class="page-note">保存后，下一次生成立即使用新提示词。进行中的任务和历史图片保留各自的版本记录。</p>
    <div class="toolbar">
      <el-input v-model="searchForm.keyword" placeholder="搜索版本名称" clearable @keyup.enter="handleSearch" @clear="handleSearch" />
      <GlassButton variant="ghost" left-icon="Search" @click="handleSearch">查询</GlassButton>
      <GlassButton v-permission="'expo:admin'" variant="primary" left-icon="Plus" @click="openCreate">新建版本</GlassButton>
    </div>
    <div class="table-card">
      <el-table v-loading="loading" :data="list" border class="list-table">
        <el-table-column prop="name" label="版本名称" min-width="150" show-overflow-tooltip />
        <el-table-column prop="hint" label="客户可见说明" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" min-width="130"><template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_default ? '默认 · 启用' : row.is_active ? '启用' : '停用' }}</el-tag>
        </template></el-table-column>
        <el-table-column prop="revision" label="修订" min-width="75" />
        <el-table-column label="最后更新" min-width="165"><template #default="{ row }">{{ formatBeijingDateTime(row.updated_at) }}</template></el-table-column>
        <el-table-column label="操作" min-width="230" fixed="right"><template #default="{ row }">
          <GlassButton v-permission="'expo:admin'" variant="link" @click="openVersion(row.id)">编辑</GlassButton>
          <GlassButton v-permission="'expo:admin'" variant="link" @click="openVersion(row.id, true)">复制</GlassButton>
          <GlassButton v-permission="'expo:admin'" variant="link" :disabled="row.is_default || !row.is_active || defaultBusy" @click="makeDefault(row)">设为默认</GlassButton>
        </template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager"
        @current-change="handlePageChange" @size-change="handleSizeChange" />
    </div>

    <DetailDrawer :model-value="visible" :title="editId ? '编辑提示词版本' : '新建提示词版本'" width="min(900px, 100vw)" :loading="opening" :before-close="beforeClose" @update:model-value="visible = $event">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="editor-alert" />
      <template v-if="form">
        <el-form label-position="top">
          <div class="identity-fields">
            <el-form-item label="版本名称（客户可见）" required><el-input v-model="form.name" maxlength="80" show-word-limit /></el-form-item>
            <el-form-item label="启用"><el-switch v-model="form.is_active" :disabled="isDefault" /><span v-if="isDefault" class="field-help">先设置其他默认版本，才可停用</span></el-form-item>
          </div>
          <el-form-item label="版本说明（客户可见）"><el-input v-model="form.hint" maxlength="160" show-word-limit placeholder="简短说明此版本的效果" /></el-form-item>
          <el-tabs v-model="editorTab">
            <el-tab-pane label="主体与画面" name="main" />
            <el-tab-pane label="发色与穿搭" name="details" />
            <el-tab-pane label="场景描述" name="scenes" />
            <el-tab-pane label="完整提示词预览" name="preview" />
          </el-tabs>
          <template v-if="editorTab === 'main' || editorTab === 'details'">
            <el-form-item v-for="part in metadata.parts.filter(p => p.group === editorTab)" :key="part.key" :label="part.label" :required="part.required">
              <el-input v-model="form.config.parts[part.key]" type="textarea" :autosize="{ minRows: 3, maxRows: 14 }" maxlength="20000" />
              <div class="field-help"><template v-if="Object.keys(part.variables).length">可用占位符：<span v-for="(label, variable) in part.variables" :key="variable"><code>{{ '{' + variable + '}' }}</code> {{ label }}；</span></template><template v-else>直接填写文本。{{ part.required ? '' : '留空表示不添加本段要求。' }}</template></div>
            </el-form-item>
            <template v-if="editorTab === 'details'">
              <el-form-item label="穿搭候选（每行一套，留空关闭随机穿搭）"><el-input v-model="outfits" type="textarea" :autosize="{ minRows: 4, maxRows: 14 }" /></el-form-item>
              <el-form-item label="首饰候选（每行一组，留空关闭随机首饰）"><el-input v-model="jewelry" type="textarea" :autosize="{ minRows: 3, maxRows: 10 }" /></el-form-item>
            </template>
          </template>
          <template v-if="editorTab === 'scenes'">
            <el-form-item v-for="scene in metadata.scenes" :key="scene.key" :label="(scene.mode === 'tryon' ? '换发 · ' : '佩戴实拍 · ') + scene.label" required>
              <el-input v-model="form.config.scene_prompts[scene.key]" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }" maxlength="6000" />
            </el-form-item>
          </template>
          <template v-if="editorTab === 'preview'">
            <p class="field-help">预览当前未保存的内容，不生成图片、不扣额度。穿搭与首饰每次随机抽取。</p>
            <el-form-item label="生成模式"><el-radio-group v-model="previewMode" @change="previewScene = null; previewResult = null"><el-radio-button value="tryon">AI 换发试戴</el-radio-button><el-radio-button value="scene">佩戴实拍场景</el-radio-button></el-radio-group></el-form-item>
            <el-form-item label="场景"><el-select v-model="previewScene" clearable placeholder="换发保持原背景 / 佩戴实拍默认首景"><el-option v-for="scene in metadata.scenes.filter(s => s.mode === previewMode)" :key="scene.key" :label="scene.label" :value="scene.key.split(':')[1]" /></el-select></el-form-item>
            <template v-if="previewMode === 'tryon'">
              <el-form-item label="发型（可选）"><el-select v-model="previewWig" filterable clearable placeholder="不选使用示例发型描述"><el-option v-for="wig in wigs" :key="wig.wig_id" :label="wig.name" :value="wig.wig_id" /></el-select></el-form-item>
              <el-form-item label="发色（可选）"><el-select v-model="previewColor" filterable clearable placeholder="保持原色"><el-option v-for="color in colors" :key="color.id" :label="color.name" :value="color.id" /></el-select></el-form-item>
            </template>
            <GlassButton variant="ghost" :loading="previewBusy" @click="renderPreview">刷新完整提示词</GlassButton>
            <template v-if="previewResult"><p class="field-help">输入图片 {{ previewResult.image_count }} 张 · 输出 {{ previewResult.size || '按模型配置' }}</p><pre class="prompt-preview">{{ previewResult.prompt }}</pre></template>
          </template>
        </el-form>
      </template>
      <template #footer><GlassButton variant="ghost" :disabled="saving" @click="closeEditor(false)">取消</GlassButton><GlassButton v-permission="'expo:admin'" variant="primary" :loading="saving" :disabled="opening || !form" @click="save">保存并生效</GlassButton></template>
    </DetailDrawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { useListPage } from '@/composables/useListPage'
import { msgSuccess } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'
import { getPromptVersions, getPromptEditor, getPromptVersion, createPromptVersion, updatePromptVersion,
  setDefaultPromptVersion, previewPromptVersion, getWigPicker, getHairColors } from '@/api/expo'

const { list, loading, total, page, pageSize, searchForm, fetchList, handleSearch, handlePageChange, handleSizeChange } =
  useListPage(async params => (await getPromptVersions(params)).data, { searchForm: { keyword: '' } })
const visible = ref(false), opening = ref(false), saving = ref(false), defaultBusy = ref(false)
const form = ref(null), editId = ref(null), isDefault = ref(false), baseline = ref(''), error = ref('')
const metadata = ref({ parts: [], scenes: [] }), editorTab = ref('main')
const wigs = ref([]), colors = ref([]), previewMode = ref('tryon'), previewScene = ref(null)
const previewWig = ref(null), previewColor = ref(null), previewResult = ref(null), previewBusy = ref(false)
const dirty = computed(() => visible.value && form.value && JSON.stringify(form.value) !== baseline.value)
const lines = key => computed({ get: () => form.value.config[key].join('\n'), set: value => { form.value.config[key] = value.split('\n').filter(line => line.trim()) } })
const outfits = lines('outfit_options'), jewelry = lines('jewelry_options')
function message(exc) {
  const detail = exc?.response?.data?.detail
  return typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(e => e.msg).join('；') : '请求失败，请重试'
}
async function openCreate() {
  const response = await getPromptVersions({ page_size: 1 })
  const template = response.data.items[0]
  if (template) return openVersion(template.id, true)
  await openVersion(null)
}
async function openVersion(id, copy = false) {
  visible.value = true; opening.value = true; form.value = null; error.value = ''; editorTab.value = 'main'
  previewResult.value = null
  try {
    const [meta, detail] = await Promise.all([getPromptEditor(), id ? getPromptVersion(id) : Promise.resolve(null)])
    metadata.value = meta.data
    const row = detail?.data
    editId.value = copy ? null : id
    isDefault.value = !copy && !!row?.is_default
    form.value = { name: copy ? `${row.name} 副本` : row?.name || '', hint: row?.hint || '', is_active: copy ? true : row?.is_active ?? true,
      config: row?.config || { parts: Object.fromEntries(meta.data.parts.map(p => [p.key, ''])), scene_prompts: Object.fromEntries(meta.data.scenes.map(s => [s.key, ''])), outfit_options: [], jewelry_options: [] } }
    if (editId.value) form.value.expected_revision = row.revision
    baseline.value = JSON.stringify(form.value)
  } catch (exc) { error.value = message(exc) } finally { opening.value = false }
}
let discardPending = null
async function discardChanges() {
  if (!dirty.value) return true
  if (discardPending) return discardPending
  discardPending = ElMessageBox.confirm('尚有未保存的修改，确定放弃？', '离开编辑', {
    confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning',
  }).then(() => true, () => false)
  try { return await discardPending } finally { discardPending = null }
}
async function beforeClose(done) {
  if (saving.value || opening.value) return
  if (await discardChanges()) done()
}
async function closeEditor(value) {
  if (value || saving.value || opening.value) return
  if (await discardChanges()) visible.value = false
}
async function save() {
  if (saving.value) return
  saving.value = true; error.value = ''
  try {
    if (editId.value) await updatePromptVersion(editId.value, form.value)
    else await createPromptVersion(form.value)
    baseline.value = JSON.stringify(form.value); visible.value = false
    msgSuccess('保存'); await fetchList()
  } catch (exc) { error.value = message(exc) } finally { saving.value = false }
}
async function makeDefault(row) {
  defaultBusy.value = true
  try { await setDefaultPromptVersion(row.id, row.revision); msgSuccess('设置默认版本'); await fetchList() }
  finally { defaultBusy.value = false }
}
async function renderPreview() {
  previewBusy.value = true; error.value = ''
  try { previewResult.value = (await previewPromptVersion({ config: form.value.config, mode: previewMode.value, scene_key: previewScene.value || null, wig_id: previewWig.value || null, hair_color_id: previewColor.value || null })).data }
  catch (exc) { error.value = message(exc) } finally { previewBusy.value = false }
}
watch(editorTab, async tab => {
  if (tab !== 'preview' || wigs.value.length) return
  try { const [w, c] = await Promise.all([getWigPicker(), getHairColors({ only_active: 1 })]); wigs.value = w.data; colors.value = c.data }
  catch (exc) { error.value = message(exc) }
})
watch(form, () => { previewResult.value = null }, { deep: true })
onBeforeRouteLeave(async () => !saving.value && await discardChanges())
function beforeUnload(event) { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>

<style scoped>
.prompt-page { display: flex; flex-direction: column; gap: 16px; }
.page-note, .field-help { color: var(--el-text-color-secondary); line-height: 1.7; font-size: 13px; }
.page-note { margin: 0; }
.toolbar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.toolbar .el-input { width: 260px; }
.table-card { background: var(--dash-glass-bg); border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight); overflow: hidden; padding: 16px; }
.pager { justify-content: flex-end; margin-top: 16px; }
.identity-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.field-help { width: 100%; margin-top: 6px; }
.editor-alert { margin-bottom: 16px; }
.prompt-preview { white-space: pre-wrap; overflow-wrap: anywhere; background: var(--el-fill-color-light); border-radius: 8px; padding: 16px; font-size: 13px; line-height: 1.7; }
@media (max-width: 600px) { .identity-fields { grid-template-columns: 1fr; gap: 0; } .toolbar .el-input { width: 100%; } }
</style>
