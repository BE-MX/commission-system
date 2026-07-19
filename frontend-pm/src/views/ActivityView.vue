<template>
  <div class="page">
    <header class="page-head rise">
      <p class="page-eyebrow">ACTIVITY</p>
      <h1 class="page-title">全站动态</h1>
      <p class="page-sub">谁、何时、做了什么——出了问题能追，平时当项目日报看</p>
      <div class="toolbar">
        <select v-model="filters.username" class="select select-inline" @change="load()">
          <option value="">全部成员</option>
          <option v-for="m in members" :key="m.username" :value="m.username">{{ m.display_name }}</option>
        </select>
        <select v-model="filters.object_type" class="select select-inline" @change="load()">
          <option value="">全部对象</option>
          <option value="material">资料</option>
          <option value="version">版本</option>
          <option value="task">任务</option>
          <option value="comment">评论</option>
          <option value="member">成员</option>
        </select>
        <span class="total-hint num">共 {{ total }} 条</span>
      </div>
    </header>

    <div v-if="loading && !items.length" class="feed-loading"><span class="spinner"></span></div>

    <template v-else>
      <div v-for="group in byDay" :key="group.day" class="day-group rise">
        <h2 class="day-title mono">{{ group.day }}</h2>
        <ul class="day-list">
          <li v-for="log in group.items" :key="log.id" class="act-item">
            <time class="act-time mono">{{ log.created_at?.slice(11, 16) }}</time>
            <span class="act-dot" :class="`tone-bg-${dotTone(log)}`" aria-hidden="true"></span>
            <div class="act-body">
              <span class="act-line">
                <strong>{{ log.display_name }}</strong>
                <span class="act-action">{{ log.action_label }}</span>
                <span v-if="log.action !== 'entry'" class="act-object">{{ log.object_name }}</span>
              </span>
              <p v-if="log.diff_hint" class="act-diff">✦ AI：{{ log.diff_hint }}</p>
              <p v-else-if="detailText(log)" class="act-detail">{{ detailText(log) }}</p>
            </div>
          </li>
        </ul>
      </div>

      <EmptyState v-if="!items.length" title="还没有动态" hint="第一份材料上传后从这里开始" />

      <div v-if="hasMore()" class="more">
        <button class="btn" type="button" :disabled="loading" @click="load(true)">
          <span v-if="loading" class="spinner"></span>加载更早的动态
        </button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import { useActivity } from '../composables/useActivity.js'

const { items, total, loading, filters, members, load, hasMore } = useActivity()

const byDay = computed(() => {
  const groups = []
  const map = new Map()
  for (const log of items.value) {
    const day = log.created_at?.slice(0, 10) || '未知日期'
    if (!map.has(day)) {
      const g = { day, items: [] }
      map.set(day, g)
      groups.push(g)
    }
    map.get(day).items.push(log)
  }
  return groups
})

const OBJECT_TONE = { version: 'gold', material: 'slate', task: 'ink', member: 'muted', comment: 'sage' }
const dotTone = (log) => OBJECT_TONE[log.object_type] || 'muted'

function detailText(log) {
  const d = log.detail
  if (!d) return ''
  if (d.change_note) return `「${d.change_note}」`
  const parts = []
  for (const [k, v] of Object.entries(d)) {
    if (v && typeof v === 'object' && ('from' in v || 'to' in v)) {
      const label = { status: '状态', assignee: '负责人', title: '标题', due_date: '截止', phase: 'Phase', name: '名称' }[k] || k
      parts.push(`${label}: ${v.from ?? '—'} → ${v.to ?? '—'}`)
    }
  }
  return parts.join(' · ')
}
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 22px;
}
.select-inline { width: auto; min-width: 120px; padding: 6px 10px; font-size: 13px; }
.total-hint { font-size: 12px; color: var(--ink-4); margin-left: auto; }

.feed-loading { display: flex; justify-content: center; padding: 100px 0; }

.day-group { margin-bottom: 28px; }
.day-title {
  font-size: 12px;
  letter-spacing: 0.12em;
  color: var(--ink-3);
  font-weight: 500;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--ink);
  margin-bottom: 4px;
}
.day-list { list-style: none; margin: 0; padding: 0; }
.act-item {
  display: grid;
  grid-template-columns: 52px 14px 1fr;
  gap: 8px;
  align-items: start;
  padding: 10px 0;
  border-bottom: 1px dashed var(--hairline);
}
.act-item:last-child { border-bottom: none; }
.act-time { font-size: 12px; color: var(--ink-4); padding-top: 2px; }
.act-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-top: 7px;
}
.tone-bg-gold { background: var(--gold-strong); }
.tone-bg-ink { background: var(--ink); }
.tone-bg-amber { background: var(--amber); }
.tone-bg-sage { background: var(--sage); }
.tone-bg-slate { background: var(--slate); }
.tone-bg-muted { background: var(--ink-4); }
.act-line { font-size: 13.5px; display: flex; gap: 6px; flex-wrap: wrap; align-items: baseline; }
.act-action { color: var(--ink-3); }
.act-object { color: var(--ink); }
.act-diff {
  margin-top: 4px;
  font-family: var(--font-serif);
  font-size: 12.5px;
  color: var(--gold-deep);
}
.act-detail { margin-top: 3px; font-size: 12px; color: var(--ink-3); }

.more { display: flex; justify-content: center; padding: 26px 0 8px; }
</style>
