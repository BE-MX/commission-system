<template>
  <div ref="panelRef" class="table-card followup-overview">
    <FilterBar label="跟进记录筛选" :loading="list.loading.value" :pending="list.hasPendingSearch.value"
               @search="list.handleSearch" @reset="list.handleReset()">
      <el-input v-model="list.searchForm.keyword" aria-label="客户或跟进内容" placeholder="客户 / 编码 / 联系人 / 跟进内容"
                clearable maxlength="100" prefix-icon="Search" class="filter-w-lg" />
      <el-select v-model="list.searchForm.author_user_id" aria-label="录入人" placeholder="全部录入人" filterable clearable
                 :loading="authorsLoading" class="filter-w-sm">
        <el-option v-for="author in authors" :key="author.id" :value="author.id" :label="author.real_name" />
      </el-select>
      <el-date-picker v-model="list.searchForm.date_from" aria-label="跟进开始日期" placeholder="跟进开始日期"
                      type="date" value-format="YYYY-MM-DD" class="filter-w-sm" />
      <el-date-picker v-model="list.searchForm.date_to" aria-label="跟进结束日期" placeholder="跟进结束日期"
                      type="date" value-format="YYYY-MM-DD" class="filter-w-sm" />
    </FilterBar>
    <div v-if="authorsError" class="authors-error" role="status">
      {{ authorsError }}<GlassButton variant="link" @click="loadAuthors">重试录入人选项</GlassButton>
    </div>
    <div class="action-bar">
      <TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columns"
                  :loading="list.loading.value" :fullscreen="isFullscreen" @refresh="refresh"
                  @fullscreen="toggleFullscreen" />
    </div>
    <ListPageStatus v-if="list.hasData.value" :error="list.errorMessage.value" :loading="list.loading.value"
                    :has-data="true" :data-page="list.dataPage.value" @retry="list.fetchList()" />
    <el-table :data="list.list.value" v-loading="list.loading.value" row-key="id" border
              class="list-table" :class="densityClass" v-sticky-scrollbar>
      <template #empty>
        <ListPageStatus :error="list.errorMessage.value" :loading="list.loading.value" :has-data="false" @retry="list.fetchList()">
          <el-empty :image-size="96" description="当前范围内暂无符合条件的跟进记录" />
        </ListPageStatus>
      </template>
      <el-table-column v-if="visibleKeys.includes('followup_date')" label="跟进日期" prop="followup_date" min-width="115" />
      <el-table-column v-if="visibleKeys.includes('author_name')" label="录入人" prop="author_name" min-width="100" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('shop_name')" label="客户" min-width="160" show-overflow-tooltip>
        <template #default="{ row }"><GlassButton variant="link" @click="$emit('timeline', row.customer_id)">{{ row.shop_name }}</GlassButton></template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('channel')" label="沟通方式" prop="channel" min-width="100" />
      <el-table-column v-if="visibleKeys.includes('summary')" label="跟进内容" min-width="260" show-overflow-tooltip>
        <template #default="{ row }">{{ row.summary || row.raw_text || row.items?.[0]?.text || '—' }}</template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('next_date')" label="下次跟进" prop="next_date" min-width="115" />
      <el-table-column label="操作" class-name="table-action-column" min-width="100" fixed="right">
        <template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="selected = row">详情</GlassButton></template>
      </el-table-column>
    </el-table>
    <el-pagination :current-page="list.page.value" :page-size="list.pageSize.value" :total="list.total.value"
                   :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager"
                   @current-change="list.handlePageChange" @size-change="list.handleSizeChange" />
    <FollowupRecordDrawer :record="selected" @close="selected = null" @timeline="openTimeline"
                          @edit="id => recordAction('edit', id)" @history="id => recordAction('history', id)" />
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import FilterBar from '@/components/FilterBar.vue'
import GlassButton from '@/components/GlassButton.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { useFollowupOverview } from '../composables/useFollowupOverview'
import FollowupRecordDrawer from './FollowupRecordDrawer.vue'

const props = defineProps({ potentialOnly: Boolean })
const emit = defineEmits(['timeline', 'edit', 'history'])
const columns = [
  { key: 'followup_date', label: '跟进日期' }, { key: 'author_name', label: '录入人' },
  { key: 'shop_name', label: '客户' }, { key: 'channel', label: '沟通方式' },
  { key: 'summary', label: '跟进内容' }, { key: 'next_date', label: '下次跟进' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('domestic-followup-overview', columns)
const list = useFollowupOverview(followupApi, () => props.potentialOnly)
const selected = ref(null)
const authors = ref([])
const authorsLoading = ref(false)
const authorsError = ref('')
let authorRequest = 0

async function loadAuthors() {
  const run = ++authorRequest
  authorsLoading.value = true
  authorsError.value = ''
  try {
    const data = await followupApi.followupAuthors({ potential_only: props.potentialOnly })
    if (run === authorRequest) authors.value = data
  } catch (error) { if (run === authorRequest) authorsError.value = apiError(error, '录入人选项加载失败') }
  finally { if (run === authorRequest) authorsLoading.value = false }
}

function refresh() {
  selected.value = null
  return Promise.all([list.fetchList(), loadAuthors()])
}

function openTimeline(id) {
  selected.value = null
  emit('timeline', id)
}

function recordAction(action, id) {
  selected.value = null
  emit(action, id)
}

watch(() => props.potentialOnly, () => {
  list.cancel()
  list.list.value = []; list.total.value = 0; list.hasLoaded.value = false
  selected.value = null
  authors.value = []
  list.handlePageChange(1)
  loadAuthors()
}, { flush: 'sync' })
onUnmounted(() => { authorRequest++ })

defineExpose({ refresh })
onMounted(refresh)
</script>

<style scoped>
.followup-overview { min-width: 0; }
.authors-error { padding: 0 16px; color: var(--text-secondary); font-size: 12px; }
</style>
