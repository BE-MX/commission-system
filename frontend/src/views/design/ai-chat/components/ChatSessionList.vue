<template>
  <div class="sidebar-content">
    <button type="button" class="new-chat-button" :disabled="!canWrite || busy" @click="emit('new')"><el-icon><Plus /></el-icon> 新对话</button>
    <div class="session-heading">最近对话</div>
    <ListPageStatus :error="error" :loading="loading" :has-data="sessions.length > 0" :paged="false" @retry="emit('retry')" />
    <div class="session-list">
      <div v-for="session in sessions" :key="session.id" class="session-row" :class="{ 'is-active': session.id === currentSessionId }">
        <button type="button" class="session-item" :disabled="busy" :aria-current="session.id === currentSessionId ? 'page' : undefined" :title="session.title" @click="emit('select', session.id)">
          <el-icon><ChatLineRound /></el-icon><span>{{ session.title || '新对话' }}</span>
        </button>
        <el-dropdown v-if="canWrite" trigger="click" :disabled="busy" @command="emit($event, session)">
          <button type="button" class="session-menu" :disabled="busy" :aria-label="`管理会话：${session.title}`"><el-icon><MoreFilled /></el-icon></button>
          <template #dropdown><el-dropdown-menu>
            <el-dropdown-item command="rename"><el-icon><EditPen /></el-icon>重命名</el-dropdown-item>
            <el-dropdown-item command="delete"><el-icon><Delete /></el-icon>删除会话</el-dropdown-item>
          </el-dropdown-menu></template>
        </el-dropdown>
      </div>
      <p v-if="hasLoaded && !loading && !error && !sessions.length" class="session-empty">你的对话会保存在这里。</p>
      <button v-if="hasMore" class="load-more" type="button" :disabled="loadingMore" @click="emit('more')">{{ loadingMore ? '加载中…' : '更早的对话' }}</button>
    </div>
  </div>
</template>
<script setup>
import { ChatLineRound, Plus, MoreFilled, EditPen, Delete } from '@element-plus/icons-vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
defineProps({ sessions: { type: Array, default: () => [] }, currentSessionId: { type: Number, default: null }, error: { type: String, default: '' }, hasLoaded: Boolean, loading: Boolean, canWrite: Boolean, busy: Boolean, hasMore: Boolean, loadingMore: Boolean })
const emit = defineEmits(['new', 'select', 'retry', 'rename', 'delete', 'more'])
</script>
<style scoped>
.sidebar-content { display: flex; height: 100%; min-height: 0; flex-direction: column; padding: 16px 12px; }
.new-chat-button { display: flex; justify-content: center; align-items: center; gap: 8px; min-height: 42px; flex-shrink: 0; border: 1px solid var(--border-color); border-radius: 10px; background: var(--dash-glass-bg-strong); color: var(--text-primary); cursor: pointer; font: inherit; font-weight: 600; }
.session-heading { padding: 24px 10px 10px; color: var(--text-secondary); font-size: 12px; }
.session-list { flex: 1; min-height: 0; overflow-y: auto; scrollbar-width: thin; }
.session-row { display: flex; align-items: center; min-height: 42px; border-radius: 8px; margin: 2px 0; }
.session-row.is-active { background: var(--color-primary-light); color: var(--color-primary-text); }
.session-item { display: flex; flex: 1; min-width: 0; align-items: center; gap: 9px; padding: 11px 8px; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; font: inherit; font-size: 13px; }
.session-item span:not(.el-icon) { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.session-item .el-icon { flex-shrink: 0; }
.session-menu { display: grid; width: 32px; height: 36px; place-items: center; border: 0; border-radius: 7px; background: transparent; color: var(--text-secondary); cursor: pointer; }
.session-empty { padding: 6px 10px; font-size: 12px; color: var(--text-secondary); line-height: 1.7; }
.load-more { width: 100%; min-height: 40px; border: 0; border-radius: 8px; background: transparent; color: var(--color-primary-text); cursor: pointer; font: inherit; font-size: 12px; }
button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }
button:disabled { opacity: .5; cursor: not-allowed; }
@media (hover: hover) and (pointer: fine) { .session-row:hover, .load-more:hover, .new-chat-button:hover { background: var(--color-primary-light); } }
</style>
