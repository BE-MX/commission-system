<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Check, Close, Select } from '@element-plus/icons-vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { portalAdminApi } from '@/api/portal'
import { formatBeijingDateTime } from '@/utils/datetime'
import { msgError, msgSuccess } from '@/utils/feedback'
import { ACCESS_REQUEST_STATUS } from './portalStatus'

const DEFAULT_FILTERS = { status: 'pending', keyword: '' }
const filters = reactive({ ...DEFAULT_FILTERS })
const applied = ref({ ...DEFAULT_FILTERS })
const requests = ref([]), loading = ref(false), error = ref(''), selected = ref(null), accessId = ref(''), reason = ref(''), busy = ref('')
const pending = computed(() => filters.status !== applied.value.status || filters.keyword !== applied.value.keyword)
const filtered = computed(() => applied.value.keyword || applied.value.status !== DEFAULT_FILTERS.status)
const columnDefs = [{ key: 'name', label: '申请人' }, { key: 'email', label: '邮箱' }, { key: 'phone', label: '电话' }, { key: 'created-at', label: '申请时间（北京）' }, { key: 'status', label: '状态' }]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('portal-access-requests', columnDefs)
let controller

async function load() {
  loading.value = true; error.value = ''
  controller?.abort(); controller = new AbortController()
  try {
    const data = await portalAdminApi.accessRequests({ status: applied.value.status, keyword: applied.value.keyword }, controller.signal)
    requests.value = data.items || []
  } catch (e) {
    if (e.code !== 'REQUEST_ABORTED' && e.name !== 'CanceledError') error.value = e.message || '读取申请失败。'
  } finally { loading.value = false }
}
function search() { applied.value = { ...filters }; return load() }
function reset() { Object.assign(filters, DEFAULT_FILTERS); return search() }
function open(row) { selected.value = row; accessId.value = ''; reason.value = '' }
async function review(decision) {
  if (!selected.value || busy.value) return
  if (decision === 'approve' && !accessId.value.trim()) { msgError('批准前请填写已启用的客户门户授权 ID。'); return }
  if (!reason.value.trim()) { msgError('请填写审核备注。'); return }
  busy.value = decision
  try {
    await portalAdminApi.reviewAccessRequest(selected.value.id, { decision, access_id: decision === 'approve' ? accessId.value.trim() : null, reason: reason.value.trim() })
    msgSuccess(decision === 'approve' ? '申请已批准，激活邮件已进入发送队列。' : '申请已拒绝。')
    selected.value = null
    await load()
  } catch (e) { msgError(e.message || '处理申请失败。') } finally { busy.value = '' }
}
onMounted(load); onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <section class="portal-page portal-access-requests">
    <div class="portal-aurora lg-aurora" aria-hidden="true"><div class="lg-aurora__blob lg-aurora__blob--gold" /><div class="lg-aurora__blob lg-aurora__blob--amber" /><div class="lg-aurora__blob lg-aurora__blob--peach" /></div>
    <header class="page-header"><div><h2>客户账号申请</h2><p>先核对申请人，再绑定现有客户门户授权。批准后发送邮箱激活链接，客户自行设置密码。</p></div></header>
    <div ref="panelRef" class="table-card portal-panel">
      <FilterBar label="账号申请筛选" :loading="loading" :pending="pending" @search="search" @reset="reset">
        <el-input v-model="filters.keyword" aria-label="搜索申请" placeholder="姓名或邮箱" maxlength="100" clearable class="filter-w-lg" />
        <el-select v-model="filters.status" aria-label="申请状态" class="filter-w-sm"><el-option v-for="(entry, value) in ACCESS_REQUEST_STATUS" :key="value" :label="entry.label" :value="value" /></el-select>
      </FilterBar>
      <div class="action-bar">
        <TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columnDefs" :fullscreen="isFullscreen" :loading="loading" @refresh="load" @fullscreen="toggleFullscreen" />
      </div>
      <ListPageStatus :error="error" :loading="loading" :has-data="requests.length > 0" :paged="false" @retry="load" />
      <el-table v-loading="loading" :data="requests" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <template #empty><el-empty v-if="!loading && !error" :image-size="96" :description="filtered ? '没有符合条件的申请' : '暂无待审核申请'"><GlassButton v-if="filtered" left-icon="RefreshLeft" @click="reset">重置筛选</GlassButton></el-empty></template>
        <el-table-column v-if="visibleKeys.includes('name')" prop="full_name" label="申请人" min-width="130" max-width="220" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('email')" prop="email" label="邮箱" min-width="220" max-width="340" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('phone')" prop="phone" label="电话" min-width="140" max-width="200" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('created-at')" prop="created_at" label="申请时间（北京）" min-width="170" max-width="220"><template #default="{ row }">{{ formatBeijingDateTime(row.created_at) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('status')" prop="status" label="状态" min-width="100" max-width="160"><template #default="{ row }"><StatusBadge :value="row.status" :dictionary="ACCESS_REQUEST_STATUS" effect="plain" /></template></el-table-column>
        <el-table-column label="操作" fixed="right" min-width="100" max-width="140" class-name="table-action-column" :sortable="false"><template #default="{ row }"><GlassButton v-permission="'portal_access:admin'" variant="link" :left-icon="Select" :disabled="row.status !== 'pending'" @click="open(row)">审核</GlassButton></template></el-table-column>
      </el-table>
    </div>
    <el-dialog :model-value="Boolean(selected)" title="审核客户账号申请" width="640px" @update:model-value="value => { if (!value && !busy) selected = null }">
      <template v-if="selected">
        <dl class="request-detail"><div><dt>申请人</dt><dd>{{ selected.full_name }}</dd></div><div><dt>邮箱</dt><dd>{{ selected.email }}</dd></div><div><dt>电话</dt><dd>{{ selected.phone }}</dd></div><div><dt>申请时间</dt><dd>{{ formatBeijingDateTime(selected.created_at) }}</dd></div></dl>
        <el-alert title="批准不会让申请人直接登录。系统会把邮箱绑定到你选择的现有客户授权，并发送一次性激活链接，由客户设置邮箱密码。" type="info" :closable="false" />
        <el-form label-position="top" class="review-form">
          <el-form-item label="绑定客户授权 ID（批准必填）"><el-input v-model="accessId" placeholder="在「客户访问」页打开客户详情后复制授权 ID" maxlength="36" /></el-form-item>
          <el-form-item label="审核备注" required><el-input v-model="reason" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="说明核对结果" /></el-form-item>
        </el-form>
      </template>
      <template #footer>
        <div class="dialog-footer">
          <GlassButton variant="ghost" :disabled="Boolean(busy)" @click="selected = null">取消</GlassButton>
          <GlassButton variant="danger" :left-icon="Close" :loading="busy === 'reject'" :disabled="busy === 'approve'" @click="review('reject')">拒绝申请</GlassButton>
          <GlassButton variant="primary" :left-icon="Check" :loading="busy === 'approve'" :disabled="busy === 'reject'" @click="review('approve')">批准并发送激活邮件</GlassButton>
        </div>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped src="./portal-page.css"></style>
<style scoped>
.request-detail { display: grid; gap: 10px; margin: 0 0 14px; font-size: 13px; }
.request-detail div { display: flex; justify-content: space-between; gap: 16px; }
dt { color: var(--text-secondary); }
dd { margin: 0; color: var(--text-primary); overflow-wrap: anywhere; text-align: right; }
.review-form { margin-top: 16px; }
</style>
