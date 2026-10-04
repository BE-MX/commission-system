<template>
  <section class="table-card">
    <h3>回信、退信与退订</h3>
    <FilterBar :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="handleReset">
      <el-select v-model="searchForm.classification" clearable placeholder="全部分类" class="filter-w-md"><el-option v-for="(label, value) in EVENT_CLASSIFICATION_LABELS" :key="value" :value="value" :label="label" /></el-select>
    </FilterBar>
    <div class="action-bar"><TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columns" :fullscreen="isFullscreen" @refresh="fetchList" @fullscreen="toggleFullscreen" /></div>
    <ListPageStatus v-if="hasData" :error="errorMessage" :loading="loading" :has-data="hasData" @retry="fetchList" />
    <div ref="panelRef">
      <el-table :data="list" v-loading="loading" border class="list-table" :class="densityClass" row-key="id" @sort-change="mailEventsState.handleSortChange($event.order ? { sort_field: $event.prop, sort_order: $event.order === 'ascending' ? 'asc' : 'desc' } : {})">
        <el-table-column sortable="custom" v-if="visibleKeys.includes('from')" prop="from_address" label="发件人" min-width="180" show-overflow-tooltip />
        <el-table-column sortable="custom" v-if="visibleKeys.includes('subject')" prop="subject" label="主题" min-width="220" show-overflow-tooltip />
        <el-table-column sortable="custom" prop="classification" v-if="visibleKeys.includes('classification')" label="分类" min-width="100"><template #default="{ row }">{{ EVENT_CLASSIFICATION_LABELS[row.classification] || row.classification || '待分类' }}</template></el-table-column>
        <el-table-column sortable="custom" prop="matched_customer_id" v-if="visibleKeys.includes('customer')" label="客户 / 任务" min-width="140"><template #default="{ row }">{{ row.matched_customer_id ? `客户 #${row.matched_customer_id}` : '未匹配客户' }} / {{ row.matched_job_id || '-' }}</template></el-table-column>
        <el-table-column sortable="custom" prop="received_at_utc" v-if="visibleKeys.includes('received')" label="收到时间（北京时间）" min-width="170"><template #default="{ row }">{{ formatBeijingDateTime(row.received_at_utc, { naiveTimeZone: 'UTC' }) }}</template></el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('processed')" prop="processed_status" label="处理状态" min-width="120" />
        <el-table-column label="操作" min-width="120" class-name="table-action-column"><template #default="{ row }"><GlassButton v-any-permission="['mail_outreach:write','mail_outreach:admin']" variant="link" left-icon="Edit" @click="open(row)">修正分类</GlassButton></template></el-table-column>
        <template #empty><ListPageStatus :error="errorMessage" :loading="loading" :has-data="false" @retry="fetchList">暂无可见收信事件。需执行器监听收到并关联客户后才会显示。</ListPageStatus></template>
      </el-table>
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </div>
    <el-dialog v-model="visible" title="修正收信分类" width="480px" :close-on-click-modal="!saving" :show-close="!saving" :close-on-press-escape="!saving">
      <p>{{ selected?.subject || '无主题' }}</p>
      <el-form label-position="top" :disabled="saving">
        <el-form-item label="分类"><el-select v-model="form.classification"><el-option v-for="(label, value) in EVENT_CLASSIFICATION_LABELS" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item label="修正依据"><el-input v-model="form.reason" type="textarea" :rows="3" maxlength="500" /></el-form-item>
        <el-alert v-if="['bounce','opt_out'].includes(form.classification)" type="warning" title="退信或退订会阻止后续触达，请依据实际邮件确认。" :closable="false" />
        <el-alert v-if="saveError" type="error" title="分类保存失败，请核对权限与事件状态后重试。" :closable="false" />
      </el-form>
      <template #footer><GlassButton variant="ghost" :disabled="saving" @click="visible = false">取消</GlassButton><GlassButton variant="primary" left-icon="Check" :disabled="!form.reason.trim() || !form.classification || saving" :loading="saving" @click="save">确认分类</GlassButton></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { reactive, ref } from 'vue'
import { listMailEvents, classifyMailEvent } from '@/api/mailOutreach'
import { useListPage } from '@/composables/useListPage'
import { useTableView } from '@/composables/useTableView'
import { formatBeijingDateTime } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import GlassButton from '@/components/GlassButton.vue'
import TableTools from '@/components/TableTools.vue'
import { EVENT_CLASSIFICATION_LABELS } from './presentation'
const mailEventsState = useListPage(async (params, { signal }) => (await listMailEvents(Object.fromEntries(Object.entries(params).filter(([, value]) => value !== '')), { signal, suppressToast: true })).data, { searchForm: { classification: '' } })
const { list, loading, total, page, pageSize, searchForm, hasPendingSearch, hasData, errorMessage, fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange, refreshUpdate } = mailEventsState

const columns = [{ key: 'from', label: '发件人' }, { key: 'subject', label: '主题' }, { key: 'classification', label: '分类' }, { key: 'customer', label: '客户 / 任务' }, { key: 'received', label: '收到时间' }, { key: 'processed', label: '处理状态' }]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('mail-inbound-events', columns)
const visible = ref(false), saving = ref(false), saveError = ref(null), selected = ref(null)
const form = reactive({ classification: 'other', reason: '' })
function open(row) { selected.value = row; form.classification = EVENT_CLASSIFICATION_LABELS[row.classification] ? row.classification : 'other'; form.reason = ''; saveError.value = null; visible.value = true }
async function save() {
  if (!selected.value || !form.reason.trim() || saving.value) return
  saving.value = true; saveError.value = null
  try { await classifyMailEvent(selected.value.id, { ...form, reason: form.reason.trim() }); msgSuccess('分类已保存'); visible.value = false; await refreshUpdate() }
  catch (cause) { saveError.value = cause } finally { saving.value = false }
}
</script>
<style scoped>
h3 { margin: 0 0 12px; font-size: 15px; }
</style>
