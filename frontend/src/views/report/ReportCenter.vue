<template>
  <div class="report-center-page">
    <!-- 模板列表 -->
    <el-card v-if="!designerMode" shadow="never">
      <template #header>
        <div class="card-header">
          <span class="header-title">报表模板</span>
          <el-button
            v-if="authStore.hasAnyPermission(['report:design', 'report:admin'])"
            type="primary"
            size="small"
            @click="showCreateDialog"
          >
            新建模板
          </el-button>
        </div>
      </template>

      <el-table
        :data="templates"
        v-loading="loading"
        stripe
        style="width: 100%"
      >
        <el-table-column label="报表编码" prop="report_code" min-width="180" show-overflow-tooltip />
        <el-table-column label="报表名称" prop="name" min-width="200" show-overflow-tooltip />
        <el-table-column label="版本" prop="version" width="80" align="center" />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-switch
              v-if="authStore.hasPermission('report:admin')"
              :model-value="row.status === 1"
              size="small"
              @change="(val) => handleToggleStatus(row, val)"
            />
            <el-tag v-else :type="row.status === 1 ? 'success' : 'info'" size="small">
              {{ row.status === 1 ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" min-width="170">
          <template #default="{ row }">
            {{ formatTime(row.updated_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="previewReport(row)">查看</el-button>
            <el-button
              v-if="authStore.hasAnyPermission(['report:design'])"
              size="small"
              link
              type="warning"
              @click="openDesigner(row)"
            >
              设计器
            </el-button>
            <el-button
              v-if="authStore.hasAnyPermission(['report:design'])"
              size="small"
              link
              @click="showVersionHistory(row)"
            >
              版本
            </el-button>
            <el-button
              v-if="authStore.hasPermission('report:admin')"
              size="small"
              link
              type="danger"
              @click="handleDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Stimulsoft Designer 全屏模式 -->
    <div v-if="designerMode" class="designer-page">
      <div class="designer-toolbar">
        <el-button @click="closeDesigner" size="small">← 返回列表</el-button>
        <span class="toolbar-info">正在编辑：{{ designerTemplateName }}（v{{ designerTemplateVersion }}）</span>
        <el-button type="success" size="small" :loading="savingDesigner" @click="handleDesignerSave">保存</el-button>
      </div>
      <div ref="designerContainer" class="designer-container"></div>
    </div>

    <!-- 新建模板弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑模板信息' : '新建模板'"
      width="600px"
      destroy-on-close
    >
      <el-form :model="form" label-width="100px">
        <el-form-item label="报表编码" v-if="!isEdit">
          <el-input v-model="form.report_code" placeholder="如 production_order_print" />
        </el-form-item>
        <el-form-item label="报表名称">
          <el-input v-model="form.name" placeholder="报表显示名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
        <el-form-item label="模板内容" v-if="!isEdit">
          <el-input
            v-model="form.template_content"
            type="textarea"
            :rows="6"
            placeholder="粘贴 .mrt 模板 JSON（从 Stimulsoft Designer 导出）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveTemplate">保存</el-button>
      </template>
    </el-dialog>

    <!-- 报表预览弹窗 -->
    <el-dialog
      v-model="previewVisible"
      :title="`报表预览 — ${previewName}`"
      width="90%"
      top="2vh"
      destroy-on-close
    >
      <div class="preview-toolbar">
        <el-input
          v-model="previewParams.order_no"
          placeholder="输入订单号预览"
          style="width: 300px; margin-right: 12px;"
          clearable
        />
        <el-button type="primary" size="small" @click="refreshPreview">预览</el-button>
      </div>
      <StimulsoftViewer
        v-if="previewVisible && previewReady"
        :report-code="previewCode"
        :params="previewParams"
        height="75vh"
      />
    </el-dialog>

    <!-- 版本历史弹窗 -->
    <el-dialog
      v-model="versionDialogVisible"
      :title="`版本历史 — ${versionTemplateName}`"
      width="700px"
      destroy-on-close
    >
      <el-table :data="versionList" v-loading="versionLoading" stripe size="small">
        <el-table-column label="版本" width="80" align="center">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="变更说明" prop="change_summary" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.change_summary || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="保存时间" min-width="160">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="previewVersion(row)">预览</el-button>
            <el-button
              v-if="authStore.hasAnyPermission(['report:design'])"
              size="small"
              link
              type="warning"
              @click="handleRollback(row)"
            >
              回滚
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  getReportTemplates, createReportTemplate, updateReportTemplate,
  deleteReportTemplate, getTemplateVersions, rollbackTemplate,
  toggleTemplateStatus, getReportTemplate,
} from '@/api/reportCenter'
import { useStimulsoft } from '@/composables/useStimulsoft'
import StimulsoftViewer from '@/components/StimulsoftViewer.vue'

const authStore = useAuthStore()
const { createDesigner } = useStimulsoft()

const loading = ref(false)
const templates = ref([])

// ── 模板 CRUD ────────────────────────────────
const dialogVisible = ref(false)
const isEdit = ref(false)
const saving = ref(false)
const editingCode = ref('')

const form = ref({
  report_code: '',
  name: '',
  description: '',
  template_content: '',
})

function showCreateDialog() {
  isEdit.value = false
  editingCode.value = ''
  form.value = { report_code: '', name: '', description: '', template_content: '' }
  dialogVisible.value = true
}

function editTemplate(row) {
  isEdit.value = true
  editingCode.value = row.report_code
  form.value = {
    report_code: row.report_code,
    name: row.name,
    description: row.description || '',
    template_content: '',
  }
  dialogVisible.value = true
}

async function saveTemplate() {
  if (!form.value.name) {
    ElMessage.warning('请输入报表名称')
    return
  }

  saving.value = true
  try {
    if (isEdit.value) {
      const data = { name: form.value.name, description: form.value.description }
      if (form.value.template_content) {
        data.template_content = form.value.template_content
      }
      await updateReportTemplate(editingCode.value, data)
      ElMessage.success('模板已更新')
    } else {
      if (!form.value.report_code) {
        ElMessage.warning('请输入报表编码')
        saving.value = false
        return
      }
      await createReportTemplate(form.value)
      ElMessage.success('模板已创建')
    }
    dialogVisible.value = false
    await loadTemplates()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(`确定删除模板「${row.name}」？`, '确认删除', { type: 'warning' })
    await deleteReportTemplate(row.report_code)
    ElMessage.success('已删除')
    await loadTemplates()
  } catch {
    // 取消
  }
}

async function handleToggleStatus(row, val) {
  try {
    await toggleTemplateStatus(row.report_code, val ? 1 : 0)
    row.status = val ? 1 : 0
    ElMessage.success(val ? '已启用' : '已禁用')
  } catch (e) {
    ElMessage.error('状态切换失败')
  }
}

// ── Stimulsoft Designer ───────────────────────
const designerMode = ref(false)
const designerContainer = ref(null)
const designerTemplateCode = ref('')
const designerTemplateName = ref('')
const designerTemplateVersion = ref(0)
const savingDesigner = ref(false)
let designerInstance = null

async function openDesigner(row) {
  // 获取模板完整内容
  try {
    const res = await getReportTemplate(row.report_code)
    const template = res?.data ?? res

    designerTemplateCode.value = row.report_code
    designerTemplateName.value = row.name
    designerTemplateVersion.value = row.version
    designerMode.value = true

    await nextTick()

    // 动态加载 Designer JS
    const { createDesigner: createDesignerFn } = useStimulsoft()

    // 传入样例数据参数，让设计器加载字段结构到字典树
    const sampleParams = row.report_code === 'production_order_print' ? { order_no: '' } : {}
    designerInstance = await createDesignerFn(
      designerContainer.value,
      template.template_content || null,
      () => {
        // onSave 回调不自动保存，只更新本地引用
        // 实际保存由工具栏按钮触发
      },
      sampleParams,
      row.report_code,
    )
  } catch (e) {
    ElMessage.error('打开设计器失败: ' + (e.message || '未知错误'))
  }
}

async function handleDesignerSave() {
  if (!designerInstance) return
  savingDesigner.value = true
  try {
    const mrtText = designerInstance.report.saveToJsonString()
    await updateReportTemplate(designerTemplateCode.value, {
      template_content: mrtText,
      change_summary: '设计器编辑保存',
    })
    ElMessage.success('模板已保存')
    // 更新版本号
    designerTemplateVersion.value += 1
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    savingDesigner.value = false
  }
}

function closeDesigner() {
  if (designerInstance) {
    try { designerInstance.dispose() } catch {}
    designerInstance = null
  }
  designerMode.value = false
  loadTemplates()
}

// ── 版本历史 ──────────────────────────────────
const versionDialogVisible = ref(false)
const versionTemplateName = ref('')
const versionTemplateCode = ref('')
const versionList = ref([])
const versionLoading = ref(false)

async function showVersionHistory(row) {
  versionTemplateCode.value = row.report_code
  versionTemplateName.value = row.name
  versionDialogVisible.value = true
  versionLoading.value = true

  try {
    const res = await getTemplateVersions(row.report_code)
    versionList.value = res?.data ?? res ?? []
  } catch {
    versionList.value = []
  } finally {
    versionLoading.value = false
  }
}

function previewVersion(row) {
  // 用 ReportView 页面打开，传入版本信息
  // 这里简化为关闭版本弹窗后打开预览弹窗
  versionDialogVisible.value = false
  previewCode.value = versionTemplateCode.value
  previewName.value = `${versionTemplateName.value} v${row.version}`
  previewParams.value = { order_no: '' }
  previewReady.value = false
  previewVisible.value = true
  setTimeout(() => { previewReady.value = true }, 100)
}

async function handleRollback(row) {
  try {
    await ElMessageBox.confirm(
      `确定回滚到 v${row.version}？当前版本会保存到历史记录。`,
      '确认回滚',
      { type: 'warning' },
    )
    await rollbackTemplate(versionTemplateCode.value, row.version)
    ElMessage.success(`已回滚到 v${row.version}`)
    versionDialogVisible.value = false
    await loadTemplates()
  } catch {
    // 取消
  }
}

// ── 报表预览 ──────────────────────────────────
const previewVisible = ref(false)
const previewReady = ref(false)
const previewCode = ref('')
const previewName = ref('')
const previewParams = ref({})

function previewReport(row) {
  previewCode.value = row.report_code
  previewName.value = row.name
  previewParams.value = { order_no: '' }
  previewReady.value = false
  previewVisible.value = true
  setTimeout(() => { previewReady.value = true }, 100)
}

function refreshPreview() {
  previewReady.value = false
  setTimeout(() => { previewReady.value = true }, 100)
}

// ── 工具函数 ──────────────────────────────────
function formatTime(dt) {
  if (!dt) return ''
  return new Date(dt).toLocaleString('zh-CN')
}

async function loadTemplates() {
  loading.value = true
  try {
    const res = await getReportTemplates()
    templates.value = res?.data ?? res ?? []
  } catch {
    templates.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadTemplates()
})
</script>

<style scoped>
.report-center-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: #1e1e2d;
}

.preview-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
}

/* Designer 全屏模式 */
.designer-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 100px);
}

.designer-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 0;
  flex-shrink: 0;
}

.toolbar-info {
  flex: 1;
  font-size: 14px;
  color: #606266;
}

.designer-container {
  flex: 1;
  min-height: 0;
}
</style>
