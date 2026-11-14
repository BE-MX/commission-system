<template>
  <article class="stats-card lg-card is-static churn-entry">
    <div class="stats-chead">
      <h3>客户流失态势</h3>
      <span class="stats-hint">当前快照，不随上方时间范围变化{{ previewHint }}</span>
      <span class="stats-spacer" />
      <GlassButton variant="primary" :disabled="!ship.data.value" @click="open">进入全屏</GlassButton>
    </div>
    <el-alert v-if="ship.state.error" type="error" :title="ship.state.error" :closable="false" show-icon />
    <div v-else class="churn-entry__body">
      <button type="button" class="churn-entry__deck" :disabled="!ship.data.value" aria-label="进入客户流失态势全屏" @click="open">
        <ChurnDeck2d v-if="ship.data.value" compact :model="ship.model.value" :version="ship.state.version" label="客户流失态势缩略图" />
        <span v-else class="churn-muted">{{ ship.state.loading ? '正在加载…' : '暂无数据' }}</span>
      </button>
      <div class="churn-entry__kpis">
        <div class="churn-kpi is-crit"><b>{{ ship.kpis.value.critical }}</b><span>临界（3 天内）</span></div>
        <div class="churn-kpi is-warn"><b>{{ ship.kpis.value.within14 }}</b><span>14 天内将落海</span></div>
        <div class="churn-kpi"><b>{{ ship.kpis.value.fallen }}</b><span>近 30 天已落海</span></div>
      </div>
    </div>
    <ChurnShipStage v-if="stageOpen" :ship="ship" :can-read-all="canReadAll" :can-claim="canClaim"
                    @close="close" @record="row => $emit('record', row)" @timeline="id => $emit('timeline', id)" />
  </article>
</template>
<script setup>
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAuthStore } from '@/stores/auth'
import { useChurnShip } from '../../../composables/useChurnShip'
import ChurnDeck2d from './ChurnDeck2d.vue'

// 三维库只在进入全屏时随沉浸层一起加载
const ChurnShipStage = defineAsyncComponent(() => import('./ChurnShipStage.vue'))
const props = defineProps({ api: { type: Object, required: true }, canReadAll: Boolean, userId: { type: Number, default: null } })
defineEmits(['record', 'timeline'])
const ship = useChurnShip(props.api)
const stageOpen = ref(false)
const canClaim = computed(() => useAuthStore().hasPermission('domestic:write'))
const previewHint = computed(() => {
  const rule = ship.data.value?.rule
  if (!rule || rule.follow_enforced) return ''
  return rule.launch_date ? ` · 「1 个月未跟进」${rule.launch_date} 生效，当前为预演` : ' · 「1 个月未跟进」尚未生效，当前为预演'
})
watch(() => props.userId, id => ship.load(id), { immediate: true })
function open() { if (ship.data.value) stageOpen.value = true }
function close() {
  stageOpen.value = false
  ship.stopPlay()
  ship.setTime(0)
  ship.state.focus = null
  if (ship.userId.value !== props.userId) ship.load(props.userId) // 沉浸层里换过归属人，回到看板的口径
}
function reload() { return ship.load() }
defineExpose({ reload })
</script>
<style src="./churn.css"></style>
