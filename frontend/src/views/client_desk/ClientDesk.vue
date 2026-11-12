<template>
  <main class="client-desk">
    <header class="heading">
      <div>
        <div class="eyebrow">MY PRIVATE SEA · 私海助理</div>
        <h1>我的私海工作台</h1>
        <p class="muted">按标签把客户分栏，先看哪一栏该动，再点开某一位客户。</p>
      </div>
      <span class="muted">{{ board.data.value?.biz_date || currentBeijingDate() }} · 仅我的私海</span>
    </header>

    <section class="toolbar panel">
      <div class="tabs" role="tablist" aria-label="客户范围">
        <button v-for="item in tabs" :key="item.key" type="button" role="tab" class="board-focus" :aria-selected="view === item.key" :class="{ on: view === item.key }" @click="switchView(item.key)">
          {{ item.label }} <small v-if="item.count != null">{{ item.count }}</small>
        </button>
      </div>
      <template v-if="view !== 'unlinked'">
        <el-input v-model="board.keyword.value" clearable placeholder="搜索客户、联系人或国家" aria-label="搜索本人私海" :prefix-icon="Search" />
        <div class="controls">
          <label>分栏依据 <el-select v-model="board.groupBy.value" aria-label="分栏依据"><el-option v-for="(dim, key) in DIMENSIONS" :key="key" :label="dim.label" :value="key" /></el-select></label>
          <label>栏内细分 <el-select v-model="board.subBy.value" aria-label="栏内细分"><el-option label="不细分" value="" /><el-option v-for="(dim, key) in DIMENSIONS" :key="key" :label="dim.label" :value="key" :disabled="key === board.groupBy.value" /></el-select></label>
          <el-popover trigger="click" :width="320" placement="bottom-start">
            <template #reference><el-button>＋ 标签筛选{{ board.tagCodes.value.length ? `（${board.tagCodes.value.length}）` : '' }}</el-button></template>
            <div v-for="group in board.filters.value" :key="group.kind" class="filter-group">
              <span class="muted">{{ group.label }}</span>
              <div class="filter-tags"><button v-for="tag in group.tags" :key="tag.code" type="button" class="tag board-focus" :class="['tone-' + tagTone(tag), { picked: board.tagCodes.value.includes(tag.code) }]" :aria-pressed="board.tagCodes.value.includes(tag.code)" @click="board.toggleTag(tag.code)">{{ tag.label }}</button></div>
            </div>
            <p v-if="!board.filters.value.length" class="muted">暂无可筛选的标签。</p>
          </el-popover>
          <span class="spacer" />
          <el-button @click="board.setAll(true)">全部展开</el-button>
          <el-button @click="board.setAll(false)">全部收起</el-button>
        </div>
        <div class="legend">
          <span class="muted">标签颜色</span>
          <span v-for="(dim, key) in DIMENSIONS" :key="key" class="tag" :class="'tone-' + dim.tone">{{ key === 'ai' ? '✦ ' : '' }}{{ dim.label }}</span>
          <span v-for="code in board.tagCodes.value" :key="code" class="tag picked-chip">{{ tagLabel(code) }}<button type="button" class="link-button" :aria-label="`取消筛选 ${tagLabel(code)}`" @click="board.toggleTag(code)">×</button></span>
          <span class="spacer" />
          <span class="muted">共 {{ board.visible.value.length }} 位客户 · {{ board.lanes.value.length }} 栏</span>
        </div>
      </template>
    </section>

    <section v-if="view !== 'unlinked'" class="board" aria-live="polite">
      <p v-if="board.loading.value" class="muted center" role="status">正在读取我的私海…</p>
      <div v-else-if="board.error.value" class="empty-state"><h3>暂时无法读取</h3><p>{{ board.error.value }}</p><el-button @click="board.load">重试</el-button></div>
      <div v-else-if="!board.lanes.value.length" class="empty-state"><h3>{{ view === 'todo' ? '今天没有需要特别跟进的客户' : '暂无匹配客户' }}</h3><p>试试其他筛选或分栏方式。</p></div>
      <BoardLane v-for="lane in board.lanes.value" v-else :key="board.groupBy.value + ':' + lane.key" :lane="lane" :dimension="board.groupBy.value" :sub-dimension="board.subBy.value" :open="board.openLanes.value.has(lane.key)" :selected-id="desk.selected.value" :options="board.options.value" @toggle="board.toggleLane" @open="openCustomer" />
    </section>

    <UnlinkedConversations v-else :desk="desk" />

    <CustomerDrawer :desk="desk" :open="drawerOpen" @close="closeDrawer" @copy="dialogs?.copyDraft()" @whatsapp="dialogs?.openWa()" />
    <DetailDrawer v-model="desk.evidenceOpen.value" :title="desk.evidence.value ? `${timelineType(desk.evidence.value)}详情` : '记录详情'">
      <p v-if="desk.evidenceLoading.value" role="status">正在核验来源权限…</p>
      <el-alert v-else-if="desk.evidenceError.value" :title="desk.evidenceError.value" type="error" :closable="false" />
      <TimelineEventDetails v-else-if="desk.evidence.value" :event="desk.evidence.value" />
    </DetailDrawer>
    <DeskDialogs ref="dialogs" :desk="desk" />
  </main>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { currentBeijingDate } from '@/utils/datetime'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { timelineType } from './deskController'
import { DIMENSIONS, tagTone } from './boardModel'
import { useClientDesk } from './useClientDesk'
import { useBoard } from './useBoard'
import BoardLane from './BoardLane.vue'
import CustomerDrawer from './CustomerDrawer.vue'
import DeskDialogs from './DeskDialogs.vue'
import TimelineEventDetails from './TimelineEventDetails.vue'
import UnlinkedConversations from './UnlinkedConversations.vue'

const route = useRoute()
const board = useBoard()
const desk = useClientDesk(route, { autoSelect: false, boardMode: true, onRefresh: () => board.load() })
const view = ref('all'), drawerOpen = ref(false), dialogs = ref(null)
const tabs = computed(() => [
  { key: 'todo', label: '今日建议', count: board.todoCount.value },
  { key: 'all', label: '全部客户', count: null },
  { key: 'unlinked', label: '未关联会话', count: null },
])
const tagLabel = code => board.cards.value.flatMap(c => c.tags || []).find(t => t.code === code)?.label || code

function switchView(key) {
  view.value = key
  board.todoOnly.value = key === 'todo'
  desk.mode.value = key === 'unlinked' ? 'unlinked' : 'all'
}
function openCustomer(card) { drawerOpen.value = true; void desk.select(card, false) }
function closeDrawer() { drawerOpen.value = false; desk.closeDetail() }
// The legacy page opened a customer from ?company_id=; keep deep links working.
watch(() => desk.selected.value, value => { if (value && view.value !== 'unlinked') drawerOpen.value = true })
onMounted(async () => {
  await Promise.all([board.load(), desk.init()])
})
</script>

<style src="./board.css" scoped></style>
<style scoped>
.client-desk { max-width: 1440px; margin: auto; padding: 8px 6px 28px; color: var(--text-primary); font: 500 14px/1.6 var(--font-body); }
.heading { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; margin-bottom: 16px; }
.eyebrow { color: var(--button-primary-text); font: 700 10px var(--font-display); letter-spacing: 0.12em; }
h1 { margin: 3px 0; font: 800 28px/1.2 var(--font-display); letter-spacing: -0.03em; }
.heading p { margin: 0; }
.toolbar { display: grid; gap: 12px; background: var(--dash-glass-bg); border-color: var(--dash-glass-border); box-shadow: var(--dash-glass-shadow); }
.tabs { display: flex; gap: 4px; padding: 3px; border-radius: 12px; background: var(--tag-neutral-bg); justify-self: start; }
.tabs button { padding: 6px 14px; border: 0; border-radius: 9px; background: transparent; color: var(--text-secondary); font: 600 13px var(--font-display); cursor: pointer; }
.tabs .on { background: var(--card-bg); color: var(--text-primary); box-shadow: var(--card-shadow); }
.tabs small { color: var(--button-primary-text); font-variant-numeric: tabular-nums; }
.controls, .legend { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.controls label { display: inline-flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 13px; }
.controls .el-select { width: 130px; }
.controls .el-button + .el-button { margin-left: 0; }
.spacer { flex: 1; }
.filter-group + .filter-group { margin-top: 10px; }
.filter-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.filter-tags .tag { cursor: pointer; }
.tag.picked { box-shadow: 0 0 0 2px var(--button-focus); }
.picked-chip { padding-right: 0; }
.board { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(330px, 100%), 1fr)); gap: 16px; margin-top: 16px; align-items: start; }
.board > .empty-state, .board > .center { grid-column: 1 / -1; }
.center { padding: 40px; text-align: center; }
@media (max-width: 720px) {
  .client-desk { padding: 4px 0 20px; }
  .heading { flex-wrap: wrap; align-items: flex-start; }
  h1 { font-size: 24px; }
  .tabs { justify-self: stretch; }
  .tabs button { flex: 1; min-height: 38px; padding: 6px 8px; }
  .controls label { flex: 1 1 140px; }
  .controls .el-select { flex: 1; }
}
</style>
