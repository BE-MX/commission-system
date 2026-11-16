<template>
  <section class="table-card">
    <div class="toolbar">
      <el-date-picker v-model="range" type="daterange" value-format="YYYY-MM-DD"
        start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至"
        :clearable="false" aria-label="账单日期（北京时间）" />
      <el-radio-group v-model="group" aria-label="花费统计维度">
        <el-radio-button value="by_day">按日</el-radio-button>
        <el-radio-button value="by_customer">按客户</el-radio-button>
      </el-radio-group>
      <GlassButton variant="primary" left-icon="Search" :disabled="loading" @click="handleSearch">查询</GlassButton>
    </div>
    <ListPageStatus :error="errorMessage" :loading="loading" :has-data="list.length > 0" @retry="load()" />
    <el-table v-loading="loading" :data="list" border class="list-table" max-height="640" v-sticky-scrollbar>
      <template #empty><el-empty v-if="!loading && !errorMessage" :image-size="80" description="此日期范围内没有 Monid 调用" /></template>
      <el-table-column v-if="group === 'by_day'" prop="day" label="日期（北京时间）" min-width="160" />
      <el-table-column v-else label="客户" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ row.customer_name || '客户' }} · #{{ row.customer_id }}</template>
      </el-table-column>
      <el-table-column prop="calls" label="调用次数" min-width="110" align="right" />
      <el-table-column prop="charged_usd" label="已结算（USD）" min-width="150" align="right" />
      <el-table-column prop="reserved_usd" label="待结算占用（USD）" min-width="160" align="right" />
    </el-table>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getMonidSpend } from '@/api/salesAutomation'
import GlassButton from '@/components/GlassButton.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { beijingStartOfToday, formatBeijingDate } from '@/utils/datetime'

const today = beijingStartOfToday().getTime()
const range = ref([formatBeijingDate(new Date(today - 29 * 86400000)), formatBeijingDate(new Date(today))])
const group = ref('by_day')
const { data, loading, errorMessage, load } = useAsyncResource(async ([date_from, date_to], { signal }) =>
  (await getMonidSpend({ date_from, date_to }, signal)).data,
)
const list = computed(() => data.value?.[group.value] || [])
const handleSearch = () => load(range.value)
onMounted(handleSearch)
</script>
