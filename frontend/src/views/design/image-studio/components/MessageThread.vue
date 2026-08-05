<template>
  <section ref="pane" class="message-thread" aria-live="polite">
    <div v-if="loading" class="thread-state"><el-skeleton :rows="5" animated /></div>
    <div v-else-if="!messages.length && !jobs.length" class="thread-empty">
      <el-icon><Picture /></el-icon>
      <h2>描述你想要的画面</h2>
      <p>可直接生图，也可以上传 1～4 张参考图。每轮只生成一张，成本更清楚。</p>
    </div>
    <template v-else v-for="message in visibleMessages" :key="message.id">
      <div class="message-row" :class="`is-${message.role}`">
        <span class="message-role">{{ message.role === 'user' ? '你' : 'AI' }}</span>
        <div class="message-bubble">
          <p>{{ message.content }}</p>
          <div v-if="messageAssets(message.id).length" class="message-assets">
            <img
              v-for="asset in messageAssets(message.id)"
              :key="asset.id"
              :src="assetUrl(asset.id)"
              alt="本轮参考图"
              loading="lazy"
            />
          </div>
        </div>
      </div>
      <GenerationCard
        v-for="job in messageJobs(message.id)"
        :key="job.id"
        :job="job"
        :assets="assets"
        :asset-url="assetUrl"
        @retry="emit('retry', $event)"
        @download="emit('download', $event)"
        @preview="emit('preview', $event)"
        @edit="emit('edit', $event)"
      />
    </template>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { Picture } from '@element-plus/icons-vue'
import GenerationCard from './GenerationCard.vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  jobs: { type: Array, default: () => [] },
  assets: { type: Array, default: () => [] },
  assetUrl: { type: Function, required: true },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['retry', 'download', 'preview', 'edit'])
const pane = ref(null)
const visibleMessages = computed(() => props.messages.filter(message => (
  message.role === 'user' || !props.jobs.some(job => job.response_message_id === message.id)
)))

function messageJobs(messageId) {
  return props.jobs.filter(job => job.request_message_id === messageId)
}

function messageAssets(messageId) {
  return props.assets.filter(asset => asset.message_id === messageId && asset.asset_type === 'upload')
}

watch(() => [props.messages.length, props.jobs.map(job => job.status).join(',')], async () => {
  await nextTick()
  if (pane.value) pane.value.scrollTop = pane.value.scrollHeight
})
</script>

<style scoped>
.message-thread { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 24px clamp(18px, 5vw, 64px); }
.thread-state { max-width: 680px; margin: 40px auto; }
.thread-empty { max-width: 480px; margin: 14vh auto 0; color: var(--text-secondary); text-align: center; }
.thread-empty :deep(.el-icon) { color: var(--color-primary); font-size: 42px; }
.thread-empty h2 { margin: 14px 0 8px; color: var(--text-primary); font-family: var(--font-display); }
.thread-empty p { margin: 0; line-height: 1.7; }
.message-row { display: flex; max-width: 720px; gap: 12px; margin: 0 0 12px; }
.message-row.is-user { margin-left: auto; flex-direction: row-reverse; }
.message-role { display: grid; width: 28px; height: 28px; flex: 0 0 28px; place-items: center; border-radius: 50%; background: var(--color-primary-light); color: var(--color-primary); font-size: 12px; font-weight: 700; }
.message-bubble { padding: 12px 14px; border-radius: var(--dash-card-radius); background: var(--toolbar-bg); color: var(--text-primary); }
.is-user .message-bubble { background: var(--color-primary-light); }
.message-bubble p { margin: 0; line-height: 1.65; white-space: pre-wrap; }
.message-assets { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.message-assets img { width: 76px; height: 76px; border-radius: var(--radius-md, 8px); object-fit: cover; }
@media (max-width: 640px) { .message-thread { padding-inline: 14px; } }
</style>
