<template>
  <section ref="pane" class="message-thread" aria-live="polite">
    <div v-if="loading" class="thread-state"><el-skeleton :rows="5" animated /></div>
    <div v-else-if="!messages.length && !jobs.length" class="thread-empty">
      <span class="empty-icon" aria-hidden="true"><el-icon><MagicStick /></el-icon></span>
      <h2>描述你想要的画面</h2>
      <p>可直接生图，也可以上传 1～4 张参考图。默认生成一张；需要多张时会先确认输出方式和消耗次数。</p>
      <div class="empty-suggestions">
        <button
          v-for="item in suggestions"
          :key="item"
          type="button"
          class="suggestion-chip"
          @click="emit('use-prompt', item)"
        >{{ item }}</button>
      </div>
      <p class="data-disclosure">提交的文字和参考图会发送至公司配置的第三方 AI 服务处理，请勿上传敏感资料。</p>
    </div>
    <template v-else v-for="message in visibleMessages" :key="message.id">
      <div class="message-row" :class="`is-${message.role}`">
        <span class="message-avatar" :class="`is-${message.role}`" aria-hidden="true">
          <el-icon><User v-if="message.role === 'user'" /><MagicStick v-else /></el-icon>
        </span>
        <div class="message-bubble">
          <p>{{ message.content }}</p>
          <div v-if="messageAssets(message.id).length" class="message-assets">
            <img
              v-for="asset in messageAssets(message.id)"
              :key="asset.id"
              :src="assetUrl(asset.id)"
              alt="本轮参考图，点击查看大图"
              title="点击查看大图"
              loading="lazy"
              @click="emit('preview', asset)"
            />
          </div>
        </div>
      </div>
      <OutputModeConfirmation
        v-if="message.interaction?.type === 'output_mode_confirmation'"
        :interaction="message.interaction"
        :submitting="isConfirmationSubmitting(message.id)"
        @choose="mode => emit('choose-output-mode', { message, mode })"
      />
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
import { MagicStick, User } from '@element-plus/icons-vue'
import { shouldAutoScroll } from '../state'
import GenerationCard from './GenerationCard.vue'
import OutputModeConfirmation from './OutputModeConfirmation.vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  jobs: { type: Array, default: () => [] },
  assets: { type: Array, default: () => [] },
  assetUrl: { type: Function, required: true },
  loading: { type: Boolean, default: false },
  isConfirmationSubmitting: { type: Function, default: () => false },
})
const emit = defineEmits(['retry', 'download', 'preview', 'edit', 'use-prompt', 'choose-output-mode'])
const pane = ref(null)

const suggestions = [
  '生成一张白底产品图，柔和自然光',
  '把参考图背景换成纯色，保留主体不变',
  '生成展会海报主视觉，暖金色调，留出文案区',
]

const visibleMessages = computed(() => props.messages.filter(message => (
  message.role === 'user' || !props.jobs.some(job => job.response_message_id === message.id)
)))

function messageJobs(messageId) {
  return props.jobs.filter(job => job.request_message_id === messageId)
}

function messageAssets(messageId) {
  return props.assets.filter(asset => asset.message_id === messageId && asset.asset_type === 'upload')
}

watch(() => [props.messages, props.jobs.map(job => job.status).join(',')], async (
  [nextMessages],
  [previousMessages = []] = [],
) => {
  const distanceFromBottom = pane.value
    ? pane.value.scrollHeight - pane.value.scrollTop - pane.value.clientHeight
    : Infinity
  const autoScroll = shouldAutoScroll({ distanceFromBottom, previousMessages, nextMessages })
  await nextTick()
  if (autoScroll && pane.value) pane.value.scrollTop = pane.value.scrollHeight
})
</script>

<style scoped>
.message-thread { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 26px clamp(18px, 5vw, 64px) 20px; }
.message-thread > * { max-width: 780px; }
.thread-state { margin: 40px auto; }

/* ── 空状态 ── */
.thread-empty { margin: 10vh auto 0; color: var(--text-secondary); text-align: center; }
.empty-icon {
  display: grid; width: 64px; height: 64px; margin: 0 auto; place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.9); border-radius: 20px;
  background: linear-gradient(135deg, var(--color-gold-soft) 0%, rgba(245, 203, 92, 0.55) 100%);
  box-shadow: 0 10px 26px rgba(146, 103, 24, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.9);
  color: var(--color-gold-muted); font-size: 28px;
}
.thread-empty h2 { margin: 18px 0 8px; color: var(--text-primary); font-family: var(--font-display); font-size: 20px; font-weight: 700; }
.thread-empty > p { margin: 0 auto; max-width: 420px; font-size: 13px; line-height: 1.7; }
.empty-suggestions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 20px; }
.suggestion-chip {
  padding: 8px 14px; border: 1px solid var(--border-color); border-radius: 999px;
  background: rgba(255, 255, 255, 0.72); color: var(--text-secondary); cursor: pointer; font-size: 12px;
  transition: border-color 160ms cubic-bezier(0.23, 1, 0.32, 1), color 160ms cubic-bezier(0.23, 1, 0.32, 1),
    background-color 160ms cubic-bezier(0.23, 1, 0.32, 1), transform 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.thread-empty .data-disclosure { margin: 22px auto 0; max-width: 460px; color: var(--color-warning-text); font-size: 12px; line-height: 1.6; }

/* ── 消息行 ── */
.message-row { display: flex; gap: 10px; margin: 0 auto 14px; }
.message-row.is-user { flex-direction: row-reverse; }
.message-avatar {
  display: grid; width: 30px; height: 30px; flex: 0 0 30px; place-items: center;
  border-radius: 50%; font-size: 15px;
}
.message-avatar.is-assistant {
  background: linear-gradient(135deg, var(--color-gold) 0%, var(--color-primary) 100%);
  box-shadow: 0 3px 8px rgba(146, 103, 24, 0.25); color: var(--text-on-dark);
}
.message-avatar.is-user {
  background: linear-gradient(135deg, var(--dash-icon-dark-from) 0%, var(--dash-icon-dark-to) 100%);
  box-shadow: 0 3px 8px rgba(41, 36, 32, 0.22); color: var(--text-on-dark);
}
.message-bubble { min-width: 0; max-width: 620px; padding: 11px 15px; font-size: 14px; }
.message-bubble p { margin: 0; line-height: 1.65; white-space: pre-wrap; word-break: break-word; }
.is-assistant .message-bubble { color: var(--text-primary); }
.is-user .message-bubble {
  border-radius: 16px 16px 6px;
  background: linear-gradient(135deg, var(--color-gold) 0%, var(--color-primary) 100%);
  box-shadow: 0 6px 16px rgba(146, 103, 24, 0.22); color: var(--text-on-dark);
}
.message-assets { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.message-assets img {
  width: 76px; height: 76px; border: 2px solid rgba(255, 255, 255, 0.85); border-radius: 10px;
  box-shadow: 0 2px 8px rgba(26, 24, 22, 0.12); cursor: zoom-in; object-fit: cover;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1);
}

@media (hover: hover) and (pointer: fine) {
  .suggestion-chip:hover {
    border-color: var(--color-primary); background: var(--color-primary-light);
    color: var(--color-gold-muted); transform: translateY(-1px);
  }
  .message-assets img:hover { transform: scale(1.04); }
}
@media (max-width: 640px) {
  .message-thread { padding-inline: 14px; }
  .message-bubble { font-size: 13px; }
}
@media (prefers-reduced-motion: reduce) {
  .suggestion-chip, .message-assets img { transition: none; }
}
</style>
