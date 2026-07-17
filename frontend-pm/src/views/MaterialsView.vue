<template>
  <div class="page">
    <header class="page-head rise">
      <div class="head-row">
        <div>
          <p class="page-eyebrow">MATERIALS</p>
          <h1 class="page-title">资料库</h1>
          <p class="page-sub">顾问清单 {{ summary.total }} 项 · 已备齐 {{ summary.done }} 项</p>
        </div>
        <button class="btn btn-primary" type="button" @click="drawerOpen = true">+ 新增资料</button>
      </div>

      <div class="toolbar">
        <div class="search-box">
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="m11 11 3.2 3.2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
          <input v-model.trim="filters.keyword" class="search-input" type="text" placeholder="搜索名称或说明…" />
        </div>
        <div class="seg">
          <button
            v-for="opt in [['', '全部'], ['required', '必须'], ['important', '重要'], ['optional', '锦上添花']]"
            :key="opt[0]"
            class="seg-btn"
            :class="{ active: filters.importance === opt[0] }"
            type="button"
            @click="filters.importance = opt[0]"
          >{{ opt[1] }}</button>
        </div>
        <select v-model="filters.phase" class="select select-inline">
          <option value="">全部 Phase</option>
          <option v-for="p in [1, 2, 3, 4]" :key="p" :value="p">Phase {{ p }}</option>
        </select>
        <select v-model="filters.status" class="select select-inline">
          <option value="">全部状态</option>
          <option v-for="(meta, s) in MATERIAL_STATUS" :key="s" :value="s">{{ meta.label }}</option>
        </select>
      </div>
    </header>

    <div v-if="loading" class="list-loading"><span class="spinner"></span></div>

    <template v-else>
      <section v-for="(group, gi) in grouped" :key="group.category" class="cat-group" :class="`rise rise-${Math.min(gi + 1, 5)}`">
        <header class="cat-head">
          <h2 class="cat-title">{{ group.category }}</h2>
          <span class="cat-count num">{{ doneIn(group) }}/{{ group.items.length }}</span>
        </header>
        <div class="rows">
          <article
            v-for="m in group.items"
            :key="m.id"
            class="row"
            tabindex="0"
            @click="goDetail(m.id)"
            @keydown.enter="goDetail(m.id)"
          >
            <span class="row-no mono">{{ m.list_no ? String(m.list_no).padStart(2, '0') : '—' }}</span>
            <div class="row-main">
              <div class="row-name">
                {{ m.name }}
                <span v-if="m.delivery_type === 'offline'" class="row-flag">线下交付</span>
                <span v-else-if="m.delivery_type === 'link'" class="row-flag link">外部链接</span>
              </div>
              <p v-if="m.description" class="row-desc">{{ m.description }}</p>
            </div>
            <div class="row-side">
              <StatusBadge :label="IMPORTANCE[m.importance].label" :tone="IMPORTANCE[m.importance].tone" dot />
              <StatusBadge :label="MATERIAL_STATUS[m.status]?.label || m.status" :tone="MATERIAL_STATUS[m.status]?.tone" />
            </div>
            <div class="row-meta">
              <span v-if="m.phase" class="mono">P{{ m.phase }}</span>
              <span v-else class="meta-none">—</span>
              <span v-if="m.current_version_no" class="mono row-ver">v{{ m.current_version_no }}</span>
              <span v-else class="meta-none">无版本</span>
            </div>
            <div class="row-updated">
              <template v-if="m.last_uploaded_by">
                <span>{{ nameOf(m.last_uploaded_by) }}</span>
                <time class="mono">{{ fmtTime(m.last_uploaded_at, false) }}</time>
              </template>
              <span v-else class="meta-none">尚未上传</span>
            </div>
            <svg class="row-chevron" viewBox="0 0 12 12" width="11" height="11" aria-hidden="true">
              <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </article>
        </div>
      </section>

      <EmptyState v-if="!grouped.length" title="没有匹配的资料" hint="调整筛选条件，或新增清单外条目" />
    </template>

    <MaterialDrawer v-model="drawerOpen" :members="members" @save="onCreate" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import EmptyState from '../components/EmptyState.vue'
import MaterialDrawer from '../components/MaterialDrawer.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { useMaterials } from '../composables/useMaterials.js'
import { fetchMembers } from '../api/index.js'
import { fmtTime, IMPORTANCE, MATERIAL_STATUS } from '../utils/labels.js'

const router = useRouter()
const { loading, filters, grouped, summary, create } = useMaterials()

const drawerOpen = ref(false)
const members = ref([])

onMounted(async () => {
  try {
    members.value = (await fetchMembers()) || []
  } catch { /* 拦截器已提示，成员列表缺失不阻断页面 */ }
})

const nameOf = (username) => members.value.find((m) => m.username === username)?.display_name || username
const doneIn = (group) => group.items.filter((m) => ['submitted', 'confirmed', 'not_required'].includes(m.status)).length

function goDetail(id) {
  router.push(`/materials/${id}`)
}
async function onCreate(payload) {
  await create(payload)
}
</script>

<style scoped>
.head-row { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; }
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 24px;
  flex-wrap: wrap;
}
.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid var(--hairline-strong);
  padding: 6px 2px;
  color: var(--ink-3);
  flex: 1;
  min-width: 200px;
  max-width: 320px;
  transition: border-color var(--dur-fast) var(--ease-out);
}
.search-box:focus-within { border-bottom-color: var(--ink); }
.search-input { border: none; outline: none; background: transparent; flex: 1; font-size: 13.5px; }
.search-input::placeholder { color: var(--ink-4); }

.seg {
  display: inline-flex;
  border: 1px solid var(--hairline-strong);
  border-radius: var(--radius);
  padding: 2px;
  background: var(--paper-raised);
}
.seg-btn {
  padding: 5px 12px;
  font-size: 12.5px;
  color: var(--ink-3);
  border-radius: 2px;
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.seg-btn.active { background: var(--ink); color: var(--paper); }
.select-inline { width: auto; min-width: 108px; padding: 6px 10px; font-size: 13px; }

.list-loading { display: flex; justify-content: center; padding: 100px 0; }

.cat-group { margin-bottom: 34px; }
.cat-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--ink);
  margin-bottom: 2px;
}
.cat-title { font-family: var(--font-serif); font-size: 17px; letter-spacing: 0.03em; }
.cat-count { font-size: 12px; color: var(--ink-3); }

.rows { display: flex; flex-direction: column; }
.row {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) auto 92px 132px 16px;
  align-items: center;
  gap: 14px;
  padding: 13px 10px;
  border-bottom: 1px solid var(--hairline);
  cursor: pointer;
  border-radius: var(--radius);
  transition: background var(--dur-fast) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
  .row:hover { background: var(--paper-sunken); }
  .row:hover .row-chevron { transform: translateX(3px); color: var(--cinnabar); }
}
.row:focus-visible { outline: 2px solid var(--cinnabar); outline-offset: -2px; }
.row-no { font-size: 12.5px; color: var(--ink-4); }
.row-main { min-width: 0; }
.row-name {
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}
.row-flag {
  font-size: 10.5px;
  letter-spacing: 0.06em;
  color: var(--cinnabar);
  border: 1px solid var(--cinnabar-line);
  border-radius: 2px;
  padding: 0 5px;
  line-height: 1.8;
}
.row-flag.link { color: var(--slate); border-color: var(--slate-line); }
.row-desc {
  margin-top: 2px;
  font-size: 12px;
  color: var(--ink-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.row-side { display: flex; gap: 6px; }
.row-meta {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
  color: var(--ink-3);
}
.row-ver { color: var(--cinnabar); font-weight: 600; }
.row-updated {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  font-size: 11.5px;
  color: var(--ink-3);
  line-height: 1.5;
}
.row-updated time { font-size: 11px; color: var(--ink-4); }
.meta-none { color: var(--ink-4); font-size: 12px; }
.row-chevron { color: var(--ink-4); transition: transform var(--dur-med) var(--ease-out), color var(--dur-med) var(--ease-out); }

@media (max-width: 900px) {
  .row { grid-template-columns: 32px minmax(0, 1fr) auto 16px; }
  .row-meta, .row-updated { display: none; }
}
</style>
