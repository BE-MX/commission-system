<template>
  <el-dialog :model-value="state.open" class="announcement-inbox-dialog" align-center
    append-to-body :show-close="false" aria-label="平台公告" @close="$emit('close')">
    <template #header>
      <div class="inbox-header">
        <span class="inbox-icon"><el-icon><Bell /></el-icon></span>
        <div class="inbox-heading"><h2>平台公告</h2><p>共 {{ state.announcementCount }} 条公告 · {{ state.unreadCount ? `${state.unreadCount} 条未读` : '暂无未读' }}</p></div>
        <button type="button" class="all-read" :disabled="!state.unreadCount || state.markingAll || state.listLoading"
          @click="$emit('all-read')"><el-icon><Check /></el-icon>{{ state.markingAll ? '更新中…' : '全部已读' }}</button>
        <button type="button" class="inbox-close" aria-label="关闭公告" @click="$emit('close')"><el-icon><Close /></el-icon></button>
      </div>
    </template>
    <div class="inbox-body" :class="{ 'has-detail': state.detail || state.detailLoading || state.detailError }">
      <section class="notice-list-panel" aria-label="公告列表">
        <div class="inbox-filters">
          <button type="button" :class="{ selected: state.filter === 'all' }" :aria-pressed="state.filter === 'all'" @click="$emit('filter', 'all')">全部 <span>{{ state.announcementCount }}</span></button>
          <button type="button" :class="{ selected: state.filter === 'unread' }" :aria-pressed="state.filter === 'unread'" @click="$emit('filter', 'unread')">未读 <span>{{ state.unreadCount }}</span></button>
        </div>
        <div v-loading="state.listLoading" class="notice-list" :aria-busy="state.listLoading">
          <div v-if="state.listError" class="inbox-empty" role="alert"><el-icon><Warning /></el-icon><p>{{ state.listError }}</p><GlassButton @click="$emit('reload')">重试</GlassButton></div>
          <template v-else>
            <button v-for="item in state.items" :key="`${item.id}:${item.revision_id}`" type="button" class="notice-row"
              :class="{ read: item.is_read, selected: state.detail?.id === item.id }"
              :aria-current="state.detail?.id === item.id ? 'true' : undefined" @click="$emit('select', item.id)">
              <span class="notice-title"><span class="notice-dot" :class="{ read: item.is_read }" aria-hidden="true" />{{ item.title }}</span>
              <span class="notice-meta"><time>{{ formatBeijingShortDateTime(item.published_at) }}</time><span :class="{ unread: !item.is_read }">{{ item.is_read ? '已读' : '未读' }}</span></span>
            </button>
            <div v-if="!state.listLoading && !state.items.length" class="inbox-empty"><el-icon><component :is="state.filter === 'unread' ? CircleCheck : MessageBox" /></el-icon><p>{{ state.filter === 'unread' ? '所有公告都已读' : '还没有公告' }}</p></div>
          </template>
        </div>
        <nav v-if="state.total > state.pageSize" class="inbox-pages" aria-label="公告分页">
          <button type="button" :disabled="state.page <= 1 || state.listLoading" @click="$emit('page', state.page - 1)">上一页</button>
          <span>{{ state.page }} / {{ Math.ceil(state.total / state.pageSize) }}</span>
          <button type="button" :disabled="state.page * state.pageSize >= state.total || state.listLoading" @click="$emit('page', state.page + 1)">下一页</button>
        </nav>
        <div class="inbox-list-note"><el-icon><InfoFilled /></el-icon>打开公告详情后自动标记已读</div>
      </section>
      <section v-loading="state.detailLoading" class="notice-detail-panel" aria-label="公告详情" :aria-busy="state.detailLoading">
        <button type="button" class="inbox-back" @click="$emit('back')"><el-icon><ArrowLeft /></el-icon>返回公告列表</button>
        <div v-if="state.detailError" class="inbox-empty" role="alert"><el-icon><Warning /></el-icon><p>{{ state.detailError }}</p><GlassButton @click="$emit('back')">返回公告列表</GlassButton></div>
        <template v-else-if="state.detail">
          <div class="detail-kicker"><span class="notice-category">{{ state.detail.category_name }}</span><span class="detail-read-state" :class="{ success: state.detail.is_read }"><el-icon v-if="state.detail.is_read"><Check /></el-icon>{{ state.detail.is_read ? '已读' : state.readSaving ? '更新已读状态…' : '未读' }}</span></div>
          <h3 class="detail-title">{{ state.detail.title }}</h3>
          <div class="detail-meta"><el-icon><Clock /></el-icon><time>{{ formatBeijingDateTime(state.detail.published_at, { seconds: false }) }}</time><span>·</span><span>平台公告</span></div>
          <KnowledgeDocumentPreview :key="`${state.detail.id}:${state.detail.revision_id}`" ref="contentPreview" :content="state.detail.content_json" class="notice-content" />
          <div class="notice-signature">莱莎方舟 · 平台公告</div>
        </template>
        <div v-else-if="!state.detailLoading" class="detail-placeholder"><span><el-icon><component :is="!state.announcementCount ? MessageBox : state.unreadCount ? Document : CircleCheck" /></el-icon></span><h3>{{ !state.announcementCount ? '暂无公告' : state.unreadCount ? '选择一条公告，查看详情' : '所有公告都已读' }}</h3><p>{{ !state.announcementCount ? '新公告发布后，会在这里显示。' : state.unreadCount ? '重要更新和通知，都在这里。' : '没有遗漏的重要通知，可随时查阅历史公告。' }}</p></div>
      </section>
    </div>
    <template #footer>
      <div class="inbox-footer">
        <div class="inbox-feedback" :class="{ success: !state.readError && state.status }" role="status" aria-live="polite">
          <el-icon><component :is="state.readError ? Warning : state.status ? CircleCheck : InfoFilled" /></el-icon>
          <span>{{ state.readError || state.status || '公告阅读状态会自动更新' }}</span>
          <button v-if="state.readError && state.detail" type="button" class="retry-read" :disabled="state.readSaving" @click="$emit('retry-read')">重试</button>
        </div>
        <GlassButton v-if="state.unreadCount" variant="primary" :right-icon="ArrowRight"
          :disabled="state.detailLoading || state.readSaving || state.markingAll" @click="$emit('next')">查看下一条未读</GlassButton>
        <GlassButton v-else @click="$emit('close')">完成</GlassButton>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, Bell, Check, CircleCheck, Clock, Close, Document, InfoFilled, MessageBox, Warning } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import KnowledgeDocumentPreview from '@/views/knowledge/components/KnowledgeDocumentPreview.vue'
import { formatBeijingDateTime, formatBeijingShortDateTime } from '@/utils/datetime'

const props = defineProps({ state: { type: Object, required: true } })
const emit = defineEmits(['close', 'content-ready', 'select', 'filter', 'page', 'reload', 'all-read', 'retry-read', 'next', 'back'])
const contentPreview = ref(null)
watch(() => props.state.detail, async detail => {
  if (!detail) return
  await nextTick()
  if (props.state.detail === detail && contentPreview.value) emit('content-ready', detail)
}, { immediate: true, flush: 'post' })
</script>

<style scoped>
.inbox-header { display: flex; align-items: center; gap: 12px; padding: 20px 24px; }
.inbox-icon { display: grid; place-items: center; width: 43px; height: 43px; border-radius: 12px; background: var(--button-primary-soft); color: var(--button-primary-text); flex-shrink: 0; }
.inbox-icon .el-icon { font-size: 21px; }
.inbox-heading { flex: 1; min-width: 0; }
.inbox-heading h2 { margin: 0; font-size: 19px; font-family: var(--font-display); color: var(--text-primary); }
.inbox-heading p { margin: 3px 0 0; font-size: 12px; color: var(--text-muted); }
.all-read, .inbox-close, .inbox-back, .retry-read { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 0; background: transparent; color: var(--text-secondary); font: inherit; cursor: pointer; }
.all-read { padding: 8px; font-size: 12px; white-space: nowrap; }
.all-read:disabled { color: var(--button-disabled-text); cursor: default; }
.inbox-close { width: 32px; height: 32px; border-radius: 7px; flex-shrink: 0; }
.inbox-body { display: grid; grid-template-columns: 300px minmax(0,1fr); min-height: 0; height: min(560px, calc(100dvh - 200px)); }
.notice-list-panel { display: flex; flex-direction: column; min-width: 0; min-height: 0; border-right: 1px solid var(--border-color); background: var(--toolbar-bg); }
.inbox-filters { display: flex; gap: 5px; padding: 17px 18px 13px; border-bottom: 1px solid var(--border-color); }
.inbox-filters button { background: transparent; border: 0; border-radius: 7px; color: var(--text-muted); padding: 7px 11px; font: inherit; font-size: 12px; cursor: pointer; }
.inbox-filters button.selected { color: var(--button-primary-text); background: var(--button-primary-soft); font-weight: 700; }
.inbox-filters span { font-size: 11px; margin-left: 5px; font-variant-numeric: tabular-nums; }
.notice-list { overflow-y: auto; flex: 1; min-height: 0; }
.notice-row { display: block; position: relative; width: 100%; text-align: left; padding: 16px 19px; background: transparent; border: 0; border-bottom: 1px solid var(--border-color); color: var(--text-primary); font: inherit; cursor: pointer; }
.notice-row.selected { background: var(--button-primary-soft); }
.notice-row.selected::before { content: ''; position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px; border-radius: 2px; background: var(--button-primary); }
.notice-title { display: flex; align-items: flex-start; gap: 9px; font-size: 13px; font-weight: 700; line-height: 1.65; overflow-wrap: anywhere; }
.notice-row.read .notice-title { font-weight: 400; }
.notice-dot { width: 6px; height: 6px; margin-top: 8px; flex-shrink: 0; border-radius: 50%; background: var(--button-danger); }
.notice-dot.read { border: 1px solid var(--text-muted); background: transparent; }
.notice-meta { display: flex; justify-content: space-between; gap: 12px; margin-top: 7px; padding-left: 15px; font-size: 11px; color: var(--text-muted); }
.notice-meta .unread { color: var(--button-danger-text); }
.inbox-list-note { display: flex; align-items: center; gap: 6px; border-top: 1px solid var(--border-color); font-size: 11px; color: var(--text-muted); padding: 14px 16px; }
.inbox-pages { display: flex; padding: 6px 12px; justify-content: space-between; align-items: center; color: var(--text-muted); font-size: 12px; }
.inbox-pages button { border: 0; background: transparent; color: var(--button-primary-text); min-height: 44px; font: inherit; cursor: pointer; }
.inbox-pages button:disabled { color: var(--button-disabled-text); cursor: default; }
.notice-detail-panel { overflow-y: auto; padding: 28px 32px; min-width: 0; min-height: 0; }
.detail-kicker { display: flex; align-items: center; gap: 9px; font-size: 11px; margin-bottom: 15px; }
.notice-category { padding: 4px 8px; border-radius: 5px; background: var(--button-primary-soft); color: var(--button-primary-text); }
.detail-read-state { display: flex; align-items: center; gap: 4px; color: var(--text-muted); }
.detail-read-state.success { color: var(--button-success-text); }
.detail-title { margin: 0; color: var(--text-primary); font-size: 22px; line-height: 1.5; overflow-wrap: anywhere; }
.detail-meta { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-top: 13px; padding-bottom: 20px; border-bottom: 1px solid var(--border-color); color: var(--text-muted); font-size: 11px; }
.notice-content { padding: 21px 0 0; border: 0; border-radius: 0; background: transparent; max-height: none; overflow: visible; }
.notice-content :deep(.tiptap) { color: var(--text-secondary); font-size: 14px; line-height: 1.9; }
.notice-content :deep(.tiptap > :first-child) { margin-top: 0; }
.notice-content :deep(.tiptap) { overflow-wrap: anywhere; }
.notice-signature { color: var(--text-muted); font-size: 11px; margin-top: 23px; }
.detail-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 340px; text-align: center; color: var(--text-muted); }
.detail-placeholder > span { display: grid; place-items: center; width: 68px; height: 68px; border: 1px solid var(--border-color); border-radius: 20px; background: var(--toolbar-bg); color: var(--button-primary-text); margin-bottom: 18px; }
.detail-placeholder .el-icon { font-size: 28px; }
.detail-placeholder h3 { margin: 0 0 8px; font-size: 17px; color: var(--text-primary); }
.detail-placeholder p { margin: 0; font-size: 12px; line-height: 1.8; }
.inbox-empty { text-align: center; color: var(--text-muted); font-size: 12px; padding: 60px 18px; overflow-wrap: anywhere; }
.inbox-empty > .el-icon { font-size: 28px; }
.inbox-footer { display: flex; align-items: center; gap: 12px; padding: 16px 24px; background: var(--toolbar-bg); }
.inbox-feedback { flex: 1; display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-muted); text-align: left; }
.inbox-feedback.success { color: var(--button-success-text); }
.retry-read { color: var(--button-primary-text); text-decoration: underline; white-space: nowrap; font-size: 12px; }
.inbox-back { display: none; }
button:focus-visible { outline: 2px solid var(--button-primary); outline-offset: -3px; }
@media (hover: hover) and (pointer: fine) { .notice-row:hover, .inbox-close:hover { background: var(--button-primary-soft); } }
@media (max-width: 760px) { .inbox-body { grid-template-columns: 260px minmax(0,1fr); } .notice-detail-panel { padding: 24px; } }
@media (max-width: 640px) {
  .inbox-header { padding: 17px 15px; gap: 7px; } .inbox-icon { width: 35px; height: 35px; border-radius: 9px; }
  .inbox-heading h2 { font-size: 17px; } .inbox-heading p { font-size: 11px; } .all-read { padding: 7px 4px; font-size: 11px; }
  .inbox-body { display: block; min-height: 0; height: min(520px, calc(100dvh - 240px)); }
  .notice-list-panel { height: 100%; border: 0; } .notice-detail-panel { display: none; height: 100%; padding: 21px; }
  .inbox-body.has-detail .notice-list-panel { display: none; } .inbox-body.has-detail .notice-detail-panel { display: block; }
  .inbox-back { display: inline-flex; justify-content: flex-start; padding: 0; min-height: 32px; color: var(--button-primary-text); font-size: 12px; margin-bottom: 20px; }
  .inbox-footer { padding: 14px 15px; flex-wrap: wrap; } .inbox-feedback { flex-basis: 100%; } .inbox-footer > .glass-button { margin-left: auto; }
}
@media (max-width: 360px) { .inbox-icon { display: none; } }
@media (pointer: coarse) { .inbox-close, .all-read, .inbox-filters button, .inbox-back, .retry-read { min-height: 44px; } .inbox-close { min-width: 44px; } }
</style>

<style>
.announcement-inbox-dialog.el-dialog { padding: 0; border-radius: 16px; overflow: hidden; width: min(900px, calc(100vw - 24px)); max-height: calc(100dvh - 32px); background: var(--card-bg); }
.announcement-inbox-dialog .el-dialog__header { padding: 0; margin: 0; border-bottom: 1px solid var(--border-color); }
.announcement-inbox-dialog .el-dialog__body { padding: 0; }
.announcement-inbox-dialog .el-dialog__footer { padding: 0; border-top: 1px solid var(--border-color); }
@media (prefers-reduced-motion: reduce) { .announcement-inbox-dialog { animation: none !important; transition: opacity 100ms linear !important; } }
</style>
