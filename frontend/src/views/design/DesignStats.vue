<template>
  <div>
    <!-- Toolbar -->
    <el-row :gutter="12" class="toolbar" align="middle">
      <el-col :span="8">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          :clearable="false"
          style="width: 100%"
          @change="fetchStats"
        />
      </el-col>
      <el-col :span="3">
        <GlassButton :icon="Refresh" @click="fetchStats">刷新</GlassButton>
      </el-col>
    </el-row>

    <!-- Summary cards -->
    <el-row :gutter="16" class="summary-cards">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ summary.total }}</div>
          <div class="stat-label">总任务数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card card-success">
          <div class="stat-value">{{ summary.completed }}</div>
          <div class="stat-label">已完成</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card card-warning">
          <div class="stat-value">{{ summary.in_progress }}</div>
          <div class="stat-label">进行中</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card card-info">
          <div class="stat-value">{{ summary.scheduled }}</div>
          <div class="stat-label">待排期</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Designer workload table -->
    <div class="section-title">设计师工作量</div>
    <div class="table-card">
    <el-table
      :data="designerStats"
      v-loading="loading"
      class="list-table"
      border
    >
      <el-table-column prop="designer_name" label="设计师" min-width="120" max-width="180" show-overflow-tooltip />
      <el-table-column prop="total" label="总任务数" min-width="100" max-width="150" />
      <el-table-column prop="completed" label="已完成" min-width="100" max-width="150">
        <template #default="{ row }">
          <el-tag type="success" size="small" effect="plain">{{ row.completed }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="in_progress" label="进行中" min-width="100" max-width="150">
        <template #default="{ row }">
          <el-tag type="warning" size="small" effect="plain">{{ row.in_progress }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="avg_duration_days" label="平均任务时长(天)" min-width="160" max-width="240" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.avg_duration_days || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="完成率" min-width="160" max-width="240">
        <template #default="{ row }">
          <el-progress
            :percentage="row.total > 0 ? Math.round(row.completed / row.total * 100) : 0"
            :stroke-width="14"
            :text-inside="true"
          />
        </template>
      </el-table-column>
    </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getDesignStats } from '@/api/design'

function getDefaultDateRange() {
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth(), 1)
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0)
  return [formatDate(start), formatDate(end)]
}

function formatDate(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const dateRange = ref(getDefaultDateRange())
const loading = ref(false)
const summary = reactive({ total: 0, completed: 0, in_progress: 0, scheduled: 0 })
const designerStats = ref([])

async function fetchStats() {
  if (!dateRange.value || dateRange.value.length !== 2) return
  loading.value = true
  try {
    const res = await getDesignStats({
      start_date: dateRange.value[0],
      end_date: dateRange.value[1],
    })
    const data = res.data || {}
    Object.assign(summary, data.summary || {})
    designerStats.value = data.designer_stats || []
  } catch {
    // handled by interceptor
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchStats()
})
</script>

<style scoped>
.toolbar {
  margin-bottom: 20px;
}

.summary-cards {
  margin-bottom: 24px;
}

.stat-card {
  text-align: center;
  border-top: 3px solid var(--color-primary);
}

.stat-card.card-success {
  border-top-color: var(--color-success);
}

.stat-card.card-warning {
  border-top-color: var(--color-warning-text);
}

.stat-card.card-info {
  border-top-color: var(--text-muted);
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}
</style>
