<template>
  <div class="followup-workbench">
    <div class="wb-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>
    <div class="wb-stats">
      <OverviewMetricCard v-for="s in STATS" :key="s.key" :label="s.label"
                          :value="w.loaded.value ? w.summary[s.key] : '—'" :icon="s.icon" :tone="s.tone"
                          :hint="s.key === 'issue' && w.summary.urgent ? `紧急 ${w.summary.urgent}` : ''"
                          interactive :selected="isStatActive(s.key)" @click="toggleFilter(s.key)" />
    </div>

    <el-alert v-if="w.drafts.value.length" type="info" :closable="false" class="wb-drafts">
      你有 {{ w.drafts.value.length }} 份草稿未确认：
      <GlassButton v-for="d in w.drafts.value.slice(0, 3)" :key="d.id" variant="link" @click="resumeDraft(d)">
        {{ d.shop_name || d.followup_date }}
      </GlassButton>
    </el-alert>

    <div class="wb-panel lg-card is-static">
      <div class="action-bar">
        <div class="wb-actions">
          <el-checkbox v-model="potentialOnly">仅显示潜在客户</el-checkbox>
          <GlassButton v-permission="'domestic_followup:write'" variant="primary" left-icon="EditPen" @click="composer.open()">记一条跟进</GlassButton>
          <GlassButton v-permission="'domestic_followup:admin'" variant="outline" left-icon="Setting" @click="configRef.open()">跟进设置</GlassButton>
        </div>
        <GlassButton v-if="tab === 'tasks'" variant="ghost" left-icon="Refresh" :loading="w.loading.value" @click="w.loadTasks">刷新</GlassButton>
      </div>
      <el-tabs v-model="tab" class="wb-tabs">
        <el-tab-pane :label="canReadAll ? '管理总览' : '跟进总览'" name="overview" lazy>
          <FollowupOverview ref="overviewRef" :potential-only="potentialOnly" @timeline="id => timelineRef.open(id)"
                            @edit="id => editorRef.open(id)" @history="id => historyRef.open(id)" />
        </el-tab-pane>
        <el-tab-pane label="待办" name="tasks">
          <ListPageStatus :error="w.error.value" :has-data="w.loaded.value" :loading="w.loading.value" :paged="false" @retry="w.loadTasks" />
          <div v-loading="w.loading.value" class="wb-cards">
            <FollowupTaskCard v-for="t in w.filtered.value.due" :key="t.id" :task="t" :on-receipt-ok="w.receiptOk"
                              @record="recordFromTask" @snooze="w.snooze" @timeline="t2 => timelineRef.open(t2.customer_id)" />
            <el-empty v-if="!w.loading.value && !w.error.value && !w.filtered.value.due.length"
                      class="wb-empty" :description="w.typeFilter.value ? '当前分类暂无待办' : '今天的跟进都完成了'">
              <GlassButton v-if="w.typeFilter.value" variant="outline" @click="w.typeFilter.value = ''">查看全部待办</GlassButton>
            </el-empty>
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
          <IssueBoard ref="issuesRef" :potential-only="potentialOnly" :categories="composer.dicts.domestic_followup_category" @timeline="id => timelineRef.open(id)" @changed="w.loadTasks" />
        </el-tab-pane>
        <el-tab-pane label="我的记录" name="records" lazy>
          <div ref="recordsPanel" class="table-card">
            <div class="action-bar">
              <TableTools v-model:visible-keys="visibleRecordKeys" v-model:density="recordDensity"
                          :columns="recordColumns" :fullscreen="recordsFullscreen" :loading="w.records.loading"
                          @refresh="w.loadRecords(w.records.page)" @fullscreen="toggleRecordsFullscreen" />
            </div>
            <ListPageStatus v-if="w.records.error" :error="w.records.error" :has-data="w.records.loaded" :loading="w.records.loading" :data-page="w.records.page" @retry="w.loadRecords(w.records.page)" />
            <el-table v-loading="w.records.loading" :data="w.records.items" border class="list-table wb-records" :class="recordDensityClass" v-sticky-scrollbar
                      @row-click="r => timelineRef.open(r.customer_id)">
              <el-table-column v-if="visibleRecordKeys.includes('followup_date')" label="日期" prop="followup_date" min-width="110" />
              <el-table-column v-if="visibleRecordKeys.includes('shop_name')" label="客户" prop="shop_name" min-width="140" show-overflow-tooltip />
              <el-table-column v-if="visibleRecordKeys.includes('summary')" label="摘要" min-width="260" show-overflow-tooltip>
                <template #default="{ row }">{{ row.summary || row.raw_text }}</template>
              </el-table-column>
              <el-table-column v-if="visibleRecordKeys.includes('next_date')" label="下次" prop="next_date" min-width="110" />
              <el-table-column label="操作" class-name="table-action-column" min-width="180" fixed="right">
                <template #default="{ row }">
                  <GlassButton variant="link" @click.stop="myRecordDetail = row">详情</GlassButton>
                  <GlassButton v-if="mayEditFollowup(auth.user, row)" v-permission="'domestic_followup:write'" variant="link" @click.stop="editorRef.open(row.id)">修改</GlassButton>
                  <GlassButton variant="link" @click.stop="historyRef.open(row.id)">修改历史</GlassButton>
                </template>
              </el-table-column>
            </el-table>
            <el-pagination
              v-model:page-size="w.records.pageSize" :current-page="w.records.page" :total="w.records.total"
              :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
              class="pager" @current-change="w.loadRecords" @size-change="w.loadRecords(1)"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <FollowupComposer :composer="composer" />
    <CustomerTimelineDrawer ref="timelineRef" @record="customer => composer.open({ customer })"
                            @edit="id => editorRef.open(id)" @history="id => historyRef.open(id)" />
    <FollowupConfigDialog ref="configRef" />
    <FollowupEditDialog ref="editorRef" @saved="afterEdit" />
    <FollowupHistoryDrawer ref="historyRef" />
    <FollowupRecordDrawer :record="myRecordDetail" @close="myRecordDetail = null"
                          @timeline="id => { myRecordDetail = null; timelineRef.open(id) }"
                          @edit="id => { myRecordDetail = null; editorRef.open(id) }"
                          @history="id => { myRecordDetail = null; historyRef.open(id) }" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Box, Calendar, ChatDotRound, Warning } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import GlassButton from '@/components/GlassButton.vue'
import OverviewMetricCard from '@/components/OverviewMetricCard.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { apiError } from '@/api/domesticFollowup'
import { msgError } from '@/utils/feedback'
import CustomerTimelineDrawer from './components/CustomerTimelineDrawer.vue'
import FollowupConfigDialog from './components/FollowupConfigDialog.vue'
import FollowupComposer from './components/FollowupComposer.vue'
import FollowupTaskCard from './components/FollowupTaskCard.vue'
import FollowupOverview from './components/FollowupOverview.vue'
import FollowupEditDialog from './components/FollowupEditDialog.vue'
import FollowupHistoryDrawer from './components/FollowupHistoryDrawer.vue'
import FollowupRecordDrawer from './components/FollowupRecordDrawer.vue'
import { mayEditFollowup } from './followupEdit'
import IssueBoard from './components/IssueBoard.vue'
import { useFollowupComposer } from './composables/useFollowupComposer'
import { useFollowupWorkbench } from './composables/useFollowupWorkbench'

const STATS = [
  { key: 'receipt', label: '收货回访', icon: Box, tone: 'gold' },
  { key: 'plan', label: '约定跟进', icon: ChatDotRound, tone: 'info' },
  { key: 'issue', label: '异常意见', icon: Warning, tone: 'warning' },
  { key: 'upcoming', label: '即将到期', icon: Calendar, tone: 'violet' },
]
const route = useRoute()
const recordColumns = [
  { key: 'followup_date', label: '日期' }, { key: 'shop_name', label: '客户' },
  { key: 'summary', label: '摘要' }, { key: 'next_date', label: '下次' },
]
const { density: recordDensity, densityClass: recordDensityClass, visibleKeys: visibleRecordKeys,
  panelRef: recordsPanel, isFullscreen: recordsFullscreen, toggleFullscreen: toggleRecordsFullscreen } = useTableView('domestic-followup-records', recordColumns)
const auth = useAuthStore()
const canReadAll = computed(() => auth.hasPermission('domestic_followup:read_all'))
const tab = ref(canReadAll.value ? 'overview' : 'tasks')
const overviewRef = ref(null)
const timelineRef = ref(null)
const configRef = ref(null)
const editorRef = ref(null), historyRef = ref(null), issuesRef = ref(null), myRecordDetail = ref(null)
const potentialOnly = ref(false)
const upcomingOpen = ref([])  // 「即将到期」默认折叠；点计数卡展开/收起
const w = useFollowupWorkbench(potentialOnly)
const composer = useFollowupComposer({
  onSaved: () => {
    if (tab.value === 'records') w.loadRecords(1)
    overviewRef.value?.refresh()
  },
  onClosed: () => w.loadTasks(),
})

function toggleFilter(key) {
  tab.value = 'tasks'
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
  if (route.name !== 'DomesticFollowups') return  // 页面缓存在后台时，别的页面换路由不该弹本页的抽屉
  const id = Number(route.query.customer)
  if (!id) return
  timelineRef.value?.open(id)
}

// 首次打开在 onMounted 里调（那时 timelineRef 才有值）；之后被 KeepAlive 缓存时 onMounted 不再触发，
// 改盯 fullPath：客户列表的「跟进」带 t=时间戳，同一客户重复点也会变
watch(() => route.fullPath, openFromQuery, { flush: 'post' })
// 每次切到「我的记录」都刷新第一页：刚确认的记录要能马上看到
watch(tab, value => {
  if (value === 'records') w.loadRecords(1)
  if (value === 'overview') overviewRef.value?.refresh()
})
watch(potentialOnly, () => {
  w.resetScope()
  myRecordDetail.value = null
  w.loadTasks()
  if (tab.value === 'records') w.loadRecords(1)
}, { flush: 'sync' })
function afterEdit() {
  myRecordDetail.value = null
  w.loadTasks()
  if (w.records.loaded || tab.value === 'records') w.loadRecords(w.records.page)
  overviewRef.value?.refresh()
  issuesRef.value?.refresh()
}
onMounted(() => { w.loadTasks(); composer.loadDicts(); openFromQuery() })  // 看板分类筛选要字典
</script>

<style scoped>
.followup-workbench { position: relative; display: flex; flex-direction: column; gap: 20px; min-width: 0; }
.wb-aurora { inset: -24px -28px; }
.wb-stats, .wb-panel, .wb-drafts { position: relative; z-index: 1; }
.wb-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.wb-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.wb-panel { min-width: 0; --el-table-bg-color: transparent; --el-table-tr-bg-color: transparent; }
.wb-panel > .action-bar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding: 16px 20px; border-bottom: 1px solid var(--border-color); }
.wb-tabs { padding: 0 20px 20px; }
.wb-panel :deep(.table-card:not(.table-card--fullscreen)) { border: 0; border-radius: 0; box-shadow: none; background: transparent; }
.wb-empty { grid-column: 1 / -1; }
.wb-records { cursor: pointer; }
.wb-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr)); gap: 16px; }
.wb-upcoming { margin-top: 12px; }
@media (max-width: 768px) {
  .wb-cards { grid-template-columns: 1fr; }
  .wb-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .wb-panel > .action-bar { padding: 12px; }
  .wb-tabs { padding: 0 12px 12px; }
}
</style>
