<template>
  <button ref="trigger" v-any-permission="ANNOUNCEMENT_PERMISSIONS" type="button"
    class="announcement-bell" :class="{ 'has-unread': state.unreadCount > 0 }"
    :aria-label="label" :title="label" aria-haspopup="dialog" :aria-expanded="state.open"
    @click="controller.open()">
    <el-icon><Bell /></el-icon>
    <span v-if="state.unreadCount" class="unread-count" aria-hidden="true">{{ state.unreadCount > 99 ? '99+' : state.unreadCount }}</span>
    <span v-if="state.unreadCount" class="unread-glow" aria-hidden="true" />
  </button>
  <AnnouncementDialog v-if="state.open" :state="state" @close="close" @content-ready="contentReady"
    @select="controller.selectNotice" @filter="controller.changeFilter" @page="changePage"
    @reload="controller.loadList" @all-read="controller.markAllRead" @retry-read="controller.retryRead"
    @next="controller.nextUnread" @back="controller.back" />
</template>

<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onErrorCaptured, onMounted, reactive, ref, watch } from 'vue'
import { Bell } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { announcementInboxApi } from '@/api/announcement'
import { ANNOUNCEMENT_PERMISSIONS, createInboxController, initialInboxState } from './inboxState'

// Only download the rich-text renderer when the reader opens the inbox.
const AnnouncementDialog = defineAsyncComponent(() => import('./AnnouncementDialog.vue'))
const auth = useAuthStore()
const state = reactive(initialInboxState())
const trigger = ref(null)
let pendingRender = null, timer
const enabled = computed(() => !!auth.user && auth.hasAnyPermission(ANNOUNCEMENT_PERMISSIONS))
const label = computed(() => state.unreadCount ? `公告，${state.unreadCount} 条未读` : '公告，无未读公告')
const controller = createInboxController({ state, api: announcementInboxApi, afterRender: detail => {
  pendingRender?.resolve()
  return new Promise((resolve, reject) => { pendingRender = { id: detail.id, revision: detail.revision_id, resolve, reject } })
} })

function contentReady(detail) {
  if (pendingRender?.id !== detail.id || pendingRender.revision !== detail.revision_id) return
  pendingRender.resolve(); pendingRender = null
}

async function close() {
  controller.close()
  pendingRender?.resolve(); pendingRender = null
  await nextTick()
  trigger.value?.focus()
}

function changePage(page) { state.page = page; controller.loadList() }
function refresh() {
  if (enabled.value && document.visibilityState === 'visible') controller.refreshSummary()
}

watch(() => [auth.user?.id, enabled.value], () => {
  controller.reset(); pendingRender?.resolve(); pendingRender = null
  if (enabled.value) controller.refreshSummary()
}, { immediate: true })

onMounted(() => {
  timer = setInterval(refresh, 60000)
  window.addEventListener('focus', refresh)
  document.addEventListener('visibilitychange', refresh)
})
onBeforeUnmount(() => {
  clearInterval(timer); controller.reset(); pendingRender?.resolve()
  window.removeEventListener('focus', refresh)
  document.removeEventListener('visibilitychange', refresh)
})
onErrorCaptured(() => {
  if (!pendingRender) return
  console.warn('Announcement content could not be rendered')
  pendingRender.reject(new Error('Announcement rendering failed')); pendingRender = null
  return false
})
</script>

<style scoped>
.announcement-bell { position: relative; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; width: 38px; height: 38px; border: 1px solid transparent; border-radius: 10px; background: transparent; color: var(--text-secondary); cursor: pointer; }
.announcement-bell > .el-icon { font-size: 21px; position: relative; z-index: 1; }
.announcement-bell.has-unread { color: var(--button-primary-text); background: var(--button-primary-soft); }
.announcement-bell.has-unread::before { content: ''; position: absolute; inset: 1px; border-radius: inherit; background: radial-gradient(circle, var(--button-focus), transparent 72%); pointer-events: none; animation: announcement-halo 3.2s ease-in-out infinite; }
.unread-count { position: absolute; z-index: 2; right: -4px; top: -3px; min-width: 19px; height: 19px; padding: 0 4px; border: 2px solid var(--card-bg); border-radius: 10px; background: var(--button-danger); color: var(--button-surface); font-size: 10px; line-height: 15px; text-align: center; font-variant-numeric: tabular-nums; font-weight: 700; }
.unread-glow { position: absolute; left: 5px; bottom: 6px; width: 5px; height: 5px; border-radius: 50%; background: var(--button-primary); box-shadow: 0 0 7px var(--button-focus); animation: announcement-glow 3.2s ease-in-out infinite; }
.announcement-bell:focus-visible { outline: 2px solid var(--button-primary); outline-offset: 3px; }
@keyframes announcement-halo { 0%,100% { opacity: .25; transform: scale(.84); } 50% { opacity: .9; transform: scale(1.1); } }
@keyframes announcement-glow { 0%,100% { opacity: .4; } 50% { opacity: 1; } }
@media (hover: hover) and (pointer: fine) { .announcement-bell:hover { background: var(--button-primary-soft); color: var(--button-primary-text); } }
@media (pointer: coarse) { .announcement-bell { width: 44px; height: 44px; } }
@media (prefers-reduced-motion: reduce) { .announcement-bell.has-unread::before, .unread-glow { animation: none; } }
</style>
