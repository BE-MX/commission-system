<template>
  <aside class="conversation-sidebar lg-card is-static" aria-label="最近会话">
    <SidebarContent v-bind="contentProps" @new="emit('new')" @select="select" @more="emit('more')" />
  </aside>
  <Transition name="drawer">
    <div v-if="drawerOpen" class="drawer-shell" @click.self="emit('update:drawerOpen', false)">
      <div
        ref="drawerPanel"
        class="drawer-panel"
        role="dialog"
        aria-modal="true"
        aria-label="选择会话"
        tabindex="-1"
        @keydown="onDialogKeydown"
      >
        <button type="button" class="drawer-close" aria-label="关闭会话列表" @click="emit('update:drawerOpen', false)">
          <el-icon><Close /></el-icon>
        </button>
        <SidebarContent v-bind="contentProps" @new="emit('new')" @select="select" @more="emit('more')" />
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, ref, resolveDirective, watch, withDirectives } from 'vue'
import { ChatDotRound, Close, Plus } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { focusDialog, restoreDialogFocus, trapDialogFocus } from '../state'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  currentSessionId: { type: Number, default: null },
  activeJob: { type: Object, default: null },
  drawerOpen: { type: Boolean, default: false },
  hasMore: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['new', 'select', 'more', 'update:drawerOpen'])
const drawerPanel = ref(null)
let restoreTarget = null

const contentProps = computed(() => ({
  sessions: props.sessions,
  currentSessionId: props.currentSessionId,
  activeJob: props.activeJob,
  hasMore: props.hasMore,
  loading: props.loading,
}))

function select(sessionId) {
  emit('select', sessionId)
  emit('update:drawerOpen', false)
}

function onDialogKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('update:drawerOpen', false)
    return
  }
  trapDialogFocus(event, drawerPanel.value)
}

watch(() => props.drawerOpen, async (isOpen, wasOpen) => {
  if (isOpen) {
    restoreTarget = document.activeElement
    await nextTick()
    focusDialog(drawerPanel.value)
  } else if (wasOpen) {
    await nextTick()
    restoreDialogFocus(restoreTarget)
    restoreTarget = null
  }
})

const SidebarContent = defineComponent({
  props: {
    sessions: { type: Array, default: () => [] },
    currentSessionId: { type: Number, default: null },
    activeJob: { type: Object, default: null },
    hasMore: { type: Boolean, default: false },
    loading: { type: Boolean, default: false },
  },
  emits: ['new', 'select', 'more'],
  setup(innerProps, { emit: innerEmit }) {
    const permission = resolveDirective('permission')
    return () => {
      const newButton = h(GlassButton, {
        variant: 'primary', fullWidth: true, leftIcon: Plus,
        onClick: () => innerEmit('new'),
      }, () => '新对话')
      return h('div', { class: 'sidebar-content' }, [
      withDirectives(newButton, [[permission, 'design_image:write']]),
      h('div', { class: 'sidebar-label' }, '最近会话'),
      innerProps.sessions.length
        ? h('div', { class: 'session-list' }, innerProps.sessions.map(session => h('button', {
          type: 'button',
          class: ['session-item', { 'is-active': session.id === innerProps.currentSessionId }],
          onClick: () => innerEmit('select', session.id),
        }, [
          h(ChatDotRound, { class: 'session-icon' }),
          h('span', { class: 'session-title' }, session.title || '新对话'),
          innerProps.activeJob?.session_id === session.id
            ? h('span', { class: 'session-status', title: '正在生成' })
            : null,
        ])))
        : h('p', { class: 'empty-copy' }, '还没有会话，点击上方开始创作。'),
      innerProps.hasMore ? h('button', {
        type: 'button', class: 'more-button', disabled: innerProps.loading,
        onClick: () => innerEmit('more'),
      }, innerProps.loading ? '加载中…' : '加载更多') : null,
      ])
    }
  },
})
</script>

<style scoped>
.conversation-sidebar {
  width: 232px;
  min-width: 220px;
  height: 100%;
  overflow: hidden;
  border: 1px solid var(--dash-glass-border);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}
.sidebar-content { display: flex; height: 100%; min-height: 0; flex-direction: column; padding: 16px; }
.sidebar-label { margin: 22px 4px 10px; color: var(--text-muted); font-size: 12px; font-weight: 600; }
.session-list { min-height: 0; overflow-y: auto; }
.session-item {
  display: grid; width: 100%; grid-template-columns: 18px minmax(0, 1fr) 8px; align-items: center;
  gap: 8px; margin-bottom: 4px; padding: 10px; border: 0; border-radius: var(--radius-md, 8px);
  background: transparent; color: var(--text-secondary); cursor: pointer; text-align: left;
  transition: background-color 140ms cubic-bezier(0.23, 1, 0.32, 1), color 140ms cubic-bezier(0.23, 1, 0.32, 1);
}
.session-item.is-active { background: var(--color-primary-light); color: var(--text-primary); }
.session-icon { width: 16px; }
.session-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-status { width: 7px; height: 7px; border-radius: 50%; background: var(--color-primary); }
.empty-copy { margin: 12px 4px; color: var(--text-muted); font-size: 12px; line-height: 1.6; }
.more-button { margin-top: 8px; border: 0; background: transparent; color: var(--color-primary); cursor: pointer; }
.drawer-shell { position: fixed; z-index: 2100; inset: 0; background: color-mix(in srgb, var(--sidebar-glass-to) 45%, transparent); }
.drawer-panel { position: relative; width: min(86vw, 280px); height: 100%; background: var(--card-bg); box-shadow: var(--dash-glass-shadow); }
.drawer-close { position: absolute; z-index: 1; top: 8px; right: 8px; display: grid; width: 32px; height: 32px; place-items: center; border: 0; border-radius: 50%; background: var(--toolbar-bg); color: var(--text-secondary); cursor: pointer; }
.drawer-enter-active, .drawer-leave-active { transition: opacity 220ms cubic-bezier(0.23, 1, 0.32, 1); }
.drawer-enter-active .drawer-panel, .drawer-leave-active .drawer-panel { transition: transform 220ms cubic-bezier(0.23, 1, 0.32, 1); }
.drawer-enter-from, .drawer-leave-to { opacity: 0; }
.drawer-enter-from .drawer-panel, .drawer-leave-to .drawer-panel { transform: translateX(-16px); }
@media (hover: hover) and (pointer: fine) {
  .session-item:hover { background: var(--toolbar-bg); color: var(--text-primary); }
  .drawer-close:hover { color: var(--text-primary); }
}
@media (max-width: 900px) { .conversation-sidebar { display: none; } }
@media (min-width: 901px) { .drawer-shell { display: none; } }
@media (prefers-reduced-motion: reduce) {
  .session-item { transition: background-color 140ms linear, color 140ms linear; }
  .drawer-enter-active, .drawer-leave-active,
  .drawer-enter-active .drawer-panel, .drawer-leave-active .drawer-panel { transition: opacity 160ms linear; }
  .drawer-enter-from .drawer-panel, .drawer-leave-to .drawer-panel { transform: none; opacity: 0; }
}
</style>
