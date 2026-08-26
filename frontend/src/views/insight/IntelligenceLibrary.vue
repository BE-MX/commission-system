<template>
  <div class="page-wrapper">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="insight-library-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="page-header">
      <h1>情报采集库</h1>
      <div class="header-actions">
        <GlassButton variant="primary" :left-icon="Plus" @click="showSourceDialog = true" v-if="authStore.hasPermission('insight:admin')">
          添加信源
        </GlassButton>
        <GlassButton variant="secondary" :left-icon="Upload" @click="showUploadDialog = true" v-if="authStore.hasPermission('insight:admin')">
          上传 MD
        </GlassButton>
      </div>
    </div>

    <!-- 筛选栏 -->
    <el-card class="filter-card" shadow="never">
      <el-form :model="filterForm" inline>
        <el-form-item label="日期">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            value-format="YYYY-MM-DD"
            @change="handleFilterChange"
          />
        </el-form-item>
        <el-form-item label="信源类型">
          <el-select v-model="filterForm.source_types" multiple collapse-tags placeholder="全部" @change="handleFilterChange" style="width: 180px">
            <el-option label="RSS" value="google_alerts_rss" />
            <el-option label="XPOZ" value="xpoz" />
            <el-option label="竞品监控" value="competitor_monitor" />
            <el-option label="手工" value="manual" />
          </el-select>
        </el-form-item>
        <el-form-item label="可信度">
          <el-select v-model="filterForm.credibility_labels" multiple collapse-tags placeholder="全部" @change="handleFilterChange" style="width: 180px">
            <el-option label="已核实" value="verified" />
            <el-option label="可信" value="plausible" />
            <el-option label="存疑" value="uncertain" />
            <el-option label="无法核实" value="unverifiable" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filterForm.status" placeholder="全部" @change="handleFilterChange" style="width: 120px">
            <el-option label="活跃" value="active" />
            <el-option label="已归档" value="archived" />
            <el-option label="已标记" value="flagged" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词">
          <el-input v-model="filterForm.keyword" placeholder="搜索标题/内容" clearable @change="handleFilterChange" />
        </el-form-item>
        <el-form-item>
          <el-button @click="resetFilter">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 列表 -->
    <el-card class="list-card" shadow="never" v-loading="loading">
      <el-table :data="items" @selection-change="handleSelectionChange" @sort-change="libSort.onSortChange" border class="list-table">
        <el-table-column type="selection" min-width="40" />
        <el-table-column label="可信度" min-width="90" prop="credibility_label" sortable="custom">
          <template #default="{ row }">
            <el-tag :type="credibilityType(row.credibility_label)" size="small">
              {{ credibilityLabel(row.credibility_label) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标题" min-width="300" prop="title" sortable="custom">
          <template #default="{ row }">
            <div class="item-title">
              <el-icon v-if="row.is_featured" class="featured-star"><Star-Filled /></el-icon>
              <span>{{ row.title || '(无标题)' }}</span>
            </div>
            <div class="item-meta">
              <el-tag size="small" type="info">{{ row.source_type }}</el-tag>
              <span>{{ formatDate(row.collected_at) }}</span>
              <span v-if="row.related_competitor">{{ row.related_competitor }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" min-width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ row.item_type || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="80" prop="status" sortable="custom">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="toggleFeature(row)">
              {{ row.is_featured ? '取消精选' : '精选' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @change="loadItems"
        class="pagination"
      />
    </el-card>

    <!-- 批量操作栏 -->
    <div class="batch-bar" v-if="selectedItems.length > 0">
      <span>已选 {{ selectedItems.length }} 项</span>
      <el-button @click="batchFeature(true)">标记精选</el-button>
      <el-button @click="batchArchive">归档</el-button>
    </div>

    <!-- 上传 MD 弹窗 -->
    <el-dialog v-model="showUploadDialog" title="上传 Markdown" width="500px">
      <el-form :model="uploadForm" label-width="80px">
        <el-form-item label="标题">
          <el-input v-model="uploadForm.title" placeholder="留空使用文件名" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="uploadForm.tags" placeholder="逗号分隔" />
        </el-form-item>
        <el-form-item label="文件">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="1"
            accept=".md"
            :on-change="handleFileChange"
          >
            <el-button type="primary">选择文件</el-button>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showUploadDialog = false">取消</el-button>
        <el-button type="primary" @click="submitUpload" :loading="uploading">上传</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Upload, StarFilled } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { listItems, toggleItemFeature, batchFeature as apiBatchFeature, batchStatus, uploadMd } from '@/api/insight'
import { useTableSort } from '@/composables/useTableSort'
import { formatBeijingDate } from '@/utils/datetime'

const authStore = useAuthStore()
const libSort = useTableSort()

// 状态
const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const selectedItems = ref([])

// 筛选
const dateRange = ref([])
const filterForm = reactive({
  source_types: [],
  credibility_labels: [],
  status: '',
  keyword: '',
})

// 上传
const showUploadDialog = ref(false)
const uploadForm = reactive({ title: '', tags: '' })
const uploadRef = ref(null)
const uploadFile = ref(null)
const uploading = ref(false)

// 加载数据
async function loadItems() {
  loading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      ...filterForm,
      ...libSort.sortParams.value,
    }
    if (dateRange.value?.length === 2) {
      params.start_date = dateRange.value[0]
      params.end_date = dateRange.value[1]
    }
    if (filterForm.source_types.length) {
      params.source_types = filterForm.source_types.join(',')
    }
    if (filterForm.credibility_labels.length) {
      params.credibility_labels = filterForm.credibility_labels.join(',')
    }
    const res = await listItems(params)
    if (res.data?.code === 200) {
      items.value = res.data.data.items
      total.value = res.data.data.total
    }
  } finally {
    loading.value = false
  }
}

function handleFilterChange() {
  page.value = 1
  loadItems()
}

function resetFilter() {
  dateRange.value = []
  filterForm.source_types = []
  filterForm.credibility_labels = []
  filterForm.status = ''
  filterForm.keyword = ''
  libSort.reset()
  page.value = 1
  loadItems()
}

function handleSelectionChange(selection) {
  selectedItems.value = selection
}

// 精选
async function toggleFeature(row) {
  try {
    await toggleItemFeature(row.id)
    row.is_featured = !row.is_featured
    ElMessage.success('已更新')
  } catch {
    ElMessage.error('操作失败')
  }
}

async function batchFeature(isFeatured) {
  const ids = selectedItems.value.map(i => i.id)
  try {
    await apiBatchFeature(ids, isFeatured)
    ElMessage.success('批量更新成功')
    loadItems()
  } catch {
    ElMessage.error('批量更新失败')
  }
}

async function batchArchive() {
  const ids = selectedItems.value.map(i => i.id)
  try {
    await batchStatus(ids, 'archived')
    ElMessage.success('已归档')
    loadItems()
  } catch {
    ElMessage.error('归档失败')
  }
}

// 上传
function handleFileChange(file) {
  uploadFile.value = file.raw
}

async function submitUpload() {
  if (!uploadFile.value) {
    ElMessage.warning('请选择文件')
    return
  }
  uploading.value = true
  const formData = new FormData()
  formData.append('file', uploadFile.value)
  if (uploadForm.title) formData.append('title', uploadForm.title)
  if (uploadForm.tags) formData.append('tags', uploadForm.tags)
  try {
    await uploadMd(formData)
    ElMessage.success('上传成功')
    showUploadDialog.value = false
    uploadForm.title = ''
    uploadForm.tags = ''
    uploadFile.value = null
    uploadRef.value?.clearFiles()
    loadItems()
  } catch {
    ElMessage.error('上传失败')
  } finally {
    uploading.value = false
  }
}

// 辅助
function credibilityType(label) {
  const map = { verified: 'success', plausible: 'warning', uncertain: 'danger', unverifiable: 'info' }
  return map[label] || 'info'
}
function credibilityLabel(label) {
  const map = { verified: '已核实', plausible: '可信', uncertain: '存疑', unverifiable: '无法核实' }
  return map[label] || label
}
function statusType(status) {
  const map = { active: 'success', archived: 'info', flagged: 'warning' }
  return map[status] || 'info'
}
function formatDate(dt) {
  return formatBeijingDate(dt)
}

onMounted(loadItems)
</script>

<style scoped>
.page-wrapper {
  padding: 24px;
  /* 极光层（.lg-aurora，与工作台同源）定位上下文 */
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台/发票页） */
.insight-library-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   会覆盖就地渲染的 el-dialog 的 .el-overlay position: fixed。
   .batch-bar 本身是 position: fixed + z-index:100，天然在极光之上，不列入 */
.page-wrapper .page-header,
.page-wrapper .filter-card,
.page-wrapper .list-card {
  position: relative;
  z-index: 1;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-header h1 {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}
.header-actions {
  display: flex;
  gap: 8px;
}
/* 筛选/列表面板：同款渐变玻璃（scoped 覆盖 el-card 白底） */
.filter-card {
  margin-bottom: 16px;
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}
.list-card {
  margin-bottom: 16px;
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.list-card :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 右侧固定操作列：sticky 单元格 + background: inherit，行透明时会透底重影，
   改成磨砂不透明的暖白，表头/hover 态同步（同 invoice-manage.css） */
.list-card :deep(.el-table-fixed-column--right) {
  background-color: rgba(249, 244, 234, 0.97);
}
.list-card :deep(th.el-table-fixed-column--right) {
  background-color: rgba(246, 239, 226, 0.98);
}
.list-card :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) {
  background-color: rgba(245, 236, 220, 0.98);
}
.item-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
}
.featured-star {
  color: #f59e0b;
  font-size: 14px;
}
.item-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
  display: flex;
  gap: 8px;
  align-items: center;
}
.pagination {
  margin-top: 16px;
  justify-content: flex-end;
}
.batch-bar {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: #fff;
  padding: 12px 24px;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  display: flex;
  align-items: center;
  gap: 12px;
  z-index: 100;
}
</style>
