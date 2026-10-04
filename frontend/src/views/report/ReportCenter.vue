<template>
  <div class="report-center-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="report-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 模板列表 -->
    <div v-if="!designerMode" class="template-list">
      <div class="card-header" style="margin-bottom: 16px;">
        <span class="header-title">报表模板</span>
      </div>

      <div ref="panelRef" class="table-card report-panel">
        <div class="action-bar">
          <GlassButton
            v-if="authStore.hasAnyPermission(['report:design', 'report:admin'])"
            variant="primary" left-icon="Plus"
            @click="showCreateDialog"
          >
            新建模板
          </GlassButton>
          <TableTools
            v-model:visible-keys="visibleKeys"
            v-model:density="density"
            :columns="columnDefs"
            :fullscreen="isFullscreen"
            @refresh="loadTemplates"
            @fullscreen="toggleFullscreen"
          />
        </div>
        <ListPageStatus :error="templatesResource.errorMessage.value" :loading="loading" :has-data="templates.length > 0" @retry="loadTemplates" />
        <el-table
          :data="templates"
          v-loading="loading"
          border
          class="list-table"
          :class="densityClass"
          :max-height="isFullscreen ? undefined : 640"
          style="width: 100%" v-sticky-scrollbar>
          <template #empty>
            <el-empty v-if="!loading && !templatesResource.error.value" :image-size="96" description="暂无数据" />
          </template>
          <el-table-column v-if="visibleKeys.includes('report-code')" label="报表编码" prop="report_code" min-width="180" max-width="270" show-overflow-tooltip />
          <el-table-column v-if="visibleKeys.includes('name')" label="报表名称" prop="name" min-width="200" max-width="300" show-overflow-tooltip />
          <el-table-column v-if="visibleKeys.includes('version')" label="版本" prop="version" min-width="80" max-width="120" />
          <el-table-column prop="status" v-if="visibleKeys.includes('status')" label="状态" min-width="100" max-width="150">
            <template #default="{ row }">
              <el-switch
                v-if="authStore.hasPermission('report:admin')"
                :model-value="row.status === 1"
                @change="(val) => handleToggleStatus(row, val)"
              />
              <StatusBadge v-else :type="row.status === 1 ? 'success' : 'info'" size="small" effect="plain">
                {{ row.status === 1 ? '启用' : '禁用' }}
              </StatusBadge>
            </template>
          </el-table-column>
          <el-table-column prop="updated_at" v-if="visibleKeys.includes('updated-at')" label="更新时间" min-width="170" max-width="255" show-overflow-tooltip>
            <template #default="{ row }">
              {{ formatTime(row.updated_at) }}
            </template>
          </el-table-column>
          <el-table-column class-name="table-action-column" label="操作" min-width="300" max-width="450" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="View" @click="previewReport(row)">查看</GlassButton>
              <GlassButton
                v-if="authStore.hasAnyPermission(['report:design'])"
                variant="link" left-icon="EditPen"
                @click="openDesigner(row)"
              >
                设计器
              </GlassButton>
              <GlassButton
                v-if="authStore.hasAnyPermission(['report:design'])"
                variant="link" left-icon="Clock"
                @click="showVersionHistory(row)"
              >
                版本
              </GlassButton>
              <GlassButton
                v-if="authStore.hasPermission('report:admin')"
                variant="link" link-tone="danger" left-icon="Delete"
                @click="handleDelete(row)"
              >
                删除
              </GlassButton>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- Stimulsoft Designer 全屏模式 -->
    <div v-if="designerMode" class="designer-page">
      <ListPageStatus :error="designerResource.errorMessage.value" :loading="designerResource.loading.value" :has-data="!!designerResource.data.value" @retry="retryDesigner" />
      <div class="designer-toolbar">
        <el-button @click="closeDesigner">← 返回列表</el-button>
        <span class="toolbar-info">正在编辑：{{ designerTemplateName }}（v{{ designerTemplateVersion }}）</span>
        <el-button type="success" :loading="savingDesigner" @click="handleDesignerSave">保存</el-button>
      </div>
      <div ref="designerContainer" class="designer-container"></div>
    </div>

    <!-- 新建模板弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑模板信息' : '新建模板'"
      width="640px"
      destroy-on-close
    >
      <el-form label-position="top" :model="form">
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
      width="480px"
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
        <el-button type="primary" @click="refreshPreview">预览</el-button>
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
      width="760px"
      destroy-on-close
    >
      <ListPageStatus :error="versionsResource.errorMessage.value" :loading="versionLoading" :has-data="versionList.length > 0" @retry="versionsResource.load()" />
      <el-table :data="versionList" v-loading="versionLoading" border class="list-table" v-sticky-scrollbar>
        <el-table-column prop="version" label="版本" min-width="80" max-width="120">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="变更说明" prop="change_summary" min-width="200" max-width="300" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.change_summary || '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="保存时间" min-width="160" max-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="200" max-width="300" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click="previewVersion(row)">预览</GlassButton>
            <GlassButton
              v-if="authStore.hasAnyPermission(['report:design'])"
              variant="link" left-icon="RefreshLeft"
              @click="handleRollback(row)"
            >
              回滚
            </GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>import { msgWarning, msgSuccessText, msgError, confirmAction } from '@/utils/feedback'
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { useAsyncResource } from '@/composables/useAsyncResource'

import { useAuthStore } from '@/stores/auth'
import {
  getReportTemplates, createReportTemplate, updateReportTemplate,
  deleteReportTemplate, getTemplateVersions, rollbackTemplate,
  toggleTemplateStatus, getReportTemplate,
} from '@/api/reportCenter'
import { useStimulsoft } from '@/composables/useStimulsoft'
import { useTableView } from '@/composables/useTableView'
import StimulsoftViewer from '@/components/StimulsoftViewer.vue'
import TableTools from '@/components/TableTools.vue'
import { formatBeijingDateTime } from '@/utils/datetime'

const authStore = useAuthStore()
const { createDesigner } = useStimulsoft()

const templatesResource = useAsyncResource(async (_, { signal }) => (await getReportTemplates({ signal, suppressToast: true })).data || [])
const loading = templatesResource.loading
const templates = computed(() => templatesResource.data.value || [])

// 列显隐元数据（TableTools 列设置面板数据源，Action Bar Spec）
const columnDefs = [
  { key: 'report-code', label: '报表编码' },
  { key: 'name', label: '报表名称' },
  { key: 'version', label: '版本' },
  { key: 'status', label: '状态' },
  { key: 'updated-at', label: '更新时间' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('report-center', columnDefs)

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
    msgWarning('请输入报表名称')
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
      msgSuccessText('模板已更新')
    } else {
      if (!form.value.report_code) {
        msgWarning('请输入报表编码')
        saving.value = false
        return
      }
      await createReportTemplate(form.value)
      msgSuccessText('模板已创建')
    }
    dialogVisible.value = false
    await loadTemplates()
  } catch (e) {
    msgError(e.response?.data?.detail || '保存失败', e)
  } finally {
    saving.value = false
  }
}

async function handleDelete(row) {
  try {
    await confirmAction(`确定删除模板「${row.name}」？`, '确认删除', { type: 'warning' })
    await deleteReportTemplate(row.report_code)
    msgSuccessText('已删除')
    await loadTemplates()
  } catch {
    // 取消
  }
}

async function handleToggleStatus(row, val) {
  try {
    await toggleTemplateStatus(row.report_code, val ? 1 : 0)
    row.status = val ? 1 : 0
    msgSuccessText(val ? '已启用' : '已禁用')
  } catch (e) {
    msgError('状态切换失败', e)
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
let designerSequence = 0
const designerResource = useAsyncResource(async (code, { signal }) => code ? (await getReportTemplate(code, { signal, suppressToast: true })).data || null : null)

async function openDesigner(row) {
  const sequence = ++designerSequence
  // 获取模板完整内容
  try {
    designerTemplateCode.value = row.report_code
    designerTemplateName.value = row.name
    designerTemplateVersion.value = row.version
    designerMode.value = true
    const code = row.report_code
    const success = await designerResource.load(code, { clear: true })
    if (!success || sequence !== designerSequence || !designerMode.value || designerTemplateCode.value !== code) return
    const template = designerResource.data.value
    await nextTick()
    if (sequence !== designerSequence || !designerMode.value || designerTemplateCode.value !== code) return

    // 动态加载 Designer JS
    const { createDesigner: createDesignerFn } = useStimulsoft()

    // 传入样例数据参数，让设计器加载字段结构到字典树
    const sampleParams = row.report_code === 'production_order_print' ? { order_no: '' } : {}
    const instance = await createDesignerFn(
      designerContainer.value,
      template.template_content || null,
      () => {
        // onSave 回调不自动保存，只更新本地引用
        // 实际保存由工具栏按钮触发
      },
      sampleParams,
      row.report_code,
    )
    if (sequence !== designerSequence || !designerMode.value || designerTemplateCode.value !== code) { instance.dispose(); return }
    if (designerInstance) designerInstance.dispose()
    designerInstance = instance
  } catch (e) {
    msgError('打开设计器失败: ' + (e.message || '未知错误'), e)
  }
}

async function handleDesignerSave() {
  if (!designerInstance) return
  const code = designerTemplateCode.value; const sequence = designerSequence
  savingDesigner.value = true
  try {
    const mrtText = designerInstance.report.saveToJsonString()
    await updateReportTemplate(code, {
      template_content: mrtText,
      change_summary: '设计器编辑保存',
    })
    msgSuccessText('模板已保存')
    // 更新版本号
    if (sequence === designerSequence && designerTemplateCode.value === code) designerTemplateVersion.value += 1
  } catch (e) {
    msgError('保存失败: ' + (e.response?.data?.detail || e.message), e)
  } finally {
    savingDesigner.value = false
  }
}

function retryDesigner() { return openDesigner({ report_code: designerTemplateCode.value, name: designerTemplateName.value, version: designerTemplateVersion.value }) }

function closeDesigner() {
  designerSequence++
  designerResource.load(null, { clear: true })
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
const versionsResource = useAsyncResource(async (code, { signal }) => code ? (await getTemplateVersions(code, { signal, suppressToast: true })).data || [] : [])
const versionList = computed(() => versionsResource.data.value || [])
const versionLoading = versionsResource.loading
watch(versionDialogVisible, opened => { if (!opened) versionsResource.load(null, { clear: true }) })

function showVersionHistory(row) {
  versionTemplateCode.value = row.report_code
  versionTemplateName.value = row.name
  versionDialogVisible.value = true
  return versionsResource.load(row.report_code, { clear: true })
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
    await confirmAction(
      `确定回滚到 v${row.version}？当前版本会保存到历史记录。`,
      '确认回滚',
      { type: 'warning' },
    )
    await rollbackTemplate(versionTemplateCode.value, row.version)
    msgSuccessText(`已回滚到 v${row.version}`)
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
  return formatBeijingDateTime(dt, { fallback: '' })
}

const loadTemplates = () => templatesResource.load()

onMounted(() => {
  loadTemplates()
})
</script>

<style scoped src="./report-center.css"></style>
