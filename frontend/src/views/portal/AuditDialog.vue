<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useListPage } from '@/composables/useListPage'
import { useAuthStore } from '@/stores/auth'
import { portalAdminApi } from '@/api/portal'
import { formatBeijingDateTime } from '@/utils/datetime'

const props = defineProps({ requestId: { type: String, required: true } })
const emit = defineEmits(['close'])
const auth = useAuthStore(), error = ref('')
let generation = 0, controller, disposed = false
const actors = { employee: '员工', customer: '客户账号', system: '系统' }
const actions = { 'order.submitted': '提交请求', 'order.proposed': '提出确认方案', 'order.accepted': '接受方案', 'order.rejected': '拒绝方案', 'order.cancelled': '取消请求', 'order.invoice_created': '生成 PI', 'order.approval_failed': '审核失败', 'order.pi_voided': '作废 PI', 'order.pi_downloaded': '下载 PI', 'invoice.portal_withdrawn': '撤回 PI 发布' }
const fields = { line_count: '产品行数', invoice_id: '发票 ID', employee_id: '员工 ID', publication_count: '撤回发布数', revision_id: '修订 ID', publication_id: '发布 ID', status: '状态', invoice_status: '发票状态' }
const { list, total, page, pageSize, loading, fetchList, handlePageChange, handleSizeChange } = useListPage(async params => {
  const current = ++generation
  controller?.abort(); controller = new AbortController()
  list.value = []; total.value = 0; error.value = ''
  try {
    const result = await portalAdminApi.audit(props.requestId, params, controller.signal)
    if (disposed || current !== generation) return { items: [], total: 0 }
    if (result?.request_id !== props.requestId || !Array.isArray(result.items)) throw new Error('审计回执不完整，请刷新。')
    return result
  } catch (e) {
    if (!disposed && current === generation) error.value = e?.response?.data?.message || '审计读取失败，请重试。'
    return { items: [], total: 0 }
  }
})
function clear() { disposed = true; generation++; controller?.abort(); list.value = []; total.value = 0 }
watch(() => [auth.accessToken, auth.user], () => { clear(); emit('close') }, { flush: 'sync' })
onBeforeUnmount(clear)
</script>

<template>
  <el-dialog :model-value="true" title="订单操作审计" width="760px" class="portal-audit-dialog" @update:model-value="value => { if (!value) emit('close') }">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <p class="object-reference">请求 {{ requestId }} · 时间均为北京时间</p>
    <el-table v-loading="loading" :data="list" border class="list-table" v-sticky-scrollbar><template #empty><el-empty :image-size="72" description="暂无订单审计记录" /></template>
      <el-table-column label="操作 / 时间" min-width="170"><template #default="{ row }"><strong>{{ actions[row.action] || row.action }}</strong><small>{{ formatBeijingDateTime(row.created_at) }}</small><small>{{ actors[row.actor_type] || '操作者' }} {{ row.actor_id ?? '—' }}</small></template></el-table-column>
      <el-table-column label="变化与原因" min-width="260"><template #default="{ row }"><p v-if="row.before_version != null || row.after_version != null">版本 {{ row.before_version ?? '—' }} → {{ row.after_version ?? '—' }}</p><p v-for="(value, key) in row.changes" :key="key">{{ fields[key] || key }}：{{ value }}</p><p>{{ row.reason || '未填写操作原因' }}</p></template></el-table-column>
      <el-table-column label="追踪编号" min-width="210"><template #default="{ row }"><code>{{ row.trace_id }}</code></template></el-table-column>
    </el-table>
    <el-pagination :current-page="page" :page-size="pageSize" :total="total" :disabled="loading" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    <template #footer><GlassButton @click="emit('close')">关闭</GlassButton><GlassButton :disabled="loading" @click="fetchList">刷新审计</GlassButton></template>
  </el-dialog>
</template>

<style scoped>
p { margin: 6px 0; overflow-wrap: anywhere; }
small { display: block; color: var(--text-secondary); margin-top: 6px; }
code { overflow-wrap: anywhere; }
.object-reference { margin-bottom: 16px; color: var(--text-secondary); }
.el-pagination { margin-top: 16px; overflow-x: auto; }
</style>
<style>
.portal-audit-dialog { max-width: calc(100vw - 24px); }
</style>
