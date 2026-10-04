<template>
  <div class="review-page">
    <div class="review-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" /><div class="lg-aurora__blob lg-aurora__blob--amber" /><div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>
    <header class="page-header"><div><h2>拍摄素材审核</h2><p>审核通过后，客户会立即在专属门户看到本批原始素材。</p></div></header>
    <div ref="panelRef" class="table-card review-panel">
      <!-- 操作行：TableTools 四图标（Action Bar Spec；原页头「刷新」由工具图标承担） -->
      <div class="action-bar">
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="load"
          @fullscreen="toggleFullscreen"
        />
      </div>
      <ListPageStatus :error="reviewsResource.errorMessage.value" :loading="loading" :has-data="rows.length > 0" @retry="load" />
      <el-table :data="rows" v-loading="loading" class="list-table" :class="densityClass" border :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <template #empty>
          <el-empty v-if="!loading && !reviewsResource.error.value" :image-size="96" description="暂无数据" />
        </template>
        <el-table-column v-if="visibleKeys.includes('customer-name')" prop="customer_name" label="客户名称" min-width="180" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('customer-id')" prop="customer_id" label="客户ID" min-width="130" />
        <el-table-column v-if="visibleKeys.includes('revision')" prop="revision" label="修订" min-width="80"><template #default="{ row }">R{{ row.revision }}</template></el-table-column>
        <el-table-column prop="assets.length" v-if="visibleKeys.includes('assets')" label="素材" min-width="110"><template #default="{ row }">{{ row.assets.length }} 个</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('submitted-at')" prop="submitted_at" label="送审时间" min-width="180" />
        <el-table-column :sort-by="() => '待审核'" v-if="visibleKeys.includes('status')" label="状态" min-width="110"><template #default><StatusBadge type="warning" effect="plain">待审核</StatusBadge></template></el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="120" fixed="right"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="open(row)">审核</GlassButton></template></el-table-column>
      </el-table>
    </div>

    <DetailDrawer v-model="drawer" title="审核客户素材" width="640px">
      <ListPageStatus :error="dimensionsResource.errorMessage.value" :loading="dimensionsResource.loading.value" :has-data="tagDimensions.length > 0" @retry="loadTagDimensions" />
      <ListPageStatus :error="customerTagsResource.errorMessage.value" :loading="customerTagsResource.loading.value" :has-data="customerTags.length > 0" @retry="customerTagsResource.load()" />
      <template v-if="current">
        <div class="drawer-summary"><strong>{{ current.customer_name }}</strong><span>ID {{ current.customer_id }} · R{{ current.revision }} · {{ current.assets.length }} 个文件</span></div>
        <div v-for="group in reviewGroups" :key="group.id" class="review-dimension">
          <h3>{{ group.label }} <span>{{ visibleGroupAssets(group).length }} / {{ group.assets.length }} 个文件</span></h3>
          <div v-for="filter in group.filters" :key="filter.id" class="review-filter-row">
            <strong>{{ filter.label }}</strong>
            <div class="review-filter-options">
              <el-button v-for="value in filter.values" :key="value.id" :type="(groupSelections[group.id] || []).includes(value.id) ? 'primary' : 'default'" @click="toggleGroupTag(group.id, value.id)">{{ value.value }}</el-button>
            </div>
          </div>
          <section class="review-tag-group">
            <div class="asset-grid">
          <article v-for="asset in visibleGroupAssets(group)" :key="asset.id" class="asset-card">
            <div class="asset-thumb"><img v-if="asset.media_type === 'image'" :src="asset.content_url" :alt="asset.file_name" @click="previewUrl = asset.content_url" /><video v-else :src="asset.content_url" controls preload="metadata" /></div>
            <div>
              <strong>{{ asset.file_name }}</strong><span>{{ formatSize(asset.file_size) }}</span>
              <div class="asset-tags">
                <StatusBadge
                  v-for="tag in (asset.tags || [])"
                  :key="`${tag.dimension_id}-${tag.tag_value_id}`"
                  size="small"
                  effect="plain"
                  class="tag-chip"
                >{{ tagLabel(tag) }}</StatusBadge>
                <span v-if="!(asset.tags || []).length" class="no-tag">未打标签</span>
                <el-button link type="primary" class="tag-edit" @click="openTagPicker(asset)">编辑标签</el-button>
              </div>
            </div>
          </article>
            </div>
            <p v-if="!visibleGroupAssets(group).length" class="group-empty">没有符合筛选条件的素材</p>
          </section>
        </div>
        <el-empty v-if="!reviewGroups.length" description="没有符合筛选条件的素材" />
        <el-form label-position="top" class="review-form"><el-form-item label="审核意见"><el-input v-model="comment" type="textarea" :rows="4" placeholder="退回时必须填写明确的修改原因；通过时可选填" /></el-form-item></el-form>
      </template>
      <template #footer>
        <GlassButton variant="danger" :loading="saving" @click="decide('request_changes')">退回修改</GlassButton>
        <GlassButton variant="success" :loading="saving" @click="decide('approve')">通过并发布</GlassButton>
      </template>
    </DetailDrawer>
    <el-image-viewer v-if="previewUrl" :url-list="[previewUrl]" @close="previewUrl = ''" />
    <CustomerMediaTagPicker
      v-model="tagPickerVisible"
      :title="`编辑标签 · ${tagTarget?.file_name || ''}`"
      :dimensions="tagDimensions"
      :available-tags="customerTags"
      :context="{ customerId: current?.customer_id, batchId: current?.id }"
      :tags="tagTarget?.tags || []"
      :saving="tagSaving"
      hint="客户标签会展示在客户素材门户，命名即对外可见。"
      @save="saveTags"
      @created="onTagCreated"
      @renamed="onTagRenamed"
    />
  </div>
</template>

<script setup>import { msgSuccessText, msgWarning, confirmAction } from '@/utils/feedback'
import { computed, onMounted, ref, watch } from 'vue'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useAuthStore } from '@/stores/auth'
import { designActorScope } from './designListScope'

import {
  getCustomerTagDimensions,
  getBatchCustomerTags,
  getMediaReviews,
  reviewMediaBatch,
  updateMediaAssetTags,
} from '@/api/customerMedia'
import CustomerMediaTagPicker from './customer-media/CustomerMediaTagPicker.vue'
import { filterMediaByTags, groupMediaByTags } from './customer-media/customerMediaGrouping'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'

// 列配置数组：TableTools 列显隐的数据源（操作列不进配置）
const columnDefs = [
  { key: 'customer-name', label: '客户名称' },
  { key: 'customer-id', label: '客户ID' },
  { key: 'revision', label: '修订' },
  { key: 'assets', label: '素材' },
  { key: 'submitted-at', label: '送审时间' },
  { key: 'status', label: '状态' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('customer-media-review', columnDefs)

const reviewsResource = useAsyncResource(async (_, { signal }) => (await getMediaReviews(undefined, { signal, suppressToast: true })).data || [])
const rows = computed(() => reviewsResource.data.value || []); const loading = reviewsResource.loading; const saving = ref(false); const drawer = ref(false); const current = ref(null); const comment = ref(''); const previewUrl = ref('')
const dimensionsResource = useAsyncResource(async (_, { signal }) => (await getCustomerTagDimensions({ signal, suppressToast: true })).data || [])
const tagDimensions = computed(() => dimensionsResource.data.value || [])
const customerTagsResource = useAsyncResource(async (id, { signal }) => id ? (await getBatchCustomerTags(id, { signal, suppressToast: true })).data || [] : [])
const customerTags = computed({ get: () => customerTagsResource.data.value || [], set: value => { customerTagsResource.data.value = value } })
const authStore = useAuthStore()
watch(() => designActorScope(authStore), () => { current.value = null; drawer.value = false; tagPickerVisible.value = false; reviewsResource.load(null, { clear: true }); dimensionsResource.load(null, { clear: true }); customerTagsResource.load(null, { clear: true }) }, { flush: 'sync' })
const tagPickerVisible = ref(false)
const tagSaving = ref(false)
const tagTarget = ref(null)
const groupSelections = ref({})
const reviewGroups = computed(() => groupMediaByTags(current.value?.assets || [], tagDimensions.value))
function toggleGroupTag(groupId, tagId) {
  const selected = groupSelections.value[groupId] || []
  groupSelections.value[groupId] = selected.includes(tagId) ? selected.filter(id => id !== tagId) : [...selected, tagId]
}
function visibleGroupAssets(group) {
  const available = new Set(group.filters.flatMap(filter => filter.values.map(value => value.id)))
  return filterMediaByTags(group.assets, (groupSelections.value[group.id] || []).filter(id => available.has(id)))
}

const load = () => reviewsResource.load()
const loadTagDimensions = () => dimensionsResource.load()
async function open(row) {
  current.value = row; comment.value = ''; groupSelections.value = {}; tagPickerVisible.value = false; tagTarget.value = null; drawer.value = true
  return customerTagsResource.load(row.id, { clear: true })
}
function formatSize(bytes) { return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB` }
function tagLabel(tag) { return tag.dimension_label ? `${tag.dimension_label}：${tag.value}` : tag.value }

function openTagPicker(asset) { tagTarget.value = asset; tagPickerVisible.value = true }

async function saveTags({ tags }) {
  if (!current.value || !tagTarget.value) return
  const batchId = current.value.id; const assetId = tagTarget.value.id; const actorScope = designActorScope(authStore)
  tagSaving.value = true
  try {
    const selectedDimensions = new Set(tags.map(item => item.dimension_id))
    const cleared = [...new Set((tagTarget.value.tags || []).map(item => item.dimension_id))]
      .filter(id => !selectedDimensions.has(id))
      .map(dimension_id => ({ dimension_id, tag_value_ids: [] }))
    const response = await updateMediaAssetTags(batchId, assetId, [...tags, ...cleared])
    if (designActorScope(authStore) !== actorScope || current.value?.id !== batchId || tagTarget.value?.id !== assetId) return
    current.value.assets = response.data.assets
    tagTarget.value = current.value.assets.find(asset => asset.id === tagTarget.value.id) || null
    for (const groupId of Object.keys(groupSelections.value)) groupSelections.value[groupId] = groupSelections.value[groupId].filter(id => current.value.assets.some(asset =>
      (asset.tags || []).some(tag => tag.tag_value_id === id)))
    await load()
    msgSuccessText('标签已更新')
    tagPickerVisible.value = false
  } catch { /* 拦截器已提示 */ } finally { tagSaving.value = false }
}

// 行内新建标签后同步进维度列表
function onTagCreated({ dimension_id, value }) {
  if (!customerTags.value.some(tag => tag.tag_value_id === value.id)) customerTags.value.push({
    dimension_id, tag_value_id: value.id, value: value.value,
    dimension_label: tagDimensions.value.find(dim => dim.id === dimension_id)?.label || '',
  })
}
function onTagRenamed({ id, value }) {
  customerTags.value = customerTags.value.map(tag => tag.tag_value_id === id ? { ...tag, value } : tag)
  if (current.value) current.value.assets = current.value.assets.map(asset => ({
    ...asset,
    tags: (asset.tags || []).map(tag => tag.tag_value_id === id ? { ...tag, value } : tag),
  }))
  tagTarget.value = current.value?.assets.find(asset => asset.id === tagTarget.value?.id) || null
}

async function decide(action) {
  if (action === 'request_changes' && !comment.value.trim()) { msgWarning('退回时必须填写修改原因'); return }
  const row = current.value
  if (!row) return
  const batchId = row.id; const actorScope = designActorScope(authStore)
  const submittedComment = comment.value || undefined
  try { await confirmAction(action === 'approve' ? '审核通过后将立即发布给客户。' : '确认退回设计师修改？', '确认审核', { type: action === 'approve' ? 'success' : 'warning' }) } catch { return }
  if (designActorScope(authStore) !== actorScope || current.value?.id !== batchId) return
  saving.value = true
  try {
    await reviewMediaBatch(batchId, { action, comment: submittedComment, lock_version: row.lock_version })
    msgSuccessText(action === 'approve' ? '已发布' : '已退回')
    if (designActorScope(authStore) !== actorScope) return
    if (current.value?.id === batchId) drawer.value = false; await load()
  } finally { saving.value = false }
}
onMounted(() => { load(); loadTagDimensions() })
</script>

<style scoped>
.review-page { position: relative; }.review-aurora { inset: -24px -28px; }.page-header,.review-panel { position: relative; z-index: 1; }.page-header { display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:20px }.page-header h2{margin:0 0 5px}.page-header p{margin:0;color:var(--text-secondary)}
.review-panel{background:var(--dash-glass-bg);border:1px solid var(--dash-glass-border);border-radius:var(--dash-card-radius);overflow:hidden}.drawer-summary{display:grid;gap:5px;margin-bottom:18px}.drawer-summary span,.asset-card span{color:var(--text-secondary)}.asset-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}.asset-card{min-width:0;border:1px solid var(--border-color);border-radius:12px;overflow:hidden;background:var(--card-bg)}.asset-thumb{display:flex;align-items:center;justify-content:center;height:200px;overflow:hidden;background:var(--page-bg)}.asset-thumb img,.asset-thumb video{display:block;width:auto;max-width:100%;height:200px;object-fit:contain}.asset-card>div:not(.asset-thumb){padding:10px;display:grid;gap:4px}.asset-card strong{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.review-form{margin-top:20px}
.asset-tags{display:flex;flex-wrap:wrap;align-items:center;gap:5px}.tag-chip{max-width:150px;overflow:hidden;text-overflow:ellipsis}.no-tag{color:var(--text-muted);font-size:12px}.tag-edit{margin-left:auto}
.review-filter-row { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin: 0 0 10px; }
.review-filter-row strong { min-width: 92px; }
.review-filter-options { display: flex; flex-wrap: wrap; gap: 6px; }
.review-filter-options .el-button { margin-left: 0; }
.review-dimension { margin: 22px 0; }
.review-dimension h3 { margin: 0 0 14px; }
.review-dimension h3 span { margin-left: 8px; color: var(--text-secondary); font-size: 12px; font-weight: 400; }
.group-empty { color: var(--text-secondary); font-size: 13px; }
.review-tag-group { margin: 0 0 20px; }
.review-tag-group h4 { margin: 0 0 10px; color: var(--color-primary-text); }
.review-tag-group h4 span { color: var(--text-secondary); font-size: 12px; font-weight: 400; }
</style>
