<template>
  <aside class="chat-sidebar" aria-label="聊天会话"><ChatSessionList v-bind="listProps" v-on="events" /></aside>
  <DetailDrawer :model-value="drawerOpen" title="我的对话" direction="ltr" width="320px" append-to-body @update:model-value="emit('update:drawerOpen', $event)">
    <ChatSessionList v-bind="listProps" v-on="events" />
  </DetailDrawer>
</template>
<script setup>
import { computed } from 'vue'
import ChatSessionList from './ChatSessionList.vue'
const props = defineProps({ sessions: { type: Array, default: () => [] }, currentSessionId: { type: Number, default: null }, drawerOpen: Boolean, error: { type: String, default: '' }, hasLoaded: Boolean, loading: Boolean, canWrite: Boolean, busy: Boolean, hasMore: Boolean, loadingMore: Boolean })
const emit = defineEmits(['new', 'select', 'retry', 'rename', 'delete', 'more', 'update:drawerOpen'])
const listProps = computed(() => ({ ...props }))
const events = Object.fromEntries(['new', 'select', 'retry', 'rename', 'delete', 'more'].map(event => [event, value => {
  emit(event, value)
  if (event === 'select' || event === 'new') emit('update:drawerOpen', false)
}]))
</script>
<style scoped>
.chat-sidebar { position: relative; z-index: 1; width: 244px; flex: 0 0 244px; height: 100%; min-height: 0; overflow: hidden; border-right: 1px solid var(--border-color); background: var(--dash-glass-bg); border-radius: 12px 0 0 12px; }
@media (max-width: 900px) { .chat-sidebar { display: none; } }
</style>
