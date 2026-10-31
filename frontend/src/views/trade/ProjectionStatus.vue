<template>
  <div>
    <div class="page-header">
      <h2>本地经营投影</h2>
      <p>仅反映方舟本地交易，显示后端读取时的处理水位。由后台任务推进，刷新查看最新结果。</p>
    </div>
    <div class="table-card">
      <div class="action-bar">
        <GlassButton left-icon="Refresh" :loading="resource.loading.value" @click="resource.load()">
          刷新状态
        </GlassButton>
      </div>
      <ListPageStatus
        :error="resource.errorMessage.value"
        :loading="resource.loading.value"
        :has-data="resource.hasData.value"
        :paged="false"
        @retry="resource.load()"
      />
      <el-descriptions v-if="resource.data.value" :column="1" border>
        <el-descriptions-item label="当前状态">
          <StatusBadge :type="states[resource.data.value.status]?.type || 'info'">
            {{ states[resource.data.value.status]?.label || resource.data.value.status }}
          </StatusBadge>
        </el-descriptions-item>
        <el-descriptions-item label="待处理订单数">{{ resource.data.value.pending_count }}</el-descriptions-item>
        <el-descriptions-item label="最近投影时间（北京时间）">
          {{ formatBeijingDateTime(resource.data.value.last_projected_at, { fallback: '尚无投影记录' }) }}
        </el-descriptions-item>
      </el-descriptions>
    </div>
  </div>
</template>
<script setup>
import { onMounted } from 'vue'
import { getProjectionStatus } from '@/api/trade'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { formatBeijingDateTime } from '@/utils/datetime'
const states = { pending: { label: '有订单待处理', type: 'warning' }, current: { label: '当前无待处理订单', type: 'success' } }
const resource = useAsyncResource(async (_, { signal }) => (await getProjectionStatus({ signal, suppressToast: true })).data)
onMounted(() => resource.load())
</script>
