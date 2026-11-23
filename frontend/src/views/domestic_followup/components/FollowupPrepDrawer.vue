<template>
  <el-drawer v-model="c.visible.value" :direction="isMobile ? 'btt' : 'rtl'" :size="isMobile ? '92%' : '640px'"
             :title="`准备跟进 · ${c.customer.value?.shop_name || ''}`" class="prep-drawer" append-to-body destroy-on-close
             :before-close="beforeClose">
    <div v-loading="c.loading.value" class="prep-body">
      <div class="steps" aria-label="准备步骤"><span v-for="n in 3" :key="n" :class="{ on: c.step.value >= n }" /></div>
      <p class="step-label">第 {{ c.step.value }} 步 · {{ ['选场景', '背调', '策略'][c.step.value - 1] }}</p>
      <div v-if="c.step.value < 3 && c.context.value?.history_count" class="history-banner">
        <span>已保存 {{ c.context.value.history_count }} 张准备卡</span>
        <GlassButton variant="outline" @click="historyRef.open(c.customer.value)">查看历史准备卡</GlassButton>
      </div>

      <section v-if="c.step.value === 1 && c.context.value" class="prep-section">
        <div v-if="c.context.value.recommendation" class="recommend"><StatusBadge type="warning">推荐</StatusBadge><div><strong>{{ c.context.value.recommendation.code }}</strong><p>{{ c.context.value.recommendation.reason }}</p></div></div>
        <div class="scene-grid">
          <button v-for="row in visibleTemplates" :key="row.code" type="button" class="scene-card" :aria-pressed="c.form.value.template_code === row.code" @click="c.form.value.template_code = row.code">
            <strong>{{ row.code }} {{ row.name }}</strong><span>{{ sceneHints[row.code] || '只解决本次一件事' }}</span>
          </button>
        </div>
        <GlassButton v-if="isMobile && !showAllScenes" variant="ghost" class="more-scenes" @click="showAllScenes = true">更多场景</GlassButton>
        <el-form label-position="top"><el-form-item label="本次只解决一件事" required><el-input v-model="c.form.value.goal" maxlength="200" placeholder="例如：确认刘海问题现在是否还影响销售" /></el-form-item></el-form>
      </section>

      <section v-else-if="c.step.value === 2" class="prep-section">
        <div class="context-bar"><el-tag effect="plain">{{ c.template.value?.code }}</el-tag><strong>{{ c.form.value.goal }}</strong><GlassButton variant="link" @click="c.step.value = 1">换场景</GlassButton></div>
        <section><div class="section-title">已知 <span>从上一张已使用准备卡带出，可改可删</span></div>
          <div class="fact-list"><div v-for="(fact, index) in c.form.value.known_facts" :key="index" class="fact-row" :class="{ stale: isStale(fact) }">
            <el-input v-model="fact.text" type="textarea" :rows="2" placeholder="补充一条有来源的已知事实" />
            <div class="fact-meta"><el-input v-model="fact.source_kind" placeholder="来源性质" /><el-input v-model="fact.source_ref" placeholder="来源，例如：跟进 #55" /><el-date-picker v-model="fact.observed_at" type="date" value-format="YYYY-MM-DD" placeholder="观察日期" /><GlassButton variant="link" link-tone="danger" @click="c.form.value.known_facts.splice(index, 1)">删除</GlassButton></div>
            <StatusBadge v-if="isStale(fact)" type="warning" size="small">可能过期</StatusBadge>
          </div></div>
          <GlassButton variant="outline" left-icon="Plus" @click="c.addFact">补一条已知</GlassButton>
        </section>
        <el-form label-position="top">
          <el-form-item label="待确认"><el-input v-model="c.form.value.toConfirmText" type="textarea" :rows="2" placeholder="每行一点，1–2 点即可，不用凑齐画像" /></el-form-item>
          <div class="form-grid"><el-form-item label="联系依据"><el-select v-model="c.form.value.reason_source" class="full"><el-option label="上次记录" value="last_followup" /><el-option label="客户主动询问" value="customer_inquiry" /><el-option label="公开动态" value="public_update" /><el-option label="其他" value="other" /></el-select></el-form-item><el-form-item label="依据日期"><el-date-picker v-model="c.form.value.reason_date" type="date" value-format="YYYY-MM-DD" class="full" /></el-form-item></div>
          <el-form-item label="联系说明"><el-input v-model="c.form.value.contact_reason" maxlength="300" /></el-form-item>
          <template v-if="c.template.value?.prep_fields.length"><h3 class="section-title">本场景要准备的</h3><FollowupDynamicField v-for="field in c.template.value.prep_fields" :key="field.key" :field="field" v-model="c.form.value.answers[field.key]" /></template>
        </el-form>
      </section>

      <section v-else-if="c.step.value === 3" class="prep-section">
        <el-alert v-if="c.prep.value?.strategy_stale" type="warning" :closable="false" title="资料有更新，建议重新生成" />
        <div v-if="c.prep.value?.strategy_status === 'running'" class="strategy-card"><p class="muted">正在读取授权范围内的记录、异常与待办…</p><el-skeleton :rows="8" animated /></div>
        <el-alert v-else-if="c.prep.value?.strategy_status === 'failed'" type="error" :closable="false" title="策略没生成出来">
          准备内容已保存，可以重试，或直接去沟通。<GlassButton variant="link" @click="c.generate">重试</GlassButton>
        </el-alert>
        <template v-if="c.strategy.value">
          <div v-if="c.strategy.value.mode === 'stop'" class="mode-banner stop"><strong>建议暂停营销联系</strong><p>{{ c.strategy.value.mode_notice || '客户已明确拒绝，请核对拒绝范围与未结事项。' }}</p></div>
          <div v-else-if="c.strategy.value.mode === 'handle_first'" class="mode-banner handle"><strong>先处理售后</strong><p>{{ c.strategy.value.mode_notice }}</p></div>
          <article class="strategy-card">
            <header><div class="strategy-tags"><el-tag size="small" effect="plain">{{ modeLabels[c.strategy.value.mode] }}</el-tag><span>v{{ c.strategy.value.template_version }} 规则 · {{ c.strategy.value.generated_at?.slice(0, 16).replace('T', ' ') }}</span></div><h2>{{ c.strategy.value.headline }}</h2><p>{{ c.strategy.value.why }}</p><div class="evidence"><el-tag v-for="ref in c.strategy.value.evidence_refs" :key="`${ref.id}-${ref.version}`" size="small" effect="plain">#{{ ref.id }} · v{{ ref.version }}</el-tag></div></header>
            <div class="strategy-content">
              <template v-if="c.strategy.value.mode !== 'stop'">
                <section v-if="c.strategy.value.opening"><h3>开场白 <GlassButton variant="link" @click="copy(c.strategy.value.opening)">复制</GlassButton></h3><p class="opening">{{ c.strategy.value.opening }}</p></section>
                <section v-if="c.strategy.value.key_questions.length"><h3>关键问题</h3><ol class="questions"><li v-for="(question, index) in c.strategy.value.key_questions" :key="index"><strong>{{ question.q }}</strong><p>{{ question.why }}</p></li></ol></section>
              </template>
              <template v-else><dl><dt>仍需处理</dt><dd>{{ c.strategy.value.prepare.join('；') || '核对未结售后和我方承诺' }}</dd><dt>记录要点</dt><dd>{{ c.strategy.value.next_step_hint || '拒绝范围、时间、原话或准确转述' }}</dd><dt>重新评估</dt><dd>{{ c.strategy.value.stop_conditions.join('；') || '客户主动联系，或限制解除时' }}</dd></dl></template>
              <div v-if="c.strategy.value.warnings?.length" class="warning-list"><p>以下内容请核实后再用：</p><mark v-for="(warning, index) in c.strategy.value.warnings" :key="index" :title="warning.reason">{{ warning.text }}（{{ warning.reason }}）</mark></div>
              <el-collapse><el-collapse-item title="渠道、时长、回复分支与停止条件">
                <dl><dt>目标</dt><dd>{{ c.strategy.value.goal || c.form.value.goal }}</dd><dt>最小回复</dt><dd>{{ c.strategy.value.minimal_reply || '未提供' }}</dd><dt>渠道</dt><dd>{{ c.strategy.value.channel.suggest || '未建议' }} {{ c.strategy.value.channel.reason }}</dd><dt>忙碌退出</dt><dd>{{ c.strategy.value.channel.busy_exit || '礼貌结束，按客户意愿另约' }}</dd><dt>时长</dt><dd>{{ rangeLabel(c.strategy.value.time_budget.prep_minutes) }} 准备 · {{ rangeLabel(c.strategy.value.time_budget.talk_minutes) }} 沟通（规划用）</dd><dt>准备</dt><dd>{{ c.strategy.value.prepare.join('；') || '无' }}</dd></dl>
                <el-table v-if="c.strategy.value.reply_branches.length" :data="c.strategy.value.reply_branches" border class="list-table" v-sticky-scrollbar><el-table-column prop="when" label="客户如果" min-width="130" /><el-table-column prop="do" label="怎么接" min-width="220" /></el-table>
                <dl><dt>停止</dt><dd>{{ c.strategy.value.stop_conditions.join('；') || '客户明确不想再谈或要求不再联系' }}</dd></dl>
              </el-collapse-item></el-collapse>
            </div>
            <footer class="feedback"><span>这份策略</span><GlassButton variant="link" @click="c.feedback('useful')">有用</GlassButton><GlassButton variant="link" @click="c.feedback('inaccurate')">不准</GlassButton><span class="spacer" /><span>还可重新生成 {{ c.remaining.value }} 次</span></footer>
          </article>
        </template>
      </section>
    </div>
    <template #footer><div class="prep-footer"><GlassButton v-if="c.step.value > 1" @click="c.back">上一步</GlassButton><span class="save-hint">{{ c.saving.value ? '正在保存…' : c.prep.value ? '草稿已自动保存' : '' }}</span><span class="spacer" /><GlassButton v-if="c.step.value === 3 && c.prep.value?.strategy_status !== 'running'" :disabled="!c.remaining.value" @click="c.generate">重新生成</GlassButton><GlassButton variant="primary" :loading="c.saving.value" :disabled="c.step.value === 3 && c.prep.value?.strategy_status === 'running'" @click="c.next">{{ c.step.value === 1 ? '下一步' : c.step.value === 2 ? '生成策略' : '沟通完了，记结果' }}</GlassButton></div></template>
  </el-drawer>
  <PrepHistoryDrawer ref="historyRef" @cloned="c.loadPrep" @record="c.recordPrep" />
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { msgError, msgSuccessText } from '@/utils/feedback'
import FollowupDynamicField from './FollowupDynamicField.vue'
import PrepHistoryDrawer from './PrepHistoryDrawer.vue'

const props = defineProps({ controller: { type: Object, required: true } })
const c = props.controller
const historyRef = ref(null), showAllScenes = ref(false)
const sceneHints = { T01: '只记触达事实', T02: '了解门店需求', T03: '报价后犹豫', T04: '确认订单要素', T05: '试戴、洗护反馈', T06: '先处理问题', T07: '视频、直播', T08: '补货、上批反馈', T09: '真实经营节点', T10: '正确结束' }
const modeLabels = { normal: '常规', handle_first: '先处理售后', stop: '已拒绝' }
const media = window.matchMedia('(max-width: 768px)'), isMobile = ref(media.matches)
const sync = event => { isMobile.value = event.matches }
onMounted(() => media.addEventListener('change', sync))
onBeforeUnmount(() => media.removeEventListener('change', sync))
const visibleTemplates = computed(() => {
  const rows = c.context.value?.templates || []
  if (!isMobile.value || showAllScenes.value) return rows
  const recommended = c.context.value?.recommendation?.code
  const common = new Set([recommended, 'T01', 'T03', 'T05', 'T06'])
  return rows.filter(row => common.has(row.code))
})
const rangeLabel = range => range?.length === 2 ? `${range[0]}–${range[1]} 分钟` : '未设置'
function isStale(fact) {
  if (!fact.observed_at || !c.context.value?.today) return false
  return (Date.parse(`${c.context.value.today}T00:00:00Z`) - Date.parse(`${fact.observed_at}T00:00:00Z`)) / 86400000 > 90
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); msgSuccessText('已复制开场白') }
  catch (e) { msgError('复制失败，请手动选择文字', e) }
}
function beforeClose(done) { c.close(); done() }
</script>

<style scoped>
.prep-body, .prep-section { display: flex; flex-direction: column; gap: 14px; }
.steps { display: flex; gap: 6px; }
.steps span { flex: 1; height: 4px; border-radius: 4px; background: var(--border-color); transition: background-color 180ms ease; }
.steps span.on { background: var(--color-primary); }
.step-label, .muted { margin: 0; color: var(--text-secondary); font-size: 12px; }
.recommend, .history-banner, .context-bar { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: var(--radius-md); background: var(--tag-gold-bg); }
.recommend p { margin: 3px 0 0; color: var(--text-secondary); }
.scene-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.scene-card { display: flex; flex-direction: column; gap: 4px; padding: 11px 12px; border: 1px solid var(--border-color); border-radius: var(--radius-md); background: var(--dash-glass-bg); text-align: left; cursor: pointer; transition: border-color 120ms ease, background-color 120ms ease, transform 140ms var(--ease-out-strong); }
.scene-card:active { transform: scale(.98); }
.scene-card[aria-pressed="true"] { border-color: var(--color-primary); background: var(--tag-gold-bg); }
.scene-card span { color: var(--text-secondary); font-size: 12px; }
.more-scenes { align-self: stretch; }
.history-banner { justify-content: space-between; background: var(--tag-neutral-bg); font-size: 12px; }
.context-bar { flex-wrap: wrap; background: var(--tag-neutral-bg); }
.context-bar :deep(button:last-child) { margin-left: auto; }
.section-title { margin: 0 0 8px; font-size: 14px; }
.section-title span { margin-left: 6px; color: var(--text-secondary); font-size: 12px; font-weight: 400; }
.fact-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px; }
.fact-row { padding: 10px; border: 1px solid var(--border-color); border-radius: var(--radius-sm); }
.fact-row.stale { border-style: dashed; }
.fact-meta { display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 6px; margin-top: 6px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.full { width: 100%; }
.mode-banner { padding: 12px 14px; border-radius: var(--radius-md); }
.mode-banner p { margin: 4px 0 0; }
.mode-banner.stop { color: var(--color-danger); background: var(--tag-danger-bg); }
.mode-banner.handle { color: var(--color-warning-text); background: var(--tag-warning-bg); }
.strategy-card { overflow: hidden; border: 1px solid var(--border-color); border-radius: var(--radius-md); }
.strategy-card > header { padding: 16px; border-bottom: 1px solid var(--border-color); background: var(--tag-gold-bg); }
.strategy-card > header h2 { margin: 8px 0; font-size: 17px; }
.strategy-card > header p { margin: 0; line-height: 1.6; }
.strategy-tags, .evidence { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; color: var(--text-secondary); font-size: 12px; }
.evidence { margin-top: 8px; }
.strategy-content { display: flex; flex-direction: column; gap: 14px; padding: 16px; }
.strategy-content h3 { display: flex; align-items: center; justify-content: space-between; margin: 0 0 6px; font-size: 14px; }
.opening { margin: 0; padding: 12px; border-radius: var(--radius-sm); background: var(--tag-neutral-bg); line-height: 1.7; }
.questions { display: flex; flex-direction: column; gap: 10px; margin: 0; padding-left: 22px; }
.questions p { margin: 3px 0 0; color: var(--text-secondary); font-size: 12px; }
.warning-list { display: flex; flex-direction: column; gap: 6px; padding: 10px; border-radius: var(--radius-sm); background: var(--tag-warning-bg); }
.warning-list p { margin: 0; color: var(--color-warning-text); font-size: 12px; }
.warning-list mark { padding: 2px 4px; color: var(--color-warning-text); background: var(--tag-warning-bg); box-shadow: inset 0 -2px 0 var(--color-warning); }
dl { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 7px 10px; margin: 0; }
dt { color: var(--text-secondary); } dd { margin: 0; }
.feedback { display: flex; align-items: center; gap: 6px; padding: 10px 14px; border-top: 1px solid var(--border-color); color: var(--text-secondary); font-size: 12px; }
.prep-footer { display: flex; align-items: center; gap: 8px; width: 100%; }
.spacer { flex: 1; }
.save-hint { color: var(--text-secondary); font-size: 12px; }
:deep(.prep-drawer) { transition: transform 240ms cubic-bezier(.32,.72,0,1), opacity 180ms ease-out; }
@media (max-width: 600px) { .scene-grid, .form-grid, .fact-meta { grid-template-columns: 1fr; } .prep-footer :deep(button) { min-height: 44px; } }
@media (prefers-reduced-motion: reduce) { :deep(.prep-drawer), .scene-card, .steps span { transition-property: opacity, background-color; } }
</style>
