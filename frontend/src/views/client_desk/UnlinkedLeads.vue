<template>
  <section class="unlinked-leads">
    <div class="sub-tabs panel">
      <div class="tabs" role="tablist" aria-label="未绑定线索视图">
        <button v-for="item in subTabs" :key="item.key" type="button" role="tab" class="chip board-focus" :aria-selected="leads.subView.value === item.key" :class="{ on: leads.subView.value === item.key }" @click="leads.setSubView(item.key)">{{ item.label }}</button>
      </div>
      <span class="muted">渠道：TM 询盘</span>
    </div>

    <template v-if="leads.subView.value !== 'review'">
      <p v-if="leads.loading.value" class="muted center" role="status">正在读取线索…</p>
      <div v-else-if="leads.error.value" class="empty-state"><h3>暂时无法读取</h3><p>{{ leads.error.value }}</p><el-button @click="leads.loadThreads">重试</el-button></div>
      <div v-else-if="!cards.length" class="empty-state">
        <h3>{{ leads.subView.value === 'prospect' ? '暂无未建档潜客' : '今天没有待处理的未绑定线索' }}</h3>
        <p>{{ leads.subView.value === 'prospect' ? '在待处理线索中点「未建档先跟踪」后会出现在这里。' : '线索分析完成后会自动出现在这里。' }}</p>
      </div>
      <div v-else class="cards">
        <UnlinkedLeadCard v-for="card in cards" :key="card.id" :card="card" :leads="leads" :variant="leads.subView.value" />
      </div>
    </template>

    <UnlinkedWeeklyReview v-else :leads="leads" />
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, watch } from 'vue'
import { useUnlinkedLeads } from './useUnlinkedLeads'
import UnlinkedLeadCard from './UnlinkedLeadCard.vue'
import UnlinkedWeeklyReview from './UnlinkedWeeklyReview.vue'

const leads = useUnlinkedLeads()
const subTabs = [
  { key: 'pending', label: '待处理线索' },
  { key: 'prospect', label: '未建档潜客' },
  { key: 'review', label: '每周梳理' },
]
const cards = computed(() => leads.subView.value === 'prospect' ? leads.prospectCards.value : leads.pendingCards.value)

// Review jumps land on the card: scroll it into view once the pending list has loaded.
watch(() => [leads.focusId.value, leads.loading.value], async ([id, loading]) => {
  if (id == null || loading) return
  await nextTick()
  document.querySelector(`[data-thread-id="${CSS.escape(String(id))}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
})
onMounted(() => { leads.loadThreads() })
</script>

<style src="./board.css" scoped></style>
<style scoped>
.unlinked-leads { display: grid; gap: 12px; margin-top: 16px; }
.sub-tabs { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; }
.tabs { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { padding: 4px 12px; border: 1px solid var(--border-color); border-radius: 999px; background: var(--card-bg); color: var(--text-secondary); font: 500 12px var(--font-body); cursor: pointer; }
.chip.on { border-color: var(--tag-gold-border); background: var(--tag-gold-bg); color: var(--tag-gold-text); }
.cards { display: grid; gap: 12px; }
.center { padding: 30px; text-align: center; }
</style>
