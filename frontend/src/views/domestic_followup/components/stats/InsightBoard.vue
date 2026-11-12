<template>
  <section>
    <div class="stats-ai-head"><StatusBadge type="warning"><el-icon><MagicStick /></el-icon> AI 分析</StatusBadge>
      <span v-if="snapshot">生成于 {{ formatBeijingShortDateTime(snapshot.generated_at) }} · 依据近 60 天 {{ snapshot.record_count }} 条已确认记录</span>
      <span v-else>还没有已完成的建议快照</span><span class="stats-spacer" />
      <GlassButton :loading="refreshing" :disabled="data.refresh.enabled === false || data.refresh.remaining <= 0 || data.refresh.status === 'running'" @click="refresh">{{ refreshing || data.refresh.status === 'running' ? '正在生成' : '重新生成' }} · 今日剩余 {{ data.refresh.remaining }} 次</GlassButton></div>
    <el-alert v-if="data.refresh.enabled === false" type="info" title="AI 建议生成已停用，可在跟进设置中开启。已有建议仍可查看。" :closable="false" />
    <el-alert v-else-if="data.refresh.status === 'failed' && !error" type="warning" title="最近一次生成失败，已保留上一份建议，可重新生成。" :closable="false" />
    <div>
      <div v-if="snapshot" class="stats-grid stats-g3"><article v-for="(highlight, index) in snapshot.highlights" :key="highlight.key" class="stats-card stats-highlight lg-card is-static" :style="{ '--stats-index': index }">
        <div class="stats-highlight__label">{{ highlight.label }}</div><h4>{{ highlight.title }}</h4><p>{{ highlight.body }}</p></article></div>
      <StatsSegments :model-value="aiTab" :options="scopeOptions" label="建议范围" @change="$emit('update:aiTab', $event)" />
      <div v-if="aiTab === 'me' && canReadAll" class="stats-chips" style="margin-top: 16px"><button v-for="user in roster" :key="user.id" type="button" class="stats-chip" :aria-pressed="aiPerson === user.id" @click="$emit('update:aiPerson', user.id); $emit('ai-person-change', user.id)">
        <span class="stats-avatar">{{ user.real_name.slice(-1) }}</span>{{ user.real_name }}</button></div>
      <Transition name="stats-fade" mode="out-in"><div v-if="snapshot" :key="aiTab" v-loading="loading">
        <template v-if="aiTab === 'me'">
          <template v-for="category in ['deal', 'cold']" :key="category">
            <div class="stats-section"><h3>{{ labels[category] }}</h3><span>{{ category === 'deal' ? '问价、要样、问交期等积极信号' : '未回复、间隔拉长或负面信号' }}</span></div>
            <div class="stats-grid" :class="category === 'deal' ? 'stats-g3' : 'stats-g2'"><InsightCard v-for="item in items(category)" :key="item.id" :item="item" :generated-at="snapshot.generated_at" :record-count="snapshot.record_count" @task="openTask" @record="item => $emit('record', item)" @feedback="feedback" /></div>
            <div v-if="!items(category).length" class="stats-empty">本周期没有需要特别提醒的</div>
          </template>
          <div class="stats-section"><h3>节奏与方式</h3><span>{{ canReadAll ? '本人和管理者看到的是同一份评语' : '针对你自己的记录 · 管理者也能看到这一份' }}</span></div>
          <div class="stats-grid stats-g2"><InsightCard v-for="item in [...items('rhythm'), ...items('method')]" :key="item.id" :item="item" :generated-at="snapshot.generated_at" :record-count="snapshot.record_count" @feedback="feedback" /></div>
          <div v-if="!items('rhythm').length && !items('method').length" class="stats-empty">本周期没有需要特别提醒的</div>
        </template>
        <template v-else>
          <template v-for="category in companyCategories" :key="category">
            <div class="stats-section"><h3>{{ labels[category] }}</h3><span>{{ categoryHints[category] }}</span></div>
            <div class="stats-grid" :class="category === 'common' ? 'stats-g3' : 'stats-g2'"><InsightCard v-for="item in items(category)" :key="item.id" :item="item" company :generated-at="snapshot.generated_at" :record-count="snapshot.record_count" @adopt="openAdopt" @feedback="feedback" /></div>
            <div v-if="!items(category).length" class="stats-empty">本周期没有需要特别提醒的</div>
          </template>
        </template>
      </div></Transition>
      <div v-if="!snapshot" class="stats-card lg-card is-static stats-empty" v-loading="loading">{{ loading ? '正在读取建议快照' : '定时任务每天生成；也可点击「重新生成」创建第一份快照' }}</div>
    </div>
    <el-dialog v-model="taskVisible" title="生成约定跟进" width="480px" append-to-body>
      <el-form label-position="top"><el-form-item label="到期日期" required><el-date-picker v-model="taskForm.due_date" type="date" value-format="YYYY-MM-DD" :disabled-date="pastDate" /></el-form-item>
        <el-form-item label="待办内容" required><el-input v-model="taskForm.content" type="textarea" :rows="4" maxlength="500" show-word-limit /></el-form-item></el-form>
      <template #footer><GlassButton @click="taskVisible = false">取消</GlassButton><GlassButton variant="primary" :loading="taskSaving" @click="saveTask">生成待办</GlassButton></template>
    </el-dialog>
    <el-dialog v-model="adoptVisible" title="标记已采纳" width="480px" append-to-body>
      <el-input v-model="adoptNote" type="textarea" :rows="4" maxlength="500" placeholder="备注（可选）" />
      <template #footer><GlassButton @click="adoptVisible = false">取消</GlassButton><GlassButton variant="primary" :loading="adoptSaving" @click="saveAdopt">确认采纳</GlassButton></template>
    </el-dialog>
  </section>
</template>
<script setup>
import StatusBadge from '@/components/StatusBadge.vue'
import { computed, reactive, ref } from 'vue'
import { MagicStick } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import StatsSegments from './StatsSegments.vue'
import InsightCard from './InsightCard.vue'
import { formatBeijingShortDateTime, currentBeijingDate, formatCalendarDate } from '@/utils/datetime'
import { CATEGORY_LABELS, groupInsights } from './statsModel'

const props = defineProps({
  data: { type: Object, required: true }, roster: { type: Array, default: () => [] }, canReadAll: Boolean,
  aiPerson: [Number, String], aiTab: String, loading: Boolean, refreshing: Boolean, error: String,
  refreshHandler: Function, feedbackHandler: Function, taskHandler: Function, adoptHandler: Function,
})
const emit = defineEmits(['update:aiPerson', 'update:aiTab', 'ai-person-change', 'record'])
const labels = CATEGORY_LABELS
const scopeOptions = computed(() => [{ value: 'me', label: props.canReadAll ? '个人层面' : '我的客户' }, { value: 'co', label: '公司层面' }])
const snapshot = computed(() => props.aiTab === 'me' ? props.data.personal : props.data.company)
const companyCategories = computed(() => props.canReadAll ? ['common', 'single', 'practice', 'frequency'] : ['common', 'practice'])
const categoryHints = { common: '多家客户提到同一件事', single: '不成规律，但客户等级高或影响大', practice: '从已成交客户的跟进过程里复盘 · 样本观察', frequency: '给管理者的配置建议，不会自动生效' }
const taskVisible = ref(false), taskSaving = ref(false), taskItem = ref(null)
const taskForm = reactive({ due_date: '', content: '' })
const adoptVisible = ref(false), adoptSaving = ref(false), adoptItem = ref(null), adoptNote = ref('')
function items(category) { return groupInsights(snapshot.value?.items, category) }
function openTask(item) { taskItem.value = item; taskForm.due_date = item.suggested_date || currentBeijingDate(); taskForm.content = item.suggested_action || item.title; taskVisible.value = true }
function pastDate(day) { return formatCalendarDate(day) < currentBeijingDate() }
async function refresh() { try { await props.refreshHandler?.() } catch { return } }
async function feedback(item, value) { await props.feedbackHandler?.(item.id, value) }
async function saveTask() {
  if (!taskForm.due_date || !taskForm.content.trim()) return
  taskSaving.value = true
  try { await props.taskHandler?.(taskItem.value.id, { due_date: taskForm.due_date, content: taskForm.content.trim() }); taskVisible.value = false }
  catch { return } finally { taskSaving.value = false }
}
function openAdopt(item) { adoptItem.value = item; adoptNote.value = item.adoption_note || ''; adoptVisible.value = true }
async function saveAdopt() {
  adoptSaving.value = true
  try { await props.adoptHandler?.(adoptItem.value.id, adoptNote.value); adoptVisible.value = false }
  catch { return } finally { adoptSaving.value = false }
}
</script>
