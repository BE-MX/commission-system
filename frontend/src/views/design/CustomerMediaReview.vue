<template>
  <div class="review-page">
    <div class="review-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" /><div class="lg-aurora__blob lg-aurora__blob--amber" /><div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>
    <header class="page-header"><div><h2>拍摄素材审核</h2><p>审核通过后，客户会立即在专属门户看到本批原始素材。</p></div><GlassButton left-icon="Refresh" @click="load">刷新</GlassButton></header>
    <div class="table-card review-panel">
      <el-table :data="rows" v-loading="loading" class="list-table" border>
        <el-table-column prop="customer_name" label="客户名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="customer_id" label="客户ID" min-width="130" />
        <el-table-column prop="revision" label="修订" min-width="80"><template #default="{ row }">R{{ row.revision }}</template></el-table-column>
        <el-table-column label="素材" min-width="110"><template #default="{ row }">{{ row.assets.length }} 个</template></el-table-column>
        <el-table-column prop="submitted_at" label="送审时间" min-width="180" />
        <el-table-column label="状态" min-width="110"><template #default><el-tag type="warning" effect="plain">待审核</el-tag></template></el-table-column>
        <el-table-column label="操作" min-width="120" fixed="right"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="open(row)">审核</GlassButton></template></el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="drawer" title="审核客户素材" size="72%">
      <template v-if="current">
        <div class="drawer-summary"><strong>{{ current.customer_name }}</strong><span>ID {{ current.customer_id }} · R{{ current.revision }} · {{ current.assets.length }} 个文件</span></div>
        <div class="asset-grid">
          <article v-for="asset in current.assets" :key="asset.id" class="asset-card">
            <img v-if="asset.media_type === 'image'" :src="asset.content_url" :alt="asset.file_name" @click="previewUrl = asset.content_url" />
            <video v-else :src="asset.content_url" controls preload="metadata" />
            <div>
              <strong>{{ asset.file_name }}</strong><span>{{ formatSize(asset.file_size) }}</span>
              <div class="asset-tags">
                <el-tag
                  v-for="tag in (asset.tags || [])"
                  :key="`${tag.dimension_id}-${tag.tag_value_id}`"
                  size="small"
                  effect="plain"
                  class="tag-chip"
                >{{ tagLabel(tag) }}</el-tag>
                <span v-if="!(asset.tags || []).length" class="no-tag">未打标签</span>
                <el-button link type="primary" size="small" class="tag-edit" @click="openTagPicker(asset)">编辑标签</el-button>
              </div>
            </div>
          </article>
        </div>
        <el-form label-position="top" class="review-form"><el-form-item label="审核意见"><el-input v-model="comment" type="textarea" :rows="4" placeholder="退回时必须填写明确的修改原因；通过时可选填" /></el-form-item></el-form>
      </template>
      <template #footer>
        <GlassButton variant="danger" :loading="saving" @click="decide('request_changes')">退回修改</GlassButton>
        <GlassButton variant="success" :loading="saving" @click="decide('approve')">通过并发布</GlassButton>
      </template>
    </el-drawer>
    <el-image-viewer v-if="previewUrl" :url-list="[previewUrl]" @close="previewUrl = ''" />
    <CustomerMediaTagPicker
      v-model="tagPickerVisible"
      :title="`编辑标签 · ${tagTarget?.file_name || ''}`"
      :dimensions="tagDimensions"
      :tags="tagTarget?.tags || []"
      :saving="tagSaving"
      hint="客户标签会展示在客户素材门户，命名即对外可见。"
      @save="saveTags"
      @created="onTagCreated"
    />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getCustomerTagDimensions,
  getMediaReviews,
  reviewMediaBatch,
  updateMediaAssetTags,
} from '@/api/customerMedia'
import CustomerMediaTagPicker from './customer-media/CustomerMediaTagPicker.vue'

const rows = ref([]); const loading = ref(false); const saving = ref(false); const drawer = ref(false); const current = ref(null); const comment = ref(''); const previewUrl = ref('')
const tagDimensions = ref([])
const tagPickerVisible = ref(false)
const tagSaving = ref(false)
const tagTarget = ref(null)

async function load() { loading.value = true; try { rows.value = (await getMediaReviews()).data || [] } finally { loading.value = false } }
async function loadTagDimensions() { try { tagDimensions.value = (await getCustomerTagDimensions()).data || [] } catch { /* 标签编辑不可用不阻断审核 */ } }
function open(row) { current.value = row; comment.value = ''; drawer.value = true }
function formatSize(bytes) { return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB` }
function tagLabel(tag) { return tag.dimension_label ? `${tag.dimension_label}：${tag.value}` : tag.value }

function openTagPicker(asset) { tagTarget.value = asset; tagPickerVisible.value = true }

async function saveTags({ tags, flat }) {
  if (!current.value || !tagTarget.value) return
  tagSaving.value = true
  try {
    await updateMediaAssetTags(current.value.id, tagTarget.value.id, tags)
    tagTarget.value.tags = flat
    ElMessage.success('标签已更新')
    tagPickerVisible.value = false
  } catch { /* 拦截器已提示 */ } finally { tagSaving.value = false }
}

// 行内新建标签后同步进维度列表
function onTagCreated({ dimension_id, value }) {
  const dim = tagDimensions.value.find(d => d.id === dimension_id)
  if (dim && !(dim.values || []).some(v => v.id === value.id)) {
    dim.values = [...(dim.values || []), value]
  }
}

async function decide(action) {
  if (action === 'request_changes' && !comment.value.trim()) { ElMessage.warning('退回时必须填写修改原因'); return }
  try { await ElMessageBox.confirm(action === 'approve' ? '审核通过后将立即发布给客户。' : '确认退回设计师修改？', '确认审核', { type: action === 'approve' ? 'success' : 'warning' }) } catch { return }
  saving.value = true
  try {
    await reviewMediaBatch(current.value.id, { action, comment: comment.value || undefined, lock_version: current.value.lock_version })
    ElMessage.success(action === 'approve' ? '已发布' : '已退回')
    drawer.value = false; await load()
  } finally { saving.value = false }
}
onMounted(() => { load(); loadTagDimensions() })
</script>

<style scoped>
.review-page { position: relative; }.review-aurora { inset: -24px -28px; }.page-header,.review-panel { position: relative; z-index: 1; }.page-header { display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:20px }.page-header h2{margin:0 0 5px}.page-header p{margin:0;color:var(--text-secondary)}
.review-panel{background:var(--dash-glass-bg);border:1px solid var(--dash-glass-border);border-radius:var(--dash-card-radius);overflow:hidden}.drawer-summary{display:grid;gap:5px;margin-bottom:18px}.drawer-summary span,.asset-card span{color:var(--text-secondary)}.asset-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}.asset-card{border:1px solid var(--border-color);border-radius:12px;overflow:hidden;background:var(--card-bg)}.asset-card img,.asset-card video{width:100%;aspect-ratio:4/3;object-fit:cover;background:var(--page-bg)}.asset-card>div{padding:10px;display:grid;gap:4px}.asset-card strong{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.review-form{margin-top:20px}
.asset-tags{display:flex;flex-wrap:wrap;align-items:center;gap:5px}.tag-chip{max-width:150px;overflow:hidden;text-overflow:ellipsis}.no-tag{color:var(--text-muted);font-size:12px}.tag-edit{margin-left:auto}
</style>
