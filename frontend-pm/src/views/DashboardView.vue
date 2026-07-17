<template>
  <div class="page">
    <header class="page-head rise">
      <p class="page-eyebrow">OVERVIEW · 阿里国际站智能体搭建</p>
      <h1 class="page-title">项目总览</h1>
      <p class="page-sub">打开 3 秒看懂「项目推进到哪了、材料备齐了多少」</p>
    </header>

    <div v-if="loading" class="dash-loading"><span class="spinner"></span></div>

    <template v-else-if="data">
      <!-- 风险提示条：逾期任务 + Phase 1 未齐的必须材料，自动置顶 -->
      <section v-if="hasRisks" class="risks rise rise-1" aria-label="风险提示">
        <div class="risks-head">
          <span class="risks-mark" aria-hidden="true">!</span>
          <h2 class="risks-title">需要盯一下</h2>
        </div>
        <ul class="risks-list">
          <li v-for="t in data.risks.overdue_tasks" :key="`ot-${t.id}`">
            任务「{{ t.title }}」已逾期（{{ t.due_date }}）<template v-if="t.assignee"> · {{ t.assignee }}</template>
          </li>
          <li v-for="g in data.risks.phase1_required_gaps" :key="`g-${g.id}`">
            Phase 1 必须材料「{{ g.name }}」尚未备齐——顾问说过不齐则核心链路跑不起来
          </li>
        </ul>
      </section>

      <!-- 项目脉搏 -->
      <section class="pulse rise rise-1">
        <div class="pulse-figures">
          <div class="figure">
            <div class="figure-value">
              <span class="num big">{{ pct(data.materials.required_rate) }}</span>
              <span class="figure-unit">%</span>
            </div>
            <div class="figure-label">必须材料备齐率</div>
            <div class="figure-sub">
              <span class="dot-cinnabar" aria-hidden="true"></span>
              必须项 {{ data.materials.required_done }}/{{ data.materials.required_total }}
              · 全部材料 {{ data.materials.done }}/{{ data.materials.total }}
            </div>
          </div>
          <div class="figure-divider" aria-hidden="true"></div>
          <div class="figure">
            <div class="figure-value">
              <span class="num big">{{ pct(data.tasks.rate) }}</span>
              <span class="figure-unit">%</span>
            </div>
            <div class="figure-label">任务完成率</div>
            <div class="figure-sub">
              {{ data.tasks.done }}/{{ data.tasks.total }} 已完成
              <template v-if="data.tasks.status_counts.blocked">
                · <span class="blocked-text">{{ data.tasks.status_counts.blocked }} 受阻</span>
              </template>
            </div>
          </div>
          <div class="figure-divider" aria-hidden="true"></div>
          <div class="figure figure-quiet">
            <div class="figure-value"><span class="num big">{{ data.tasks.status_counts.in_progress || 0 }}</span></div>
            <div class="figure-label">进行中任务</div>
            <div class="figure-sub">看板正在推进的工作</div>
          </div>
        </div>

        <!-- 顾问 Phase 分段进度 -->
        <div class="phases">
          <div
            v-for="p in data.phases"
            :key="p.phase"
            class="phase"
            role="button"
            tabindex="0"
            @click="goMaterials({ phase: p.phase })"
            @keydown.enter="goMaterials({ phase: p.phase })"
          >
            <div class="phase-head">
              <span class="phase-name mono">PHASE {{ p.phase }}</span>
              <span class="phase-count num">{{ p.done }}/{{ p.total }}</span>
            </div>
            <div class="phase-track">
              <div class="phase-fill" :style="{ transform: `scaleX(${p.total ? p.done / p.total : 0})` }"></div>
              <div class="phase-fill-required" :style="{ transform: `scaleX(${p.total ? p.required_done / p.total : 0})` }"></div>
            </div>
            <div class="phase-sub">
              <template v-if="p.required_total">必须 {{ p.required_done }}/{{ p.required_total }}</template>
              <template v-else>无必须项</template>
            </div>
          </div>
        </div>
      </section>

      <div class="dash-grid">
        <!-- 材料概况：按重要级 -->
        <section class="panel rise rise-2">
          <header class="panel-head">
            <h2 class="panel-title">材料概况</h2>
            <router-link to="/materials" class="panel-more">进入资料库 →</router-link>
          </header>
          <div class="imp-list">
            <button
              v-for="imp in ['required', 'important', 'optional']"
              :key="imp"
              class="imp-row"
              type="button"
              @click="goMaterials({ importance: imp })"
            >
              <span class="imp-label">
                <StatusBadge :label="IMPORTANCE[imp].label" :tone="IMPORTANCE[imp].tone" dot />
              </span>
              <span class="imp-frac num">{{ data.materials.by_importance[imp].done }}<em>/{{ data.materials.by_importance[imp].total }}</em></span>
              <span class="imp-bar" aria-hidden="true">
                <span
                  v-for="seg in statusSegments(data.materials.by_importance[imp].status_counts, data.materials.by_importance[imp].total)"
                  :key="seg.status"
                  class="imp-seg"
                  :class="`seg-${seg.status}`"
                  :style="{ width: seg.width }"
                ></span>
              </span>
            </button>
          </div>
          <p class="imp-hint">计入完成：已提交 / 顾问确认 / 无需提供</p>
        </section>

        <!-- 最新动态 -->
        <section class="panel rise rise-3">
          <header class="panel-head">
            <h2 class="panel-title">最新动态</h2>
            <router-link to="/activity" class="panel-more">全部动态 →</router-link>
          </header>
          <ul class="feed">
            <li v-for="log in data.recent" :key="log.id" class="feed-item">
              <div class="feed-line">
                <span class="feed-name">{{ log.display_name }}</span>
                <span class="feed-action">{{ log.action_label }}</span>
                <span v-if="log.action !== 'entry'" class="feed-object">{{ log.object_name }}</span>
                <time class="feed-time">{{ relTime(log.created_at) }}</time>
              </div>
              <p v-if="log.diff_hint" class="feed-diff">✦ AI：{{ log.diff_hint }}</p>
            </li>
            <li v-if="!data.recent.length" class="feed-empty">还没有动态——第一份材料上传后从这里开始</li>
          </ul>
        </section>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import StatusBadge from '../components/StatusBadge.vue'
import { useDashboard } from '../composables/useDashboard.js'
import { IMPORTANCE, relTime } from '../utils/labels.js'

const router = useRouter()
const { data, loading } = useDashboard()

const hasRisks = computed(() => {
  const r = data.value?.risks
  return r && (r.overdue_tasks.length > 0 || r.phase1_required_gaps.length > 0)
})

const pct = (rate) => Math.round((rate || 0) * 100)

function statusSegments(counts, total) {
  if (!total) return []
  const order = ['confirmed', 'submitted', 'preparing', 'not_required', 'not_started']
  return order
    .filter((s) => counts?.[s])
    .map((status) => ({ status, width: `${(counts[status] / total) * 100}%` }))
}

function goMaterials(query) {
  router.push({ path: '/materials', query })
}
</script>

<style scoped>
.dash-loading { display: flex; justify-content: center; padding: 120px 0; }

/* ── 风险提示条 ─────────────────────────── */
.risks {
  border: 1px solid var(--cinnabar-line);
  border-left: 3px solid var(--cinnabar);
  background: var(--cinnabar-wash);
  border-radius: var(--radius);
  padding: 16px 20px;
  margin-bottom: 24px;
}
.risks-head { display: flex; align-items: center; gap: 9px; margin-bottom: 8px; }
.risks-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 17px;
  height: 17px;
  border-radius: 50%;
  background: var(--cinnabar);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
}
.risks-title { font-family: var(--font-serif); font-size: 15px; color: var(--cinnabar-deep); }
.risks-list { margin: 0; padding-left: 26px; font-size: 13px; color: var(--cinnabar-deep); }
.risks-list li { margin: 3px 0; }

/* ── 项目脉搏 ─────────────────────────── */
.pulse {
  border: 1px solid var(--hairline-strong);
  background: var(--paper-raised);
  border-radius: var(--radius-lg);
  padding: 30px 32px 26px;
  margin-bottom: 24px;
}
.pulse-figures {
  display: flex;
  align-items: stretch;
  gap: 36px;
  padding-bottom: 26px;
  border-bottom: 1px solid var(--hairline);
}
.figure { flex: 1; }
.figure-quiet .figure-value { color: var(--ink-3); }
.figure-value { display: flex; align-items: baseline; gap: 4px; }
.num.big {
  font-size: 52px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: -0.03em;
}
.figure-unit { font-size: 18px; color: var(--ink-3); }
.figure-label {
  margin-top: 10px;
  font-size: 13px;
  color: var(--ink-2);
  letter-spacing: 0.04em;
}
.figure-sub {
  margin-top: 5px;
  font-size: 12px;
  color: var(--ink-3);
  display: flex;
  align-items: center;
  gap: 6px;
}
.figure-divider { width: 1px; background: var(--hairline); }
.dot-cinnabar { width: 6px; height: 6px; border-radius: 50%; background: var(--cinnabar); }
.blocked-text { color: var(--cinnabar); }

.phases {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 28px;
  padding-top: 22px;
}
.phase { cursor: pointer; padding: 2px 0; }
.phase-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
.phase-name { font-size: 11px; letter-spacing: 0.14em; color: var(--ink-3); }
.phase-count { font-size: 12.5px; color: var(--ink-2); }
.phase-track {
  position: relative;
  height: 3px;
  background: var(--paper-sunken);
  border-radius: 2px;
  overflow: hidden;
}
.phase-fill,
.phase-fill-required {
  position: absolute;
  inset: 0;
  transform-origin: left;
  border-radius: 2px;
}
.phase-fill {
  background: var(--ink);
  transition: transform 600ms var(--ease-out);
}
.phase-fill-required {
  background: var(--cinnabar);
  transition: transform 600ms var(--ease-out) 80ms;
}
.phase-sub { margin-top: 7px; font-size: 11.5px; color: var(--ink-4); }
@media (hover: hover) and (pointer: fine) {
  .phase:hover .phase-name { color: var(--cinnabar); }
}
.phase { transition: transform var(--dur-fast) var(--ease-out); }
.phase:active { transform: scale(0.98); }

/* ── 下半区双栏 ─────────────────────────── */
.dash-grid {
  display: grid;
  grid-template-columns: 7fr 5fr;
  gap: 24px;
}
.panel {
  border: 1px solid var(--hairline-strong);
  background: var(--paper-raised);
  border-radius: var(--radius-lg);
  padding: 24px 26px;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 18px;
}
.panel-title { font-family: var(--font-serif); font-size: 17px; }
.panel-more {
  font-size: 12px;
  color: var(--ink-3);
  transition: color var(--dur-fast) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
  .panel-more:hover { color: var(--cinnabar); }
}

.imp-list { display: flex; flex-direction: column; gap: 4px; }
.imp-row {
  display: grid;
  grid-template-columns: 108px 74px 1fr;
  align-items: center;
  gap: 14px;
  padding: 10px 8px;
  border-radius: var(--radius);
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}
.imp-row:active { transform: scale(0.99); }
@media (hover: hover) and (pointer: fine) {
  .imp-row:hover { background: var(--paper-sunken); }
}
.imp-frac { font-size: 17px; color: var(--ink); }
.imp-frac em { font-style: normal; font-size: 12px; color: var(--ink-4); }
.imp-bar {
  display: flex;
  height: 5px;
  border-radius: 3px;
  overflow: hidden;
  background: var(--paper-sunken);
}
.imp-seg { display: block; }
.seg-confirmed { background: var(--sage); }
.seg-submitted { background: var(--amber); }
.seg-preparing { background: var(--slate); }
.seg-not_required { background: var(--ink-4); }
.seg-not_started { background: var(--hairline-strong); }
.imp-hint { margin-top: 14px; font-size: 11.5px; color: var(--ink-4); }

.feed { list-style: none; margin: 0; padding: 0; }
.feed-item {
  padding: 9px 0;
  border-bottom: 1px dashed var(--hairline);
}
.feed-item:last-child { border-bottom: none; }
.feed-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 13px;
  flex-wrap: wrap;
}
.feed-name { font-weight: 600; }
.feed-action { color: var(--ink-3); }
.feed-object { color: var(--ink); }
.feed-time { margin-left: auto; font-size: 11.5px; color: var(--ink-4); }
.feed-diff {
  margin-top: 4px;
  font-family: var(--font-serif);
  font-size: 12.5px;
  color: var(--cinnabar);
  padding-left: 2px;
}
.feed-empty { color: var(--ink-4); font-size: 13px; padding: 24px 0; text-align: center; }

@media (max-width: 900px) {
  .pulse-figures { flex-direction: column; gap: 22px; }
  .figure-divider { display: none; }
  .phases { grid-template-columns: repeat(2, 1fr); }
  .dash-grid { grid-template-columns: 1fr; }
}
</style>
