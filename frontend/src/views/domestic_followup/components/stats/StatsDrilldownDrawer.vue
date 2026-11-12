<template>
  <DetailDrawer :model-value="visible" :title="title" width="680px" @update:model-value="value => { visible = value }">
    <el-alert v-if="error" class="stats-error" type="error" :title="error" :closable="false" show-icon />
    <div v-loading="loading" class="stats-drill-list">
      <template v-for="row in items" :key="row.id || row.customer_id">
        <article v-if="kind === 'records'" class="stats-drill-item">
          <div class="stats-drill-item__head"><strong>{{ row.shop_name }}</strong><StatusBadge>{{ row.result_code || '未填结果' }}</StatusBadge><span class="stats-spacer" /><span>{{ row.followup_date }} · {{ row.author_name }}</span></div>
          <p>{{ row.summary || row.raw_text }}</p>
          <div><GlassButton variant="link" @click="$emit('record', row)">记录详情</GlassButton><GlassButton variant="link" @click="$emit('timeline', row.customer_id)">客户时间线</GlassButton><GlassButton v-permission="'domestic_followup:write'" variant="link" @click="$emit('write', row)">记跟进</GlassButton></div>
        </article>
        <article v-else-if="kind === 'plans'" class="stats-drill-item">
          <div class="stats-drill-item__head"><strong>{{ row.title }}</strong><StatusBadge :type="row.on_time ? 'success' : 'info'">{{ row.on_time ? '按时兑现' : '未按时兑现' }}</StatusBadge></div>
          <p>到期 {{ row.due_date }} · 顺延 {{ row.snooze_count }} 次 · {{ { todo: '待完成', done: '已完成', expired: '已过期', cancelled: '已取消' }[row.status] }}</p>
          <GlassButton variant="link" @click="$emit('timeline', row.customer_id)">客户时间线</GlassButton>
        </article>
        <article v-else class="stats-drill-item">
          <div class="stats-drill-item__head"><strong>{{ row.shop_name }}</strong><StatusBadge v-if="row.level">{{ row.level }}</StatusBadge><StatusBadge v-if="row.overdue_days" type="warning">超期 {{ row.overdue_days }} 天</StatusBadge><span class="stats-spacer" /><span v-if="row.owner_name" class="stats-hint">{{ row.owner_name }}</span></div>
          <p v-if="row.last_followup_date">上次跟进：{{ row.last_followup_date }}</p><p v-else-if="kind === 'overdue'">从未跟进，从接手日或建档日起算</p>
          <GlassButton variant="link" @click="$emit('timeline', row.customer_id)">客户时间线</GlassButton><GlassButton v-permission="'domestic_followup:write'" variant="link" @click="$emit('write', row)">记跟进</GlassButton>
        </article>
      </template>
      <el-empty v-if="!loading && !items.length" description="当前条件下没有数据" :image-size="72" />
    </div>
    <el-pagination v-if="total > pageSize" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="load(1)" />
  </DetailDrawer>
</template>
<script setup>
import StatusBadge from '@/components/StatusBadge.vue'
import { ref } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import { followupApi } from '@/api/domesticFollowup'
import { errorMessage } from '@/utils/errors'

const emit = defineEmits(['record', 'timeline', 'write'])
const visible = ref(false), loading = ref(false), error = ref(''), title = ref('统计明细')
const items = ref([]), kind = ref('records'), total = ref(0), page = ref(1), pageSize = ref(20)
let params = {}, run = 0
async function load(pageNumber = 1) {
  const current = ++run
  loading.value = true
  error.value = ''
  try {
    const data = await followupApi.statsDrilldown({ ...params, page: pageNumber, page_size: pageSize.value })
    if (current !== run) return
    items.value = data.items
    total.value = data.total
    page.value = pageNumber
  } catch (failure) { if (current === run) error.value = errorMessage(failure, '统计明细加载失败') }
  finally { if (current === run) loading.value = false }
}
function open(nextParams, nextTitle = '统计明细') {
  run += 1
  params = { ...nextParams }
  kind.value = nextParams.kind || 'records'
  title.value = nextTitle
  items.value = []
  total.value = 0
  visible.value = true
  load(1)
}
defineExpose({ open })
</script>
