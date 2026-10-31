<template>
  <div class="followup-workbench">
    <header class="wb-head">
      <div class="wb-stats">
        <button v-for="s in STATS" :key="s.key" type="button" class="wb-stat" :class="{ active: isStatActive(s.key) }"
                @click="toggleFilter(s.key)">
          <span class="wb-stat-num">{{ w.summary[s.key] }}</span>
          <span class="wb-stat-label">{{ s.label }}<em v-if="s.key === 'issue' && w.summary.urgent">紧急 {{ w.summary.urgent }}</em></span>
        </button>
      </div>
      <div class="wb-actions">
        <GlassButton v-permission="'domestic_followup:admin'" variant="link" left-icon="Setting" @click="configRef.open()">跟进设置</GlassButton>
        <GlassButton v-permission="'domestic_followup:write'" variant="primary" left-icon="EditPen" @click="composer.open()">记一条跟进</GlassButton>
      </div>
    </header>

    <el-alert v-if="w.drafts.value.length" type="info" :closable="false" class="wb-drafts">
      你有 {{ w.drafts.value.length }} 份草稿未确认：
      <GlassButton v-for="d in w.drafts.value.slice(0, 3)" :key="d.id" variant="link" @click="resumeDraft(d)">
        {{ d.shop_name || d.followup_date }}
      </GlassButton>
    </el-alert>

    <el-tabs v-model="tab">
      <el-tab-pane label="待办" name="tasks">
        <div v-loading="w.loading.value" class="wb-cards">
          <FollowupTaskCard v-for="t in w.filtered.value.due" :key="t.id" :task="t" :on-receipt-ok="w.receiptOk"
                            @record="recordFromTask" @snooze="w.snooze" @timeline="t2 => timelineRef.open(t2.customer_id)" />
          <el-empty v-if="!w.loading.value && !w.filtered.value.due.length" description="今天的跟进都完成了" />
        </div>
        <el-collapse v-if="w.filtered.value.upcoming.length" v-model="upcomingOpen" class="wb-upcoming">
          <el-collapse-item name="upcoming" :title="`即将到期（${w.filtered.value.upcoming.length}）`">
            <div class="wb-cards">
              <FollowupTaskCard v-for="t in w.filtered.value.upcoming" :key="t.id" :task="t" :on-receipt-ok="w.receiptOk"
                                @record="recordFromTask" @snooze="w.snooze" @timeline="t2 => timelineRef.open(t2.customer_id)" />
            </div>
          </el-collapse-item>
        </el-collapse>
      </el-tab-pane>
      <el-tab-pane label="异常意见" name="items" lazy>
        <IssueBoard :categories="composer.dicts.domestic_followup_category" @timeline="id => timelineRef.open(id)" @changed="w.loadTasks" />
      </el-tab-pane>
      <el-tab-pane label="我的记录" name="records" lazy>
        <div class="table-card">
          <el-table v-loading="w.records.loading" :data="w.records.items" border class="list-table wb-records" v-sticky-scrollbar
                    @row-click="r => timelineRef.open(r.customer_id)">
            <el-table-column label="日期" prop="followup_date" min-width="110" />
            <el-table-column label="客户" prop="shop_name" min-width="140" show-overflow-tooltip />
            <el-table-column label="摘要" min-width="260" show-overflow-tooltip>
              <template #default="{ row }">{{ row.summary || row.raw_text }}</template>
            </el-table-column>
            <el-table-column label="下次" prop="next_date" min-width="110" />
          </el-table>
          <el-pagination
            v-model:page-size="w.records.pageSize" :current-page="w.records.page" :total="w.records.total"
            :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
            class="pager" @current-change="w.loadRecords" @size-change="w.loadRecords(1)"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <FollowupComposer :composer="composer" />
    <CustomerTimelineDrawer ref="timelineRef" @record="customer => composer.open({ customer })" />
    <FollowupConfigDialog ref="configRef" />
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import GlassButton from '@/components/GlassButton.vue'
import { apiError } from '@/api/domesticFollowup'
import { msgError } from '@/utils/feedback'
import CustomerTimelineDrawer from './components/CustomerTimelineDrawer.vue'
import FollowupConfigDialog from './components/FollowupConfigDialog.vue'
import FollowupComposer from './components/FollowupComposer.vue'
import FollowupTaskCard from './components/FollowupTaskCard.vue'
import IssueBoard from './components/IssueBoard.vue'
import { useFollowupComposer } from './composables/useFollowupComposer'
import { useFollowupWorkbench } from './composables/useFollowupWorkbench'

const STATS = [
  { key: 'receipt', label: '收货回访' }, { key: 'plan', label: '约定跟进' },
  { key: 'issue', label: '异常意见' }, { key: 'upcoming', label: '即将到期' },
]
const route = useRoute()
const tab = ref('tasks')
const timelineRef = ref(null)
const configRef = ref(null)
const upcomingOpen = ref([])  // 「即将到期」默认折叠；点计数卡展开/收起
const w = useFollowupWorkbench()
const composer = useFollowupComposer({
  onSaved: () => { if (tab.value === 'records') w.loadRecords(1) },
  onClosed: () => w.loadTasks(),
})

function toggleFilter(key) {
  if (key === 'upcoming') {
    upcomingOpen.value = upcomingOpen.value.includes('upcoming') ? [] : ['upcoming']
    return
  }
  w.typeFilter.value = w.typeFilter.value === key ? '' : key
}

const isStatActive = key => (key === 'upcoming' ? upcomingOpen.value.includes('upcoming') : w.typeFilter.value === key)

function recordFromTask(task) {
  composer.open({ customer: { id: task.customer_id, shop_name: task.shop_name, writable: true }, source_task_id: task.id })
}

async function resumeDraft(draft) {
  try { await composer.resume(draft.id) } catch (e) { msgError(apiError(e, '草稿加载失败'), e) }
}

function openFromQuery() {
  const id = Number(route.query.customer)
  if (!id) return
  timelineRef.value?.open(id)
}

// 页面被 KeepAlive 缓存时 onMounted 不再触发：盯住 ?customer=，从客户列表换个客户再点也能打开
// flush: 'post' 让首次执行排在挂载之后，timelineRef 才有值
watch(() => route.query.customer, openFromQuery, { immediate: true, flush: 'post' })
// 每次切到「我的记录」都刷新第一页：刚确认的记录要能马上看到
watch(tab, value => { if (value === 'records') w.loadRecords(1) })
onMounted(() => { w.loadTasks(); composer.loadDicts() })  // 看板分类筛选要字典
</script>

<style scoped>
.followup-workbench { display: flex; flex-direction: column; gap: 12px; }
.wb-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.wb-stats { display: flex; gap: 10px; flex-wrap: wrap; }
.wb-actions { display: flex; align-items: center; gap: 8px; }
.wb-records { cursor: pointer; }
.wb-stat { display: flex; flex-direction: column; align-items: flex-start; min-width: 96px; padding: 10px 14px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--card-bg); cursor: pointer; transition: transform 160ms var(--ease-out-strong), border-color 160ms ease; }
.wb-stat:active { transform: scale(0.97); }
.wb-stat.active { border-color: var(--color-primary); }
.wb-stat-num { font-size: 22px; font-weight: 700; }
.wb-stat-label { font-size: 12px; color: var(--text-secondary); }
.wb-stat-label em { margin-left: 4px; font-style: normal; color: var(--color-danger); }
.wb-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
.wb-upcoming { margin-top: 12px; }
@media (max-width: 768px) {
  .wb-cards { grid-template-columns: 1fr; }
  .wb-stat { flex: 1 1 calc(50% - 10px); }
}
</style>
