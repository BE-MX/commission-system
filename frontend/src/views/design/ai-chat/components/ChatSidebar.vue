<template>
  <aside class="chat-sidebar lg-card is-static" aria-label="方案对话会话">
    <SidebarContent />
  </aside>

  <el-drawer
    :model-value="drawerOpen"
    class="chat-session-drawer"
    direction="ltr"
    size="min(86vw, 320px)"
    :show-close="false"
    :with-header="false"
    :append-to-body="false"
    @update:model-value="emit('update:drawerOpen', $event)"
  >
    <SidebarContent />
  </el-drawer>
</template>

<script setup>
import { defineComponent, h } from 'vue'
import { ChatLineRound, Plus } from '@element-plus/icons-vue'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  currentSessionId: { type: Number, default: null },
  drawerOpen: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  canWrite: { type: Boolean, default: false },
})
const emit = defineEmits(['new', 'select', 'update:drawerOpen'])

function select(sessionId) {
  emit('select', sessionId)
  emit('update:drawerOpen', false)
}

const SidebarContent = defineComponent({
  name: 'AiChatSidebarContent',
  setup() {
    return () => h('div', { class: 'sidebar-content' }, [
      h('button', {
        type: 'button',
        class: 'new-chat-button',
        disabled: !props.canWrite,
        onClick: () => emit('new'),
      }, [h(Plus, { class: 'sidebar-icon' }), '新对话']),
      h('div', { class: 'session-heading' }, '最近会话'),
      props.loading
        ? h('div', { class: 'session-loading' }, '正在加载…')
        : props.sessions.length
          ? h('div', { class: 'session-list' }, props.sessions.map(session => h('button', {
            type: 'button',
            class: ['session-item', { 'is-active': session.id === props.currentSessionId }],
            'aria-current': session.id === props.currentSessionId ? 'page' : undefined,
            onClick: () => select(session.id),
          }, [
            h(ChatLineRound, { class: 'sidebar-icon' }),
            h('span', { class: 'session-title' }, session.title || '新对话'),
          ])))
          : h('p', { class: 'session-empty' }, '还没有会话。选择一个快捷任务，或直接输入你的问题。'),
    ])
  },
})
</script>

<style scoped>
.chat-sidebar {
  position: relative;
  z-index: 1;
  width: 236px;
  min-width: 220px;
  height: 100%;
  overflow: hidden;
  border: 1px solid var(--dash-glass-border);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-highlight), var(--dash-glass-shadow);
}

.sidebar-content {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  padding: 16px 14px;
}

.sidebar-content :deep(.new-chat-button),
.sidebar-content :deep(.session-item) {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 9px;
  border: 0;
  font-family: var(--font-display);
  cursor: pointer;
}

.sidebar-content :deep(.new-chat-button) {
  min-height: 40px;
  justify-content: center;
  border-radius: 11px;
  background: linear-gradient(135deg, var(--color-primary), var(--color-primary-hover));
  box-shadow: var(--card-shadow);
  color: var(--text-on-dark);
  font-size: 13px;
  font-weight: 700;
}

.sidebar-content :deep(.new-chat-button:disabled) { cursor: not-allowed; opacity: 0.5; }

.sidebar-content :deep(.session-heading) {
  margin: 22px 8px 8px;
  color: var(--text-muted-blue);
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.sidebar-content :deep(.session-list) {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  scrollbar-width: thin;
}

.sidebar-content :deep(.session-item) {
  min-height: 42px;
  margin-bottom: 3px;
  padding: 0 11px;
  border-radius: 10px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  text-align: left;
}

.sidebar-content :deep(.session-item.is-active) {
  background: var(--color-primary-light);
  box-shadow: inset 3px 0 0 var(--color-primary);
  color: var(--text-primary);
  font-weight: 700;
}

.sidebar-content :deep(.sidebar-icon) { width: 16px; height: 16px; flex: 0 0 16px; }
.sidebar-content :deep(.session-title) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sidebar-content :deep(.session-loading),
.sidebar-content :deep(.session-empty) { margin: 10px 8px; color: var(--text-muted); font-size: 12px; line-height: 1.6; }

:deep(.chat-session-drawer) { --el-transition-duration: 200ms; }
:deep(.chat-session-drawer .el-drawer__body) { padding: 0; }

.sidebar-content :deep(.new-chat-button:focus-visible),
.sidebar-content :deep(.session-item:focus-visible) {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

@media (hover: hover) and (pointer: fine) {
  .sidebar-content :deep(.new-chat-button:not(:disabled):hover) { box-shadow: var(--dash-glass-shadow-hover); }
  .sidebar-content :deep(.session-item:not(.is-active):hover) { background: var(--dash-glass-bg-strong); color: var(--text-primary); }
}

@media (max-width: 899px) {
  .chat-sidebar { display: none; }
}

@media (min-width: 900px) {
  :deep(.chat-session-drawer) { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  :deep(.chat-session-drawer) { --el-transition-duration: 1ms; }
}
</style>
