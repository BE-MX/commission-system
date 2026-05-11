<template>
  <div class="sources-page">
    <div class="page-header">
      <div>
        <h2>信源配置管理</h2>
        <p class="subtitle">管理行业情报日报的所有信源 (RSS / 爬虫 / API)。当前为配置阶段,实际抓取尚未实现。</p>
      </div>
      <div class="header-actions">
        <GlassButton variant="link" left-icon="ArrowLeft" @click="goBack">返回</GlassButton>
        <GlassButton variant="primary" left-icon="Plus" @click="openCreate">新增信源</GlassButton>
      </div>
    </div>

    <el-table :data="sources" v-loading="loading" border class="source-table" style="width: 100%">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
      <el-table-column label="类型" width="140">
        <template #default="{ row }">
          <el-tag size="small" effect="light">{{ TYPE_LABELS[row.source_type] || row.source_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="url" label="URL" min-width="240" show-overflow-tooltip />
      <el-table-column label="管线" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.pipeline === 'external' ? 'info' : 'success'">{{ row.pipeline === 'external' ? '外部' : '内部' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="抓取间隔" width="100">
        <template #default="{ row }">{{ row.fetch_interval_hours }}h</template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="健康度" width="120">
        <template #default="{ row }">
          <span v-if="row.consecutive_failures === 0" class="health ok">正常</span>
          <span v-else class="health bad">连续失败 {{ row.consecutive_failures }} 次</span>
        </template>
      </el-table-column>
      <el-table-column label="最近抓取" min-width="160">
        <template #default="{ row }">
          <div class="last-fetched">
            <span>{{ row.last_fetched_at ? formatTime(row.last_fetched_at) : '从未' }}</span>
            <span v-if="row.last_error" class="last-error" :title="row.last_error">⚠ 上次失败</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <GlassButton variant="link" left-icon="Connection" @click="testOne(row)">测试连通</GlassButton>
          <GlassButton variant="link" left-icon="Edit" @click="openEdit(row)">编辑</GlassButton>
          <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="disable(row)">禁用</GlassButton>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新增/编辑 -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑信源' : '新增信源'" width="600px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="如: Google Alerts - hair extensions" />
        </el-form-item>
        <el-form-item label="类型" prop="source_type">
          <el-select v-model="form.source_type" style="width: 100%">
            <el-option v-for="(label, key) in TYPE_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="URL" prop="url">
          <el-input v-model="form.url" placeholder="完整 URL (含 https://)" />
        </el-form-item>
        <el-form-item label="管线">
          <el-select v-model="form.pipeline" style="width: 100%">
            <el-option label="外部信源" value="external" />
            <el-option label="内部信源" value="internal" />
          </el-select>
        </el-form-item>
        <el-form-item label="抓取间隔(小时)">
          <el-input-number v-model="form.fetch_interval_hours" :min="1" :max="168" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" :max="999" />
        </el-form-item>
        <el-form-item label="是否启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
        <el-form-item label="关键词(JSON)" v-if="form.source_type === 'google_alerts_rss'">
          <el-input v-model="keywordsText" type="textarea" :rows="2" placeholder='["hair extensions", "wig review"]' />
        </el-form-item>
        <el-form-item label="CSS 选择器" v-if="form.source_type === 'amazon_bestseller' || form.source_type === 'competitor_html'">
          <el-input v-model="form.css_selector" placeholder=".product-row" />
        </el-form-item>
        <el-form-item label="自定义请求头(JSON)">
          <el-input v-model="headersText" type="textarea" :rows="2" placeholder='{"User-Agent": "..."}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="dialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submitForm">保存</GlassButton>
      </template>
    </el-dialog>

    <!-- 测试结果 -->
    <el-dialog v-model="testResultVisible" title="连通性测试结果" width="500px">
      <div v-if="testResult" class="test-result">
        <el-result
          :icon="testResult.success ? 'success' : 'error'"
          :title="testResult.success ? '连接成功' : '连接失败'"
          :sub-title="`耗时 ${testResult.latency_ms}ms${testResult.status_code ? ' · HTTP ' + testResult.status_code : ''}`"
        />
        <div v-if="testResult.error" class="error-detail">
          <strong>错误信息:</strong>
          <pre>{{ testResult.error }}</pre>
        </div>
        <div v-if="testResult.preview && testResult.preview.length" class="preview-list">
          <h5>预览前 5 条:</h5>
          <ul>
            <li v-for="(p, i) in testResult.preview" :key="i">{{ p.title }}</li>
          </ul>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listSources, createSource, updateSource, deleteSource, testSource,
} from '@/api/insight'
import GlassButton from '@/components/GlassButton.vue'

const router = useRouter()
function goBack() {
  router.back()
}

const TYPE_LABELS = {
  google_alerts_rss: 'Google Alerts RSS',
  pinterest_scrape: 'Pinterest 爬虫',
  google_trends_rss: 'Google Trends RSS',
  amazon_bestseller: 'Amazon 排行榜',
  competitor_rss: '竞品 RSS',
  competitor_html: '竞品 HTML 爬虫',
  aihot_api: 'AIHot API',
}

const sources = ref([])
const loading = ref(false)

const dialogVisible = ref(false)
const isEdit = ref(false)
const editId = ref(null)
const saving = ref(false)
const formRef = ref()
const form = reactive({
  name: '',
  source_type: 'google_alerts_rss',
  url: '',
  pipeline: 'external',
  fetch_interval_hours: 24,
  sort_order: 0,
  is_active: true,
  css_selector: '',
})
const keywordsText = ref('')
const headersText = ref('')

const rules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  source_type: [{ required: true, message: '请选择类型', trigger: 'change' }],
  url: [{ required: true, message: '请输入 URL', trigger: 'blur' }],
}

const testResultVisible = ref(false)
const testResult = ref(null)

async function refresh() {
  loading.value = true
  try {
    const res = await listSources({})
    sources.value = res.data || []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  isEdit.value = false
  editId.value = null
  Object.assign(form, {
    name: '', source_type: 'google_alerts_rss', url: '',
    pipeline: 'external', fetch_interval_hours: 24, sort_order: 0,
    is_active: true, css_selector: '',
  })
  keywordsText.value = ''
  headersText.value = ''
  dialogVisible.value = true
}

function openEdit(row) {
  isEdit.value = true
  editId.value = row.id
  Object.assign(form, {
    name: row.name,
    source_type: row.source_type,
    url: row.url,
    pipeline: row.pipeline,
    fetch_interval_hours: row.fetch_interval_hours,
    sort_order: row.sort_order || 0,
    is_active: row.is_active,
    css_selector: row.css_selector || '',
  })
  keywordsText.value = row.keywords ? JSON.stringify(row.keywords, null, 2) : ''
  headersText.value = row.request_headers ? JSON.stringify(row.request_headers, null, 2) : ''
  dialogVisible.value = true
}

async function submitForm() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  let keywords = null
  let headers = null
  try {
    if (keywordsText.value.trim()) keywords = JSON.parse(keywordsText.value)
  } catch (e) {
    ElMessage.error('关键词 JSON 格式错误')
    return
  }
  try {
    if (headersText.value.trim()) headers = JSON.parse(headersText.value)
  } catch (e) {
    ElMessage.error('请求头 JSON 格式错误')
    return
  }
  const payload = { ...form, keywords, request_headers: headers }
  saving.value = true
  try {
    if (isEdit.value) {
      await updateSource(editId.value, payload)
      ElMessage.success('已更新')
    } else {
      await createSource(payload)
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    refresh()
  } finally {
    saving.value = false
  }
}

async function disable(row) {
  await ElMessageBox.confirm(`确定要禁用「${row.name}」?`, '请确认', {
    type: 'warning',
    confirmButtonText: '禁用',
    cancelButtonText: '取消',
  })
  await deleteSource(row.id)
  ElMessage.success('已禁用')
  refresh()
}

async function testOne(row) {
  const res = await testSource(row.id)
  testResult.value = res.data
  testResultVisible.value = true
  refresh()
}

function formatTime(s) {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}

onMounted(refresh)
</script>

<style scoped>
.sources-page { padding: 0; }

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
  gap: 16px;
}

.page-header h2 {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary, #1a1a2e);
  margin: 0;
}

.subtitle {
  font-size: 12px;
  color: var(--text-tertiary, #8b95a5);
  margin: 6px 0 0;
}

.header-actions { display: flex; gap: 8px; flex-shrink: 0; }

.source-table {
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
}

.health.ok { color: #16a34a; font-size: 12px; }
.health.bad { color: #dc2626; font-size: 12px; font-weight: 600; }

.last-fetched { display: flex; flex-direction: column; gap: 2px; }
.last-fetched span { font-size: 12px; }
.last-error { color: #dc2626; font-size: 11px; }

.test-result {
  text-align: center;
}

.test-result :deep(.el-result__title) { font-size: 16px; }
.test-result :deep(.el-result__subtitle) { font-size: 12px; }

.error-detail {
  text-align: left;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  padding: 10px;
  margin-top: 12px;
}

.error-detail pre {
  font-size: 12px;
  color: #991b1b;
  margin-top: 6px;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.preview-list {
  text-align: left;
  margin-top: 12px;
  padding: 10px 14px;
  background: #fafbfe;
  border-radius: 8px;
}

.preview-list h5 { font-size: 12px; color: var(--text-secondary, #4a5568); margin: 0 0 6px; }

.preview-list ul { padding-left: 18px; margin: 0; }
.preview-list li { font-size: 12px; color: var(--text-secondary, #4a5568); padding: 2px 0; }
</style>
