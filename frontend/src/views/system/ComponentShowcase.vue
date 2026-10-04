<template>
  <main class="showcase">
    <header class="showcase-heading">
      <div><h1>组件与交互样例</h1><p>用本地示例数据检查查询、失败恢复、详情与表格偏好。</p></div>
      <el-select v-model="scenario" aria-label="演示场景" class="filter-w-md" @change="changeScenario">
        <el-option v-for="option in scenarios" :key="option.value" :label="option.label" :value="option.value" />
      </el-select>
    </header>
    <section class="showcase-states" aria-label="组件状态">
      <StatusBadge v-for="state in Object.keys(states)" :key="state" :value="state" :dictionary="states" />
      <StatusBadge value="future_state" :dictionary="states" />
      <GlassButton disabled>暂不可用</GlassButton>
      <GlassButton :loading="saving">提交状态</GlassButton>
      <el-input model-value="只读内容，可复制" readonly aria-label="只读输入" />
    </section>
    <section ref="panelRef" class="table-card">
      <div class="showcase-toolbar">
        <h2>示例记录 <span>{{ total }}</span></h2>
        <TableTools :columns="columns" v-model:visible-keys="visibleKeys" v-model:density="density" :fullscreen="isFullscreen" :loading="loading" @refresh="fetchList" @fullscreen="toggleFullscreen" />
        <GlassButton variant="primary" @click="openCreate">新增记录</GlassButton>
      </div>
      <FilterBar :loading="loading" :pending="hasPendingSearch" :advanced-count="advancedCount" @search="handleSearch" @reset="handleReset">
        <el-input v-model="searchForm.keyword" clearable placeholder="名称关键字" aria-label="名称关键字" class="filter-w-md" />
        <el-select v-model="searchForm.status" clearable placeholder="状态" aria-label="状态" class="filter-w-sm">
          <el-option v-for="(state, value) in states" :key="value" :label="state.label" :value="value" />
        </el-select>
        <el-select v-model="searchForm.owner" clearable placeholder="负责人" aria-label="负责人" class="filter-w-sm"><el-option label="张楠" value="张楠" /><el-option label="李晓" value="李晓" /></el-select>
        <el-input v-model="searchForm.reference" clearable placeholder="记录编号" aria-label="记录编号" class="filter-w-md" />
        <template #advanced>
          <el-date-picker v-model="searchForm.dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" class="filter-w-lg" />
          <el-input v-model="searchForm.note" clearable placeholder="备注关键字" aria-label="备注关键字" class="filter-w-md" />
        </template>
      </FilterBar>
      <ListPageStatus v-if="hasData && errorMessage" :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
      <el-table class="list-table" border v-loading="loading" :data="list" :class="densityClass" @row-dblclick="openDetail">
        <el-table-column v-if="visibleKeys.includes('name')" prop="name" label="名称" min-width="220" />
        <el-table-column v-if="visibleKeys.includes('owner')" prop="owner" label="负责人" min-width="110" />
        <el-table-column prop="amount" v-if="visibleKeys.includes('amount')" label="金额" min-width="130"><template #default="{ row }">{{ formatMoney(row.amount, { currency: 'CNY', currencyDisplay: 'narrowSymbol' }) }}</template></el-table-column>
        <el-table-column prop="status" v-if="visibleKeys.includes('status')" label="状态" min-width="130"><template #default="{ row }"><StatusBadge :value="row.status" :dictionary="states" /></template></el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="145" fixed="right"><template #default="{ row }"><GlassButton left-icon="Document" variant="link" @click="openDetail(row)">详情</GlassButton><GlassButton left-icon="Delete" variant="link" link-tone="danger" @click="remove(row)">删除</GlassButton></template></el-table-column>
        <template #empty><ListPageStatus :error="errorMessage" :loading="loading" @retry="fetchList"><EmptyState description="没有符合条件的示例记录" action-label="清空筛选" @action="handleReset" /></ListPageStatus></template>
      </el-table>
      <el-pagination class="pager" v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </section>
    <DetailDrawer v-model="detailOpen" title="示例详情" :width="640">
      <ResponsiveDescriptions v-if="selected" :column="3" border>
        <el-descriptions-item label="编号">{{ selected.reference }}</el-descriptions-item>
        <el-descriptions-item label="负责人">{{ selected.owner }}</el-descriptions-item>
        <el-descriptions-item label="状态"><StatusBadge :value="selected.status" :dictionary="states" /></el-descriptions-item>
        <el-descriptions-item label="名称">{{ selected.name }}</el-descriptions-item>
        <el-descriptions-item label="备注">{{ selected.note }}</el-descriptions-item>
      </ResponsiveDescriptions>
      <template #footer><GlassButton @click="detailOpen = false">关闭</GlassButton></template>
    </DetailDrawer>
    <el-dialog v-model="createOpen" title="新增示例记录" width="480px" @closed="name = ''">
      <el-form label-position="top" @submit.prevent="save">
        <el-form-item label="名称"><el-input v-model="name" maxlength="120" aria-label="新增记录名称" /></el-form-item>
        <p class="showcase-help">此操作只修改当前页面的本地数据，刷新页面后恢复。</p>
      </el-form>
      <template #footer><GlassButton :disabled="saving" @click="createOpen = false">取消</GlassButton><GlassButton variant="primary" :loading="saving" :disabled="!name.trim()" @click="save">保存</GlassButton></template>
    </el-dialog>
  </main>
</template>

<script setup>
import { computed, ref } from 'vue'
import FilterBar from '../../components/FilterBar.vue'
import ListPageStatus from '../../components/ListPageStatus.vue'
import TableTools from '../../components/TableTools.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import EmptyState from '../../components/EmptyState.vue'
import DetailDrawer from '../../components/DetailDrawer.vue'
import ResponsiveDescriptions from '../../components/ResponsiveDescriptions.vue'
import { useListPage } from '../../composables/useListPage.js'
import { clearListResource } from '../../composables/useListResourceScope.js'
import { useTableView } from '../../composables/useTableView.js'
import { formatMoney } from '../../utils/money.js'
import { statusDictionary } from '../../utils/status.js'
import { confirmDanger, msgSuccess } from '../../utils/feedback.js'

const states = statusDictionary([['draft', '草稿', 'info'], ['active', '处理中', 'warning'], ['done', '已完成', 'success'], ['rejected', '未通过', 'danger']])
const scenarios = [
  { value: 'ready', label: '正常数据' }, { value: 'slow', label: '慢速加载' },
  { value: 'empty', label: '空列表' }, { value: 'first-error', label: '首次加载失败' },
  { value: 'refresh-error', label: '刷新失败，保留旧数据' },
]
const scenario = ref('ready')
let failNext = false
let records = Array.from({ length: 57 }, (_, index) => ({
  id: index + 1, reference: 'EX-' + String(index + 1).padStart(3, '0'),
  name: index === 0 ? '超长名称示例：用于检查表格、详情与窄屏下的内容换行，确保所有文字都能阅读' : '示例记录 ' + (index + 1),
  owner: index % 2 ? '张楠' : '李晓', status: Object.keys(states)[index % 4],
  amount: index === 1 ? -1234.56 : 1250.5 + index, date: '2026-10-01',
  note: '这是一段超长说明。'.repeat(index === 0 ? 35 : 2),
}))
async function load(params, { signal }) {
  await new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, scenario.value === 'slow' ? 1600 : 220)
    signal.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }, { once: true })
  })
  if (failNext) { failNext = false; throw new Error('示例请求失败，可点击重试恢复。') }
  let filtered = scenario.value === 'empty' ? [] : records.filter(row =>
    row.name.includes(params.keyword) && row.reference.includes(params.reference) &&
    (!params.status || row.status === params.status) && (!params.owner || row.owner === params.owner) &&
    row.note.includes(params.note) && (!params.dateRange?.length || (row.date >= params.dateRange[0] && row.date <= params.dateRange[1])))
  return { items: filtered.slice((params.page - 1) * params.page_size, params.page * params.page_size), total: filtered.length }
}
const listState = useListPage(load, { searchForm: { keyword: '', reference: '', status: '', owner: '', note: '', dateRange: [] } })
const { list, total, page, pageSize, loading, hasData, dataPage, errorMessage, hasPendingSearch, searchForm, fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange, refreshCreate, refreshRemove } = listState
const columns = [{ key: 'name', label: '名称' }, { key: 'owner', label: '负责人' }, { key: 'amount', label: '金额' }, { key: 'status', label: '状态' }]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('component-showcase', columns)
const advancedCount = computed(() => Number(!!searchForm.note) + Number(!!searchForm.dateRange?.length))
async function changeScenario() {
  if (scenario.value === 'first-error') { clearListResource(listState); failNext = true }
  if (scenario.value === 'refresh-error') {
    if (!hasData.value) { scenario.value = 'ready'; await fetchList(); scenario.value = 'refresh-error' }
    failNext = true
  }
  await fetchList()
}
const detailOpen = ref(false)
const selected = ref(null)
function openDetail(row) { selected.value = row; detailOpen.value = true }
const createOpen = ref(false)
const name = ref('')
const saving = ref(false)
function openCreate() { name.value = ''; createOpen.value = true }
async function save() {
  if (saving.value || !name.value.trim()) return
  saving.value = true
  try {
    await new Promise(resolve => setTimeout(resolve, 350))
    const id = Math.max(0, ...records.map(row => row.id)) + 1
    records.unshift({ id, reference: 'EX-' + id, name: name.value.trim(), owner: '张楠', status: 'draft', amount: 1250, date: '2026-10-01', note: '新增示例' })
    createOpen.value = false
    msgSuccess('保存')
    await refreshCreate()
  } finally { saving.value = false }
}
async function remove(row) {
  try { await confirmDanger('删除示例记录「' + row.name + '」') } catch { return }
  records = records.filter(item => item.id !== row.id)
  msgSuccess('删除')
  await refreshRemove()
}
</script>

<style scoped>
.showcase { max-width: 1280px; margin: 0 auto; padding: 24px; }
.showcase-heading, .showcase-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.showcase-heading { justify-content: space-between; margin-bottom: 20px; }
.showcase-heading .el-select { width: 200px; }
.showcase-heading h1 { font-size: 24px; margin: 0 0 8px; }
.showcase-heading p, .showcase-help { color: var(--text-secondary); margin: 0; line-height: 1.6; }
.showcase-states { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 20px; }
.showcase-states .el-input { max-width: 220px; }
.showcase-toolbar { padding: 16px; }
.showcase-toolbar h2 { font-size: 17px; margin: 0 auto 0 0; }
.showcase-toolbar h2 span { color: var(--text-secondary); font-size: 13px; }
.showcase .filter-bar { margin: 0 16px 16px; }
.showcase .pager { padding: 16px; }
@media (max-width: 600px) {
  .showcase { padding: 12px; }
  .showcase-heading .el-select { width: 100%; }
  .showcase-toolbar { gap: 8px; }
}
</style>

