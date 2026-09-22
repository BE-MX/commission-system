<template>
  <div>
    <el-alert v-if="error" type="error" :title="error" :closable="false" show-icon />
    <section class="table-card battle-panel">
      <div class="battle-section-title"><div><h3>每日成交矩阵</h3><span>每格显示 GMV（USD）与订单数；仅可下钻本人或授权组的订单。</span></div><div class="battle-actions"><GlassButton :disabled="!matrix || matrix.dates[0] <= report.start_date" @click="shift(-7)">上一周</GlassButton><span>{{ matrix?.dates[0] }} — {{ matrix?.dates.at(-1) }}</span><GlassButton :disabled="!matrix || matrix.dates.at(-1) >= report.end_date" @click="shift(7)">下一周</GlassButton></div></div>
      <el-table v-loading="matrixLoading" :data="matrix?.rows || []" border class="list-table">
        <el-table-column label="业务员" min-width="120" max-width="160"><template #default="{ row }"><el-button link type="primary" :disabled="!row.can_view_orders" @click="select(row.member_id, '')"><el-icon><ArrowRight /></el-icon>{{ row.user_name }}</el-button><p>{{ row.team }}</p></template></el-table-column>
        <el-table-column v-for="(day, index) in matrix?.dates || []" :key="day" :label="day.slice(5)" min-width="125" max-width="150"><template #default="{ row }"><button type="button" class="battle-cell" :class="{ selected: memberId === row.member_id && selectedDay === day }" :disabled="!row.can_view_orders || row.cells[index].state === 'future'" :aria-label="`${row.user_name} ${day} 订单`" @click="select(row.member_id, day)"><b>{{ row.cells[index].state === 'future' ? '—' : money(row.cells[index].gmv) }}</b><small>{{ row.cells[index].state === 'future' ? '未到' : row.cells[index].state === 'incomplete' ? '待核对' : `${row.cells[index].order_count} 单` }}</small></button></template></el-table-column>
        <el-table-column label="本页小计 / USD" min-width="155" max-width="190"><template #default="{ row }">{{ money(row.subtotal) }}</template></el-table-column>
      </el-table>
    </section>
    <section class="table-card battle-panel">
      <div class="battle-section-title"><h3>订单复盘</h3><span v-if="!report.can_admin">明细只包含本人或组长授权范围</span></div>
      <div class="battle-actions">
        <el-date-picker v-model="selectedDay" type="date" value-format="YYYY-MM-DD" placeholder="整个周期" aria-label="复盘日期" :disabled-date="disabledDay" @change="searchOrders" />
        <el-select v-model="memberId" clearable placeholder="全部可查看业务员" aria-label="复盘业务员" @change="searchOrders"><el-option v-for="m in detailMembers" :key="m.id" :label="m.user_name" :value="m.id" /></el-select>
        <el-input v-model="searchForm.keyword" clearable placeholder="订单号 / 客户" aria-label="搜索订单" @keyup.enter="searchOrders" @clear="searchOrders" />
        <el-select v-model="searchForm.sort" aria-label="订单排序" @change="searchOrders"><el-option label="按核算日期" value="date" /><el-option label="按订单金额" value="amount" /></el-select>
        <GlassButton left-icon="Search" @click="searchOrders">查询</GlassButton>
      </div>
      <el-alert v-if="orderError" type="error" :title="orderError" :closable="false" />
      <div class="battle-order-summary"><b>所选范围 GMV：${{ money(orderMeta.gmv) }}</b><span>{{ total }} 单 · 完整筛选合计，不受分页影响</span></div>
      <el-alert v-if="orderMeta.issues?.length" type="warning" :closable="false" :title="`${orderMeta.issues.length} 条异常记录未计入`"><template #default><p v-for="(issue, index) in orderMeta.issues" :key="index">{{ issue.order_no || '无订单号' }}：{{ issue.reason }}</p></template></el-alert>
      <el-table v-loading="loading" :data="list" border class="list-table">
        <template #empty>{{ detailMembers.length ? '当前筛选范围暂无订单' : '当前组没有可查看的订单明细' }}</template>
        <el-table-column label="订单号" min-width="170" max-width="220"><template #default="{ row }"><el-button link type="primary" @click="openOrder(row)"><el-icon><View /></el-icon>{{ row.order_no }}</el-button></template></el-table-column>
        <el-table-column prop="account_date" label="核算日" min-width="120" max-width="160" />
        <el-table-column prop="user_name" label="业务员" min-width="110" max-width="150" show-overflow-tooltip />
        <el-table-column prop="team" label="业务组" min-width="110" max-width="160" show-overflow-tooltip />
        <el-table-column prop="company_name" label="客户" min-width="180" max-width="260" show-overflow-tooltip />
        <el-table-column prop="status_name" label="状态" min-width="110" max-width="150" show-overflow-tooltip />
        <el-table-column label="订单金额 / USD" min-width="160" max-width="200"><template #default="{ row }">{{ money(row.amount_usd) }}</template></el-table-column>
        <el-table-column label="计入 GMV / USD" min-width="170" max-width="210"><template #default="{ row }">{{ money(row.included_usd) }}</template></el-table-column>
      </el-table>
      <el-pagination :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="changePage" @size-change="changeSize" />
    </section>
    <DetailDrawer v-model="drawer" title="战报订单明细" :loading="detailLoading">
      <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <el-descriptions v-if="order" :column="1" border><el-descriptions-item label="订单号">{{ order.order_no }}</el-descriptions-item><el-descriptions-item label="客户">{{ order.company_name }}</el-descriptions-item><el-descriptions-item label="业务员 / 组">{{ order.user_name }} / {{ order.team }}</el-descriptions-item><el-descriptions-item label="核算日期">{{ order.account_date }}</el-descriptions-item><el-descriptions-item label="订单金额">USD {{ money(order.amount_usd) }}</el-descriptions-item><el-descriptions-item label="计入本战报">USD {{ money(order.included_usd) }} · {{ order.included_percent }}%</el-descriptions-item><el-descriptions-item label="计入原因">{{ order.reason }}</el-descriptions-item></el-descriptions>
    </DetailDrawer>
  </div>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowRight, View } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { useListPage } from '@/composables/useListPage'
import { battleReportApi } from '@/api/battleReport'
import { currentBeijingDate, formatCalendarDate } from '@/utils/datetime'
import { addDays, errorText, money } from '../helpers'
const props = defineProps({ report: { type: Object, required: true }, team: { type: String, default: '' }, selection: { type: Object, default: () => ({}) } })
const matrix = ref(null), matrixLoading = ref(false), error = ref(''), start = ref('')
const memberId = ref(props.selection.memberId || ''), selectedDay = ref(props.selection.day || '')
const orderMeta = ref({ gmv: '0', issues: [] }), orderError = ref('')
const drawer = ref(false), order = ref(null), detailLoading = ref(false), detailError = ref('')
let matrixRequest = 0, orderRequest = 0, detailRequest = 0, orderUiRequest = 0
const detailMembers = computed(() => props.report.members.filter(m => props.report.detail_member_ids.includes(m.id) && (!props.team || m.team === props.team)))
const { list, total, page, pageSize, searchForm, loading, handleSearch, handlePageChange, handleSizeChange } = useListPage(async params => {
  const token = ++orderRequest
  if (!detailMembers.value.length) { orderMeta.value = { gmv: '0', issues: [] }; return { items: [], total: 0 } }
  const result = await battleReportApi.orders(props.report.id, { ...params, team: props.team || undefined, member_id: memberId.value || undefined, day: selectedDay.value || undefined })
  if (token === orderRequest) { orderMeta.value = result; orderError.value = '' }
  return result
}, { immediate: false, searchForm: { keyword: '', sort: 'date' } })
async function loadMatrix() {
  const token = ++matrixRequest; matrixLoading.value = true
  try { const data = await battleReportApi.daily(props.report.id, { team: props.team || undefined, start: start.value || undefined }); if (token === matrixRequest) { matrix.value = data; error.value = '' } }
  catch (e) { if (token === matrixRequest) error.value = errorText(e) }
  finally { if (token === matrixRequest) matrixLoading.value = false }
}
async function runOrders(fn) { const token = ++orderUiRequest; try { await fn() } catch (e) { if (token === orderUiRequest) orderError.value = errorText(e) } }
function searchOrders() { orderRequest++; list.value = []; total.value = 0; orderMeta.value = { gmv: null, issues: [] }; return runOrders(handleSearch) }
function changePage(value) { return runOrders(() => handlePageChange(value)) }
function changeSize(value) { return runOrders(() => handleSizeChange(value)) }
function select(id, day) { memberId.value = id; selectedDay.value = day; searchOrders() }
function shift(count) { start.value = [props.report.start_date, addDays(matrix.value.dates[0], count)].sort().at(-1); loadMatrix() }
function disabledDay(value) { const day = formatCalendarDate(value); return day < props.report.start_date || day > props.report.end_date || day > currentBeijingDate() }
async function openOrder(row) {
  const token = ++detailRequest; order.value = null; detailError.value = ''; drawer.value = true; detailLoading.value = true
  try { const result = await battleReportApi.order(props.report.id, row.order_id); if (token === detailRequest) order.value = result }
  catch (e) { if (token === detailRequest) detailError.value = errorText(e) }
  finally { if (token === detailRequest) detailLoading.value = false }
}
watch(() => props.selection, value => { memberId.value = value.memberId || ''; selectedDay.value = value.day || ''; searchOrders() })
onMounted(() => { loadMatrix(); searchOrders() })
onUnmounted(() => { matrixRequest++; orderRequest++; detailRequest++; orderUiRequest++ })
</script>
