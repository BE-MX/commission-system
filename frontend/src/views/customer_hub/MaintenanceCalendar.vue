<template>
  <main class="maintenance-calendar customer-hub">
    <header><h1>跟进日历</h1><p>按北京时间业务日展示维护实例；客户当地时间仅作提示，日程不代表自动发送。</p></header>
    <div class="lg-card toolbar">
      <el-select v-model="scope" size="small" style="width: 130px" @change="load">
        <el-option value="primary" label="我主负责" />
        <el-option value="collaborator" label="我协作" />
        <el-option value="authorized" label="授权可见" />
      </el-select>
      <el-date-picker v-model="range" type="daterange" size="small" value-format="YYYY-MM-DD" start-placeholder="开始" end-placeholder="结束" @change="load" />
      <GlassButton variant="secondary" left-icon="Refresh" @click="load">刷新</GlassButton>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <section v-for="group in groups" :key="group.date ?? 'unknown'" class="lg-card day-group">
      <h3>{{ group.date || '日期未知' }} <span class="hint">{{ group.items.length }} 项</span></h3>
      <el-table class="list-table" :data="group.items" size="small" border>
        <el-table-column prop="plan_type" label="类型" min-width="90" />
        <el-table-column prop="title" label="事项" min-width="150" show-overflow-tooltip />
        <el-table-column prop="customer_id" label="客户" min-width="110">
          <template #default="{ row }">
            <router-link :to="`/customer-hub/workspace/${row.customer_id}?tab=maintenance`">#{{ row.customer_id }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="local_date" label="当地日期" min-width="110" />
        <el-table-column prop="status" label="状态" min-width="100" />
      </el-table>
    </section>
    <el-empty v-if="!groups.length && !error" description="该区间没有维护实例" />
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getMaintenanceCalendar } from '@/api/customerHub'
import { groupCalendarByDate } from './customerWorkspaceController'

const scope = ref('primary')
const range = ref([])
const days = ref([])
const error = ref('')
const groups = computed(() => {
  const items = []
  for (const day of days.value) {
    for (const item of day.items || []) {
      items.push({ ...item, date: day.date })
    }
  }
  return groupCalendarByDate(items)
})

async function load() {
  error.value = ''
  try {
    const [from, to] = range.value || []
    const response = await getMaintenanceCalendar({
      customer_scope: scope.value,
      date_from: from || undefined,
      date_to: to || undefined,
    })
    days.value = response.data?.days ?? []
  } catch {
    error.value = '日历加载失败，请重试'
    days.value = []
  }
}

onMounted(load)
</script>

<style scoped>
.maintenance-calendar { display: grid; gap: 16px; color: var(--text-primary); }
.maintenance-calendar h1 { margin: 0 0 8px; font-size: 17px; }
.maintenance-calendar header p { margin: 0; color: var(--text-secondary); line-height: 1.6; }
.toolbar { display: flex; gap: 10px; align-items: center; padding: 12px 16px; flex-wrap: wrap; }
.day-group { padding: 14px 16px; }
.day-group h3 { margin: 0 0 10px; font-size: 14px; }
.hint { font-size: 12px; color: var(--text-muted); font-weight: normal; }
</style>
