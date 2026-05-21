<template>
  <div class="asset-library-page">
    <!-- 左侧筛选面板 -->
    <aside class="filter-sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-header">
        <span class="sidebar-title">筛选</span>
        <el-button type="text" size="small" @click="resetFilters">重置</el-button>
      </div>

      <!-- 标签关键字筛选 -->
      <div class="filter-keyword-wrap">
        <el-input
          v-model="filterKeyword"
          placeholder="搜索标签"
          clearable
          size="small"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
      </div>

      <div class="filter-groups">
        <div
          v-for="dim in filteredDimensions"
          :key="dim.id"
          class="filter-group"
          :style="getDimDividerStyle(dim)"
        >
          <div class="filter-label">{{ dim.label }}</div>
          <div class="filter-tag-list">
            <div
              v-for="val in filteredValues(dim)"
              :key="val.id"
              class="filter-tag"
              :class="{ active: isTagSelected(dim.name, val.id) }"
              :style="getTagStyle(dim.name, val.id, val.color_hex)"
              @click="toggleTag(dim.name, val.id)"
            >
              <img
                v-if="val.image_path"
                :src="getTagImageUrl(val.image_path)"
                class="filter-tag-thumb"
              />
              {{ val.value }}
            </div>
          </div>
        </div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="main-content">
      <!-- 批量操作栏 -->
      <div v-if="isBatchMode" class="batch-toolbar">
        <span class="batch-info">已选择 {{ selectedAssets.length }} 项</span>
        <el-button type="primary" size="small" @click="handleBatchDownload">
          <el-icon><Download /></el-icon>批量下载
        </el-button>
        <el-button size="small" @click="clearSelection">取消选择</el-button>
      </div>

      <!-- 顶部工具栏 -->
      <div class="toolbar">
        <div class="toolbar-left">
          <el-input
            v-model="keyword"
            placeholder="搜索文件名或备注"
            clearable
            style="width: 280px"
            @keyup.enter="loadData"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-select v-model="sortBy" style="width: 140px" @change="loadData">
            <el-option label="上传时间" value="created_at" />
            <el-option label="文件名" value="file_name" />
            <el-option label="下载量" value="download_count" />
          </el-select>
          <el-select v-model="sortOrder" style="width: 100px" @change="loadData">
            <el-option label="降序" value="desc" />
            <el-option label="升序" value="asc" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-radio-group v-model="viewMode" size="small">
            <el-radio-button label="grid"><el-icon><Grid /></el-icon></el-radio-button>
            <el-radio-button label="list"><el-icon><List /></el-icon></el-radio-button>
          </el-radio-group>
        </div>
      </div>

      <!-- 内容区（可滚动） -->
      <div class="content-wrapper">
        <div v-if="loading" class="loading-wrap">
          <el-skeleton :rows="5" animated />
        </div>
        <div v-else-if="assets.length === 0" class="empty-wrap">
          <el-empty description="暂无素材" />
        </div>

        <!-- 网格视图 -->
        <div v-else-if="viewMode === 'grid'" class="asset-grid">
        <div
          v-for="asset in assets"
          :key="asset.id"
          class="asset-card"
          :class="{ selected: isAssetSelected(asset) }"
          @click="openPreview(asset)"
        >
          <div class="card-checkbox" @click.stop>
            <el-checkbox
              :model-value="isAssetSelected(asset)"
              @change="toggleSelectAsset(asset)"
              size="large"
            />
          </div>
          <div class="card-thumb">
            <img v-if="asset.file_type === 'image'" :src="getThumbUrl(asset.thumbnail_path || asset.storage_path)" />
            <div v-else-if="asset.file_type === 'video'" class="type-icon video"><el-icon><VideoPlay /></el-icon></div>
            <div v-else-if="asset.file_type === 'document'" class="type-icon doc"><el-icon><Document /></el-icon></div>
            <div v-else class="type-icon"><el-icon><Picture /></el-icon></div>
            <div v-if="asset.status === 'offline'" class="offline-badge">已下线</div>
          </div>
          <div class="card-info">
            <div class="card-name" :title="asset.file_name">{{ asset.file_name }}</div>
            <div class="card-meta">
              <span>{{ formatSize(asset.file_size) }}</span>
              <span>{{ formatDate(asset.created_at) }}</span>
            </div>
            <div class="card-tags">
              <div v-for="tag in asset.tags.slice(0, 3)" :key="tag.id" class="tag-with-thumb">
                <img v-if="tag.image_path" :src="getTagImageUrl(tag.image_path)" class="tag-thumb" />
                <el-tag size="small" effect="plain">
                  {{ tag.value }}
                </el-tag>
              </div>
            </div>
          </div>
          <div class="card-actions" @click.stop>
            <el-tooltip content="下载">
              <el-button circle size="small" @click="handleDownload(asset)">
                <el-icon><Download /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip content="收藏">
              <el-button circle size="small" @click="handleFavorite(asset)">
                <el-icon><Star /></el-icon>
              </el-button>
            </el-tooltip>
          </div>
        </div>
      </div>

      <!-- 列表视图 -->
      <el-table v-else :data="assets" style="width: 100%" @row-click="openPreview">
        <el-table-column label="缩略图" width="80">
          <template #default="{ row }">
            <img v-if="row.file_type === 'image'" :src="getThumbUrl(row.thumbnail_path || row.storage_path)" class="table-thumb" />
            <el-icon v-else size="24"><Picture /></el-icon>
          </template>
        </el-table-column>
        <el-table-column label="文件名" prop="file_name" min-width="200" show-overflow-tooltip />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="fileTypeTag(row.file_type)">{{ fileTypeLabel(row.file_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="标签" min-width="200">
          <template #default="{ row }">
            <div v-for="tag in row.tags" :key="tag.id" class="tag-with-thumb mr-4">
              <img v-if="tag.image_path" :src="getTagImageUrl(tag.image_path)" class="tag-thumb" />
              <el-tag size="small" effect="plain">
                {{ tag.value }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="160">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click.stop="handleDownload(row)">
              <el-icon><Download /></el-icon>
            </el-button>
            <el-button size="small" @click.stop="handleFavorite(row)">
              <el-icon><Star /></el-icon>
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      </div>

      <!-- 分页 -->
      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[12, 24, 48, 96]"
          layout="total, sizes, prev, pager, next"
          @change="loadData"
        />
      </div>
    </div>

    <!-- 预览弹窗 -->
    <el-dialog v-model="previewVisible" width="80%" :title="previewAsset?.file_name" destroy-on-close>
      <div class="preview-body">
        <div class="preview-media">
          <img v-if="previewAsset?.file_type === 'image'" :src="getFileUrl(previewAsset.storage_path)" class="preview-img" />
          <video v-else-if="previewAsset?.file_type === 'video'" :src="getFileUrl(previewAsset.storage_path)" controls class="preview-video" />
          <div v-else class="preview-doc">
            <el-icon size="64"><Document /></el-icon>
            <p>文档预览暂不支持，请下载后查看</p>
          </div>
        </div>
        <div class="preview-info">
          <h4>文件信息</h4>
          <p><label>文件名:</label> {{ previewAsset?.file_name }}</p>
          <p><label>类型:</label> {{ fileTypeLabel(previewAsset?.file_type) }}</p>
          <p><label>大小:</label> {{ formatSize(previewAsset?.file_size) }}</p>
          <p><label>上传时间:</label> {{ formatDate(previewAsset?.created_at) }}</p>
          <p><label>下载次数:</label> {{ previewAsset?.download_count }}</p>
          <div v-if="previewAsset?.tags?.length" class="preview-tags">
            <label>标签:</label>
            <el-tag v-for="tag in previewAsset.tags" :key="tag.id" size="small">{{ tag.value }}</el-tag>
          </div>
          <div v-if="previewAiTags.length" class="preview-ai-tags">
            <label>AI 建议:</label>
            <el-tag v-for="tag in previewAiTags" :key="tag.id" size="small" type="warning" effect="plain">{{ tag.value }}</el-tag>
          </div>
          <div class="preview-actions">
            <el-button type="primary" @click="handleDownload(previewAsset)">
              <el-icon><Download /></el-icon>下载
            </el-button>
            <el-button @click="handleFavorite(previewAsset)">
              <el-icon><Star /></el-icon>收藏
            </el-button>
            <el-button :loading="aiAnalyzing" @click="handleAiAnalyze(previewAsset)">
              <el-icon><MagicStick /></el-icon>AI 分析
            </el-button>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 收藏夹选择 -->
    <el-dialog v-model="favoriteDialogVisible" title="收藏到" width="360px">
      <div v-if="folders.length" class="folder-list">
        <div
          v-for="folder in folders"
          :key="folder.id"
          class="folder-item"
          :class="{ active: selectedFolderId === folder.id }"
          @click="selectedFolderId = folder.id"
        >
          <el-icon><Folder /></el-icon>
          <span>{{ folder.name }}</span>
        </div>
      </div>
      <el-empty v-else description="暂无收藏夹，请先创建" />
      <template #footer>
        <el-button @click="favoriteDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!selectedFolderId" @click="confirmFavorite">确定</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, reactive, watch, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Search, Grid, List, Download, Star, Picture,
  VideoPlay, Document, Folder, MagicStick,
} from '@element-plus/icons-vue'
import {
  getAssetList, getTagDimensions, downloadAsset, getFavoriteFolders,
  addFavoriteItem, analyzeAsset, batchDownload,
} from '@/api/asset'

const loading = ref(false)
const assets = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(24)
const keyword = ref('')
const sortBy = ref('created_at')
const sortOrder = ref('desc')
const viewMode = ref('grid')
const sidebarCollapsed = ref(false)

const dimensions = ref([])
const activeFilters = reactive({})

// 标签关键字筛选
const filterKeyword = ref('')

// 当前已加载素材拥有的标签 ID 集合（用于联动筛选）
const availableTagIds = ref(new Set())

// 根据关键字过滤后的维度（只包含有匹配标签值的维度）
const filteredDimensions = computed(() => {
  const dims = dimensions.value
  if (!filterKeyword.value.trim()) {
    return dims.filter(dim => dim.values?.length > 0)
  }
  const kw = filterKeyword.value.toLowerCase()
  return dims.filter(dim => dim.values?.some(v => v.value.toLowerCase().includes(kw)))
})

// 获取某个维度下过滤后的标签值
function filteredValues(dim) {
  let values = dim.values || []
  if (filterKeyword.value.trim()) {
    const kw = filterKeyword.value.toLowerCase()
    values = values.filter(v => v.value.toLowerCase().includes(kw))
  }
  // 联动筛选：当用户已选择某些标签且已加载素材时，只显示当前结果中存在的标签
  const hasActiveFilter = Object.values(activeFilters).some(arr => arr && arr.length > 0)
  if (hasActiveFilter && assets.value.length > 0 && availableTagIds.value.size > 0) {
    values = values.filter(v => availableTagIds.value.has(v.id))
  }
  return values
}

// 检查标签是否被选中
function isTagSelected(dimName, valId) {
  return (activeFilters[dimName] || []).includes(valId)
}

// 切换标签选中状态
function toggleTag(dimName, valId) {
  if (!activeFilters[dimName]) {
    activeFilters[dimName] = []
  }
  const idx = activeFilters[dimName].indexOf(valId)
  if (idx >= 0) {
    activeFilters[dimName].splice(idx, 1)
  } else {
    activeFilters[dimName].push(valId)
  }
}

// 获取标签样式（选中时显示标签库颜色）
function getTagStyle(dimName, valId, colorHex) {
  if (!isTagSelected(dimName, valId)) return {}
  const color = colorHex || '#d4941c'
  // 如果颜色是 rgb 格式，直接返回；如果是 hex，判断亮度决定文字颜色
  return {
    backgroundColor: color,
    color: isLightColor(color) ? '#1e1e2d' : '#fff',
    borderColor: 'transparent',
  }
}

// 简单判断颜色亮度
function isLightColor(color) {
  if (!color) return false
  // 处理 rgb(r,g,b) 格式
  const rgbMatch = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
  if (rgbMatch) {
    const r = parseInt(rgbMatch[1])
    const g = parseInt(rgbMatch[2])
    const b = parseInt(rgbMatch[3])
    return (r * 299 + g * 587 + b * 114) / 1000 > 160
  }
  // 处理 hex 格式
  let hex = color.replace('#', '')
  if (hex.length === 3) hex = hex.split('').map(c => c + c).join('')
  if (hex.length !== 6) return false
  const r = parseInt(hex.substr(0, 2), 16)
  const g = parseInt(hex.substr(2, 2), 16)
  const b = parseInt(hex.substr(4, 2), 16)
  return (r * 299 + g * 587 + b * 114) / 1000 > 160
}

// 获取维度分隔色条样式：取该维度下第一个有颜色的标签值
function getDimDividerStyle(dim) {
  const color = dim.values?.find(v => v.color_hex)?.color_hex
  if (!color) return {}
  return {
    borderLeft: `3px solid ${color}`,
    backgroundColor: color + '10',
  }
}

const previewVisible = ref(false)
const previewAsset = ref(null)

const favoriteDialogVisible = ref(false)
const folders = ref([])
const selectedFolderId = ref(null)
const favoriteTargetAsset = ref(null)
const aiAnalyzing = ref(false)
const previewAiTags = ref([])

// 批量操作
const selectedAssets = ref([])
const isBatchMode = computed(() => selectedAssets.value.length > 0)

// 初始化维度筛选状态
watch(dimensions, (dims) => {
  dims.forEach(d => {
    if (!(d.name in activeFilters)) {
      activeFilters[d.name] = []
    }
  })
}, { immediate: true })

// 标签筛选变化时自动加载
watch(activeFilters, () => {
  page.value = 1
  loadData()
}, { deep: true })

async function handleAiAnalyze(asset) {
  if (!asset) return
  aiAnalyzing.value = true
  previewAiTags.value = []
  try {
    const res = await analyzeAsset(asset.id)
    const data = res.data || {}
    const suggestions = data.suggestions || []
    previewAiTags.value = suggestions.flatMap(s => s.values.map(v => ({ id: v.tag_value_id, value: v.value })))
  } catch (e) {
    ElMessage.error('AI 分析失败')
  } finally {
    aiAnalyzing.value = false
  }
}

async function loadDimensions() {
  try {
    const res = await getTagDimensions()
    dimensions.value = res.data || []
  } catch (e) {
    console.warn('加载标签维度失败:', e)
  }
}

async function loadData() {
  loading.value = true
  try {
    // 构造 tag_filters 参数
    const tagFilters = {}
    for (const [dimName, ids] of Object.entries(activeFilters)) {
      if (ids && ids.length) {
        tagFilters[dimName] = ids
      }
    }

    const res = await getAssetList({
      keyword: keyword.value || undefined,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
      page: page.value,
      page_size: pageSize.value,
      tag_filters: Object.keys(tagFilters).length ? JSON.stringify(tagFilters) : undefined,
    })
    assets.value = res.data?.items || []
    total.value = res.data?.total || 0

    // 更新可用标签 ID 集合（联动筛选）
    const tagIds = new Set()
    assets.value.forEach(asset => {
      asset.tags?.forEach(tag => tagIds.add(tag.id))
    })
    availableTagIds.value = tagIds
  } catch (e) {
    ElMessage.error('加载素材失败')
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  keyword.value = ''
  filterKeyword.value = ''
  for (const key in activeFilters) {
    activeFilters[key] = []
  }
  page.value = 1
  loadData()
}

function openPreview(asset) {
  previewAsset.value = asset
  previewVisible.value = true
}

async function handleDownload(asset) {
  try {
    const res = await downloadAsset(asset.id)
    const blob = new Blob([res.data])
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = asset.file_name
    a.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success('下载开始')
  } catch (e) {
    ElMessage.error('下载失败')
  }
}

async function handleFavorite(asset) {
  favoriteTargetAsset.value = asset
  selectedFolderId.value = null
  try {
    const res = await getFavoriteFolders()
    folders.value = res.data || []
    favoriteDialogVisible.value = true
  } catch (e) {
    ElMessage.error('加载收藏夹失败')
  }
}

async function confirmFavorite() {
  if (!selectedFolderId.value || !favoriteTargetAsset.value) return
  try {
    await addFavoriteItem(selectedFolderId.value, { asset_id: favoriteTargetAsset.value.id })
    ElMessage.success('已收藏')
    favoriteDialogVisible.value = false
  } catch (e) {
    ElMessage.error('收藏失败')
  }
}

// ── 批量操作 ────────────────────────────────────────────

function toggleSelectAsset(asset) {
  const idx = selectedAssets.value.findIndex(a => a.id === asset.id)
  if (idx >= 0) {
    selectedAssets.value.splice(idx, 1)
  } else {
    selectedAssets.value.push(asset)
  }
}

function isAssetSelected(asset) {
  return selectedAssets.value.some(a => a.id === asset.id)
}

function clearSelection() {
  selectedAssets.value = []
}

async function handleBatchDownload() {
  if (selectedAssets.value.length === 0) return
  try {
    const ids = selectedAssets.value.map(a => a.id)
    const res = await batchDownload(ids)
    const blob = new Blob([res.data], { type: 'application/zip' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `leshine_assets_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.zip`
    a.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success('下载开始')
    clearSelection()
  } catch (e) {
    ElMessage.error('批量下载失败')
  }
}

// URL  helpers
function getThumbUrl(path) {
  if (!path) return ''
  return `/uploads/assets/${path}`
}

function getFileUrl(path) {
  if (!path) return ''
  return `/uploads/assets/${path}`
}

function getTagImageUrl(path) {
  if (!path) return ''
  return `/uploads/${path}`
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024
    i++
  }
  return `${bytes.toFixed(1)} ${units[i]}`
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fileTypeLabel(type) {
  return { image: '图片', video: '视频', document: '文档' }[type] || type
}

function fileTypeTag(type) {
  return { image: 'success', video: 'warning', document: 'info' }[type] || ''
}

onMounted(() => {
  // 移动端检测已移至路由守卫，此处仅加载数据
  loadDimensions()
  loadData()
})
</script>

<style scoped>
.asset-library-page {
  display: flex;
  gap: 16px;
}

/* 左侧筛选 */
.filter-sidebar {
  width: 220px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  position: sticky;
  top: 0;
  align-self: flex-start;
  max-height: calc(100vh - 48px);
  overflow-y: auto;
}
.filter-sidebar.collapsed {
  width: 0;
  padding: 0;
  overflow: hidden;
}
.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.sidebar-title {
  font-weight: 600;
  font-size: 15px;
  color: #1e1e2d;
}
.filter-group {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  border-bottom: 1px solid #f0f0f0;
}
.filter-group:last-child {
  border-bottom: none;
}
.filter-label {
  font-size: 13px;
  font-weight: 600;
  color: #333;
  margin-bottom: 8px;
  padding-left: 6px;
}

.filter-keyword-wrap {
  padding-bottom: 12px;
}

.filter-tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.filter-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
  background: #fff;
  cursor: pointer;
  font-size: 12px;
  line-height: 1.4;
  transition: all 0.15s;
  user-select: none;
}

.filter-tag:hover {
  border-color: #d4941c;
}

.filter-tag.active {
  font-weight: 500;
}

.filter-tag-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
}

/* 主内容 */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff;
  border-radius: 12px;
  padding: 12px 16px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  position: sticky;
  top: 0;
  z-index: 10;
}
.toolbar-left {
  display: flex;
  gap: 10px;
}
.toolbar-right {
  display: flex;
  gap: 10px;
  align-items: center;
}

/* 网格 */
.asset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
  padding: 4px;
}
.asset-card {
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
  position: relative;
}
.asset-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}
.card-thumb {
  aspect-ratio: 1;
  background: #f5f5f5;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  position: relative;
}
.card-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.type-icon {
  color: #ccc;
  font-size: 32px;
}
.type-icon.video { color: #e74c3c; }
.type-icon.doc { color: #3498db; }
.offline-badge {
  position: absolute;
  top: 8px;
  left: 8px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
}
.card-info {
  padding: 10px 12px;
}
.card-name {
  font-size: 13px;
  font-weight: 500;
  color: #1e1e2d;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 6px;
}
.card-meta {
  font-size: 11px;
  color: #999;
  display: flex;
  gap: 10px;
  margin-bottom: 6px;
}
.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.card-actions {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 6px;
  opacity: 0;
  transition: opacity 0.15s;
}
.asset-card:hover .card-actions {
  opacity: 1;
}

/* 表格 */
.table-thumb {
  width: 48px;
  height: 48px;
  object-fit: cover;
  border-radius: 6px;
}

/* 分页 */
.pagination-bar {
  display: flex;
  justify-content: flex-end;
  padding: 8px 0;
}

/* 预览 */
.preview-body {
  display: flex;
  gap: 20px;
  min-height: 400px;
}
.preview-media {
  flex: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8f8f8;
  border-radius: 8px;
  overflow: hidden;
}
.preview-img {
  max-width: 100%;
  max-height: 500px;
  object-fit: contain;
}
.preview-video {
  max-width: 100%;
  max-height: 500px;
}
.preview-doc {
  text-align: center;
  color: #999;
}
.preview-info {
  flex: 1;
  min-width: 240px;
}
.preview-info h4 {
  margin: 0 0 12px;
  font-size: 15px;
}
.preview-info p {
  margin: 8px 0;
  font-size: 13px;
  color: #666;
}
.preview-info label {
  color: #999;
  display: inline-block;
  width: 70px;
}
.preview-tags {
  margin-top: 12px;
}
.preview-tags .el-tag {
  margin: 4px 4px 0 0;
}
.preview-actions {
  margin-top: 20px;
  display: flex;
  gap: 10px;
}

/* 收藏夹 */
.folder-list {
  max-height: 300px;
  overflow-y: auto;
}
.folder-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.folder-item:hover,
.folder-item.active {
  background: #f0f0f5;
}

.loading-wrap,
.empty-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.mr-4 {
  margin-right: 4px;
}

.tag-with-thumb {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.tag-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid #e4e7ed;
}

/* 批量操作栏 */
.batch-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #fff;
  border-radius: 12px;
  padding: 12px 16px;
  margin-bottom: 16px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  position: sticky;
  top: 0;
  z-index: 10;
}

.batch-info {
  font-size: 14px;
  font-weight: 500;
  color: #1a1a2e;
  margin-right: auto;
}

/* 卡片复选框 */
.card-checkbox {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 2;
  opacity: 0;
  transition: opacity 0.15s;
}

.asset-card:hover .card-checkbox,
.asset-card.selected .card-checkbox {
  opacity: 1;
}

.asset-card.selected {
  box-shadow: 0 0 0 2px #d4941c;
}
</style>
