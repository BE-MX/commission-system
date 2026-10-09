<template>
  <DetailDrawer :model-value="modelValue" title="出库问题单据" :width="660" @update:model-value="emit('update:modelValue', $event)">
    <div class="problem-summary">
      <div><strong>{{ state.hasLoaded.value ? `${state.total.value} 项需要核对` : '正在核对问题单据' }}</strong><p>仅显示方舟出库单当前的异常状态，与出库单列表一致。</p></div>
      <GlassButton left-icon="Refresh" :loading="state.loading.value" @click="load()">刷新</GlassButton>
    </div>
    <ListPageStatus :error="state.errorMessage.value" :loading="state.loading.value" :has-data="state.hasData.value" :data-page="state.dataPage.value" @retry="load()" />
    <el-empty v-if="state.isEmpty.value" :image-size="80" description="当前没有需要核对的出库问题" />
    <ul v-if="state.hasData.value" class="problem-list" :aria-busy="state.loading.value">
      <li v-for="item in state.list.value" :key="item.key" class="problem-item">
        <div class="problem-heading"><strong>{{ item.number }}</strong><StatusBadge type="warning">{{ item.problem }}</StatusBadge></div>
        <p class="problem-meta">{{ item.customer_name || '客户信息待核对' }}</p>
        <p class="problem-guidance">{{ item.guidance }}</p>
        <GlassButton v-if="item.target" variant="link" right-icon="ArrowRight" :disabled="state.isStale.value" @click="openRelated(item)">查看相关出库单</GlassButton>
      </li>
    </ul>
    <el-pagination v-if="state.total.value > 20" class="problem-pager" :current-page="state.page.value" :page-size="state.pageSize.value" :page-sizes="[20, 50, 100]" :total="state.total.value" layout="total, sizes, prev, pager, next" @current-change="changePage" @size-change="state.handleSizeChange" />
    <p v-if="checkedAt" class="problem-checked">查询时间：{{ formatBeijingDateTime(checkedAt) }}</p>
  </DetailDrawer>
</template>

<script setup>
import { watch } from 'vue'
import { useRouter } from 'vue-router'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAuthStore } from '@/stores/auth'
import { formatBeijingDateTime } from '@/utils/datetime'
import { useOutboundProblems } from './composables/useOutboundProblems'

const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue'])
const router = useRouter(), auth = useAuthStore()
const { state, checkedAt, reset, load, changePage, location } = useOutboundProblems()
watch(() => props.modelValue, visible => { reset(); if (visible) load() }, { immediate: true })
watch(() => JSON.stringify([auth.user?.id, auth.user?.roles, auth.user?.permissions]), () => {
  reset()
  emit('update:modelValue', false)
})
async function openRelated(item) {
  const target = location(item)
  if (!target) return
  await router.push(target)
  emit('update:modelValue', false)
}
</script>

<style scoped>
.problem-summary{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
.problem-summary strong{font-size:16px;color:var(--text-primary)}
.problem-summary p,.problem-meta,.problem-checked{font-size:12px;color:var(--text-secondary);line-height:1.6}
.problem-summary p{margin:6px 0 16px}
.problem-list{list-style:none;padding:0;margin:0}
.problem-item{padding:18px 0;border-bottom:1px solid var(--border-color)}
.problem-heading{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.problem-heading>strong{font-size:15px;color:var(--text-primary);overflow-wrap:anywhere}
.problem-meta{margin:8px 0 0;overflow-wrap:anywhere}
.problem-guidance{font-size:13px;line-height:1.7;color:var(--text-secondary);margin:8px 0}
.problem-pager{margin-top:20px;justify-content:center}
.problem-checked{margin-top:16px}
</style>
