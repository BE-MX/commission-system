<template>
  <DetailDrawer :model-value="modelValue" :title="item?.title || '事项详情'" @update:model-value="$emit('update:modelValue', $event)">
    <el-skeleton v-if="loading && !item" :rows="6" animated />
    <div v-else-if="error"><el-alert type="error" :closable="false" title="详情加载失败" /><el-button @click="$emit('retry')">重试</el-button></div>
    <div v-else-if="item" class="devlog-drawer">
      <div class="devlog-drawer__tags">
        <StatusBadge :type="tagType(TYPE_META[item.type].tone)" effect="light" :label="TYPE_META[item.type].label" />
        <StatusBadge type="warning" :label="STATUS_LABELS[item.status]" />
        <StatusBadge v-if="item.unmerged_hotfix" type="danger" label="未回合 main" />
        <span class="devlog-drawer__meta">{{ item.module || '未归模块' }} · {{ AGENT_LABELS[item.agent] }}</span>
      </div>
      <section>
        <h3 class="devlog-drawer__h">进度</h3>
        <ol class="devlog-steps">
          <li v-for="event in item.events" :key="event.at + event.to_status" class="is-done">
            <span class="devlog-steps__dot" aria-hidden="true" />
            <span>{{ STATUS_LABELS[event.to_status] }}</span>
            <time>{{ event.at.replace('T', ' ') }}</time>
          </li>
        </ol>
        <p v-if="item.released_revision" class="devlog-drawer__note">
          发布版本 <code>{{ shortSha(item.released_revision) }}</code>（按代码内容比对）
        </p>
      </section>
      <section v-if="tags.length">
        <h3 class="devlog-drawer__h">上线前提</h3>
        <div class="devlog-drawer__tags"><StatusBadge v-for="tag in tags" :key="tag.text" :type="tagType(tag.tone)" :label="tag.text" /></div>
      </section>
      <section>
        <h3 class="devlog-drawer__h">证据</h3>
        <ul class="devlog-evidence">
          <li v-for="e in item.evidences" :key="e.kind + e.ref">
            <span class="devlog-evidence__kind">{{ EVIDENCE_LABELS[e.kind] }}</span>
            <code>{{ shortSha(e.ref) }}</code>
            <time>{{ e.at.replace('T', ' ') }}</time>
          </li>
        </ul>
      </section>
    </div>
  </DetailDrawer>
</template>

<script setup>
import { computed } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { AGENT_LABELS, STATUS_LABELS, TYPE_META, preconditionTags, shortSha } from './devlogPresentation.js'

const props = defineProps({ modelValue: Boolean, item: Object, loading: Boolean, error: [Object, String, null] })
defineEmits(['update:modelValue', 'retry'])
const EVIDENCE_LABELS = { branch: '分支', commit: 'commit', release: '发布', worktree: '未提交改动' }
const tags = computed(() => preconditionTags(props.item?.preconditions))
const tagType = tone => ({ gold: 'warning', info: 'primary', danger: 'danger', violet: 'info', neutral: 'info', warning: 'warning', success: 'success' }[tone] || 'info')
</script>

<style scoped>
.devlog-drawer { display: flex; flex-direction: column; gap: 18px; }
.devlog-drawer__tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.devlog-drawer__meta { font-size: 12px; color: var(--text-muted); }
.devlog-drawer__h { margin: 0 0 8px; font: 700 12px/1.4 Outfit, sans-serif; letter-spacing: 0.08em; color: var(--text-muted); }
.devlog-drawer__note { margin: 4px 0 0; font-size: 12px; color: var(--text-secondary); }
.devlog-steps { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 10px; }
.devlog-steps li { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto; gap: 10px; align-items: center; font-size: 13px; }
.devlog-steps__dot { width: 12px; height: 12px; border-radius: 50%; background: var(--tag-success-solid); }
.devlog-steps time, .devlog-evidence time { font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.devlog-evidence { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
.devlog-evidence li { display: flex; flex-wrap: wrap; overflow-wrap: anywhere; gap: 8px; align-items: center; padding: 7px 10px; border-radius: 8px; border: 1px solid var(--border-color); background: var(--toolbar-bg); font-size: 13px; }
.devlog-evidence__kind { width: 72px; flex: none; font-size: 12px; color: var(--text-muted); }
.devlog-evidence time { margin-left: auto; }
.devlog-evidence code { min-width: 0; overflow-wrap: anywhere; }
@media (max-width: 600px) { .devlog-steps li { grid-template-columns: 14px minmax(0, 1fr); } .devlog-steps time { grid-column: 2; } }
</style>
