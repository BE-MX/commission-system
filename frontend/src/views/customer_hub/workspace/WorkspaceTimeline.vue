<template><section class="timeline"><h3>客户往来时间线</h3><ListPageStatus :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" /><GlassButton variant="secondary" :loading="loading" @click="fetchList">刷新时间线</GlassButton><el-timeline v-loading="loading"><el-timeline-item v-for="event in list" :key="event.event_id" :timestamp="event.occurred_at ? formatBeijingDateTime(event.occurred_at) : '时间未提供'"><strong>{{ event.title || event.event_type }}</strong><p>{{ event.summary || '无补充摘要' }}</p></el-timeline-item></el-timeline><el-empty v-if="!loading && !error && !list.length" description="暂无可见时间线记录" :image-size="48" /><el-pagination class="pager" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" /></section></template>
<script setup>
import { watch } from 'vue'
import { listCustomerTimeline } from '@/api/customerHub'
import { useListPage } from '@/composables/useListPage'
import { formatBeijingDateTime } from '@/utils/datetime'
const props = defineProps({ customerId: { type: Number, required: true } })
const listPageState = useListPage(
  async ({ customer_id, ...params }, { signal }) => (await listCustomerTimeline(customer_id, params, { signal, suppressToast: true })).data,
  { searchForm: { customer_id: props.customerId } },
)
const { loading, list, total, page, pageSize, searchForm, error, errorMessage, hasData, hasLoaded, dataPage, fetchList, handleSearch, handlePageChange, handleSizeChange } = listPageState
watch(() => props.customerId, customerId => {
  list.value = []; total.value = 0; hasLoaded.value = false; dataPage.value = 1
  searchForm.customer_id = customerId
  handleSearch()
})
</script>
<style scoped>.timeline{padding:14px;border:1px solid var(--border-color);border-radius:var(--card-radius)}h3{font-size:14px;margin:0 0 12px}.el-timeline{padding-top:16px}.el-pagination{overflow-x:auto}p{color:var(--text-secondary);line-height:1.6}</style>
