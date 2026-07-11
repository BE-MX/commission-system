<template>
  <div class="sop-page">
    <div class="page-heading"><div><h1>售后 SOP 管理</h1><p>上传后先检查解析和问题映射，再启用；历史售后仍保留原版本引用。</p></div><GlassButton v-permission="'aftersales:admin'" variant="primary" left-icon="Upload" @click="dialogVisible = true">上传新版本</GlassButton></div>
    <div class="table-card">
      <el-table :data="versions" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column prop="version_no" label="版本号" min-width="130" max-width="190" show-overflow-tooltip />
        <el-table-column prop="original_filename" label="文件名" min-width="190" max-width="320" show-overflow-tooltip />
        <el-table-column prop="clause_count" label="条款数" min-width="90" max-width="120" />
        <el-table-column prop="uploaded_by_name" label="上传人" min-width="100" max-width="150" show-overflow-tooltip />
        <el-table-column prop="reference_count" label="引用单据" min-width="90" max-width="120" />
        <el-table-column label="问题映射" min-width="110" max-width="160"><template #default="{ row }">{{ Object.keys(row.issue_mapping || {}).length }} / 11</template></el-table-column>
        <el-table-column label="解析状态" min-width="100" max-width="140"><template #default="{ row }"><el-tag :type="row.parse_status === 'parsed' ? 'success' : 'warning'" effect="plain">{{ row.parse_status }}</el-tag></template></el-table-column>
        <el-table-column label="生效状态" min-width="100" max-width="140"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'" effect="plain">{{ row.is_active ? '当前生效' : '未生效' }}</el-tag></template></el-table-column>
        <el-table-column prop="effective_date" label="生效日期" min-width="120" max-width="160" />
        <el-table-column label="操作" min-width="180" max-width="240" fixed="right"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="preview(row)">查看解析</GlassButton><GlassButton v-if="!row.is_active" v-permission="'aftersales:admin'" variant="link" link-tone="success" left-icon="CircleCheck" @click="activate(row)">启用</GlassButton></template></el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" title="上传售后 SOP" width="520px">
      <el-form label-position="top">
        <el-form-item label="版本号" required><el-input v-model="form.version_no" placeholder="如 2026.07.10-v2" /></el-form-item>
        <el-form-item label="生效日期" required><el-date-picker v-model="form.effective_date" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item>
        <el-form-item label="变更说明" required><el-input v-model="form.change_summary" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="DOCX / PDF" required><input type="file" accept=".docx,.pdf" @change="event => selectedFile = event.target.files?.[0] || null" /></el-form-item>
      </el-form>
      <template #footer><GlassButton variant="ghost" @click="dialogVisible = false">取消</GlassButton><GlassButton variant="primary" :loading="saving" @click="upload">上传并解析</GlassButton></template>
    </el-dialog>

    <el-drawer v-model="previewVisible" title="SOP 解析预览" size="620px">
      <div v-if="selectedVersion" class="preview-body">
        <div class="preview-summary"><strong>{{ selectedVersion.version_no }}</strong><span>{{ selectedVersion.clause_count }} 条 · 映射 {{ Object.keys(selectedVersion.issue_mapping || {}).length }}/11 类问题</span></div>
        <section v-for="(section, index) in selectedVersion.structured_content?.sections || []" :key="index"><h3>{{ section.title }}</h3><p v-for="(paragraph, pIndex) in section.paragraphs" :key="pIndex">{{ paragraph }}</p></section>
        <el-empty v-if="!selectedVersion.structured_content?.sections?.length" description="该文档没有可预览的标题章节" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { activateAfterSalesSop, getAfterSalesSopVersions, uploadAfterSalesSop } from '@/api/aftersales'
import { msgError, msgSuccess } from '@/utils/feedback'
const loading = ref(false); const saving = ref(false); const versions = ref([]); const dialogVisible = ref(false); const previewVisible = ref(false); const selectedVersion = ref(null); const selectedFile = ref(null)
const form = reactive({ version_no: '', effective_date: '', change_summary: '' })
async function fetchVersions() { loading.value = true; try { const response = await getAfterSalesSopVersions(); versions.value = response.data?.items || [] } finally { loading.value = false } }
function preview(row) { selectedVersion.value = row; previewVisible.value = true }
async function upload() {
  if (!selectedFile.value || !form.version_no || !form.effective_date || !form.change_summary.trim()) { msgError('请完整填写版本、日期、变更说明并选择文件'); return }
  saving.value = true
  try { await uploadAfterSalesSop(selectedFile.value, form); dialogVisible.value = false; msgSuccess('上传并解析 SOP'); await fetchVersions() } finally { saving.value = false }
}
async function activate(row) {
  const mapped = Object.keys(row.issue_mapping || {}).length
  if (!row.clause_count || mapped < 11) { msgError(`解析结果不完整：${row.clause_count || 0} 条，映射 ${mapped}/11；请修正文档后重新上传`); return }
  try { await ElMessageBox.confirm(`已确认 ${row.clause_count} 条内容和 ${mapped}/11 类问题映射。启用 ${row.version_no} 后，后续 AI 分析将引用此版本。`, '启用 SOP 确认', { type: 'warning' }) } catch { return }
  await activateAfterSalesSop(row.id); msgSuccess('启用 SOP'); await fetchVersions()
}
onMounted(fetchVersions)
</script>

<style scoped>
.page-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 20px; }.page-heading h1 { margin: 0 0 4px; color: var(--text-primary); font: 700 20px/1.3 var(--font-display); }.page-heading p { margin: 0; color: var(--text-secondary); font-size: 13px; }.preview-summary { display: flex; justify-content: space-between; gap: 12px; padding: 12px; border-radius: 8px; background: var(--color-gold-soft); color: var(--text-secondary); font-size: 12px; }.preview-summary strong { color: var(--text-primary); }.preview-body section { padding: 14px 0; border-bottom: 1px solid var(--border-color); }.preview-body h3 { color: var(--text-primary); font-size: 15px; }.preview-body p { color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
</style>
