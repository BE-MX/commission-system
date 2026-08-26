<template>
  <section ref="scrollPane" class="chat-thread" aria-live="polite" @scroll.passive="handleScroll">
    <div v-if="loading" class="thread-loading">
      <el-skeleton :rows="5" />
    </div>

    <div v-else-if="!messages.length" class="thread-welcome">
      <span class="welcome-kicker">LESHINE AI</span>
      <h1>今天想一起解决什么？</h1>
      <p v-if="canWrite">选择一种对话方式，或直接输入问题</p>
      <p v-else>你当前只有查看权限。可从左侧打开已有会话，阅读历史方案。</p>
      <StarterCards v-if="canWrite" :starters="modes" :selected-id="selectedModeId" :disabled="modeDisabled" @select="emit('starter', $event)" />
      <p v-if="catalogError" role="alert">{{ catalogError }} <button type="button" @click="emit('reload-modes')">重试</button></p>
    </div>

    <TransitionGroup v-else tag="div" name="msg" class="message-list">
      <article
        v-for="message in messages"
        :key="message.id"
        class="message-row"
        :class="`is-${message.role}`"
      >
        <div class="message-meta">
          <span>{{ message.role === 'user' ? '你' : '方案助手' }}</span>
          <span v-if="message.status === 'streaming'" class="message-status">
            生成中
            <span class="typing-dots" aria-hidden="true"><i /><i /><i /></span>
          </span>
          <span v-else-if="message.status === 'stopped'" class="message-status">已停止</span>
          <span v-else-if="message.status === 'failed'" class="message-status is-error">生成失败</span>
        </div>

        <div v-if="message.role === 'assistant'" class="assistant-message">
          <div
            v-if="message.content"
            class="markdown-body"
            :class="{ 'is-streaming': message.status === 'streaming' }"
            v-html="renderMarkdown(message.content)"
          />
          <p v-else-if="message.status === 'streaming'" class="stream-placeholder">正在组织方案…</p>
          <p v-if="message.error_message" class="message-error">{{ message.error_message }}</p>
        </div>
        <p v-else class="user-message">{{ message.content }}</p>

        <div v-if="message.attachments?.length" class="message-attachments">
          <span v-for="attachment in message.attachments" :key="attachment.id" class="attachment-label">
            <el-icon aria-hidden="true"><Paperclip /></el-icon>
            {{ attachment.original_name }}
          </span>
        </div>

        <div class="message-actions">
          <button type="button" @click="copyMessage(message)">
            <el-icon aria-hidden="true"><CopyDocument /></el-icon>
            复制
          </button>
          <button
            v-if="message.role === 'assistant' && ['failed', 'stopped'].includes(message.status) && canWrite"
            type="button"
            @click="emit('retry', message.id)"
          >
            <el-icon aria-hidden="true"><RefreshRight /></el-icon>
            重试
          </button>
        </div>
      </article>
    </TransitionGroup>

    <Transition name="fab">
      <button v-if="showScrollDown" type="button" class="scroll-latest" @click="scrollToLatest">
        <el-icon aria-hidden="true"><ArrowDown /></el-icon>
        回到最新
      </button>
    </Transition>
  </section>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { ArrowDown, CopyDocument, Paperclip, RefreshRight } from '@element-plus/icons-vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import StarterCards from './StarterCards.vue'
import { msgError, msgSuccess } from '@/utils/feedback'

const props = defineProps({
  modes: { type: Array, default: () => [] },
  selectedModeId: { type: String, default: '' },
  modeDisabled: { type: Boolean, default: false },
  catalogError: { type: String, default: '' },
  messages: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  canWrite: { type: Boolean, default: false },
})
const emit = defineEmits(['starter', 'retry', 'reload-modes'])
const scrollPane = ref(null)

marked.setOptions({ gfm: true, breaks: true })

function renderMarkdown(raw) {
  return DOMPurify.sanitize(marked.parse(raw))
}

async function copyMessage(message) {
  try {
    await navigator.clipboard.writeText(message.content || '')
    msgSuccess('复制')
  } catch {
    msgError('复制失败，请手动选择文本')
  }
}

// 自动滚底：只在用户停留在底部附近时才跟随流式输出；
// 用户上翻阅读时松开，由「回到最新」按钮召回
const stickToBottom = ref(true)
const showScrollDown = ref(false)

function distanceFromBottom() {
  const pane = scrollPane.value
  return pane ? pane.scrollHeight - pane.scrollTop - pane.clientHeight : 0
}

function handleScroll() {
  const distance = distanceFromBottom()
  stickToBottom.value = distance < 90
  showScrollDown.value = distance > 260
}

function scrollToLatest() {
  stickToBottom.value = true
  scrollPane.value?.scrollTo({
    top: scrollPane.value.scrollHeight,
    behavior: 'auto',
  })
}

let prevSignature = ''
watch(
  () => props.messages.map(message => `${message.id}:${message.status}:${message.content?.length || 0}`).join('|'),
  async () => {
    // 首尾 id 或数量变化 = 新消息/切换会话 → 钉回底部；仅内容长度变化 = 流式追加 → 跟随当前钉住状态
    const last = props.messages[props.messages.length - 1]
    const signature = `${props.messages[0]?.id}:${last?.id}:${props.messages.length}`
    if (signature !== prevSignature) stickToBottom.value = true
    prevSignature = signature
    await nextTick()
    if (scrollPane.value && stickToBottom.value) {
      scrollPane.value.scrollTop = scrollPane.value.scrollHeight
    }
    showScrollDown.value = distanceFromBottom() > 260
  },
)
</script>

<style scoped>
.chat-thread {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 28px clamp(18px, 5vw, 72px) 22px;
  scrollbar-width: thin;
}

.thread-loading,
.thread-welcome,
.message-list { width: min(100%, 820px); margin: 0 auto; }

.thread-welcome {
  padding-top: clamp(12px, 2vh, 24px);
  animation: welcome-in 260ms var(--ease-out-strong) backwards;
}

@keyframes welcome-in {
  from { opacity: 0; transform: translateY(14px); }
}

.welcome-kicker {
  color: var(--color-primary);
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.13em;
}

.thread-welcome h1 {
  margin: 8px 0;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: clamp(24px, 3vw, 34px);
  line-height: 1.2;
}

.thread-welcome > p {
  max-width: 590px;
  margin: 0 0 24px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

/* 新消息入场（TransitionGroup，仅新增/换会话时触发） */
.msg-enter-active {
  transition:
    opacity 260ms var(--ease-out-strong),
    transform 260ms var(--ease-out-strong);
}
.msg-enter-from { opacity: 0; transform: translateY(10px); }

.message-row { margin-bottom: 26px; }
.message-row.is-user { display: flex; flex-direction: column; align-items: flex-end; }
.message-meta {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 7px;
  color: var(--text-muted-blue);
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 700;
}

.message-status { display: inline-flex; align-items: center; color: var(--color-warning-text); font-weight: 600; }
.message-status.is-error,
.message-error { color: var(--color-danger-text); }

/* 「生成中」三点跳动 */
.typing-dots { display: inline-flex; align-items: center; gap: 3px; margin-left: 6px; }
.typing-dots i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: currentColor;
  animation: dot-bounce 1.2s ease-in-out infinite;
}
.typing-dots i:nth-child(2) { animation-delay: 150ms; }
.typing-dots i:nth-child(3) { animation-delay: 300ms; }

@keyframes dot-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.45; }
  30% { transform: translateY(-3px); opacity: 1; }
}

.assistant-message {
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.75;
}

.user-message {
  max-width: min(86%, 640px);
  margin: 0;
  padding: 12px 16px;
  border-radius: 16px 16px 5px;
  background: linear-gradient(135deg, var(--dash-icon-dark-from), var(--dash-icon-dark-to));
  box-shadow: var(--card-shadow);
  color: var(--text-on-dark);
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
}

/* 流式输出末尾的闪烁光标 */
.markdown-body.is-streaming :deep(> :last-child)::after {
  content: "";
  display: inline-block;
  width: 7px;
  height: 14px;
  margin-left: 3px;
  border-radius: 2px;
  background: var(--color-primary);
  vertical-align: -2px;
  animation: caret-blink 0.9s ease-in-out infinite;
}

@keyframes caret-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.stream-placeholder { margin: 0; color: var(--text-muted); animation: placeholder-breathe 1.6s ease-in-out infinite; }

@keyframes placeholder-breathe {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}

.message-error { margin: 10px 0 0; font-size: 12px; }
.message-attachments { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.attachment-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 260px;
  padding: 5px 9px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--dash-glass-bg-strong);
  color: var(--text-secondary);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-actions {
  display: flex;
  gap: 4px;
  margin-top: 8px;
  transition: opacity 180ms ease;
}
.message-row.is-user .message-actions { justify-content: flex-end; }
.message-actions button {
  display: inline-flex;
  min-height: 30px;
  align-items: center;
  gap: 5px;
  padding: 0 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted-blue);
  cursor: pointer;
  font-size: 12px;
  transition: background-color 180ms ease, color 180ms ease;
}

.message-actions button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }

/* 上翻时出现的「回到最新」浮钮（sticky 于滚动容器底部） */
.scroll-latest {
  position: sticky;
  bottom: 14px;
  z-index: 2;
  display: flex;
  width: fit-content;
  align-items: center;
  gap: 5px;
  margin: 8px 4px 0 auto;
  padding: 7px 14px;
  border: 1px solid var(--dash-glass-border);
  border-radius: 999px;
  background: var(--dash-glass-bg-strong);
  box-shadow: var(--dash-glass-highlight), var(--dash-glass-shadow);
  color: var(--color-primary);
  cursor: pointer;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  transition:
    transform 200ms var(--ease-out-strong),
    box-shadow 200ms var(--ease-out-strong);
}

.scroll-latest:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }

.fab-enter-active,
.fab-leave-active {
  transition:
    opacity 200ms var(--ease-out-strong),
    transform 200ms var(--ease-out-strong);
}
.fab-enter-from,
.fab-leave-to { opacity: 0; transform: translateY(8px) scale(0.94); }

.markdown-body :deep(*) { max-width: 100%; }
.markdown-body :deep(p) { margin: 0 0 0.85em; }
.markdown-body :deep(p:last-child) { margin-bottom: 0; }
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) { margin: 1.25em 0 0.5em; font-family: var(--font-display); line-height: 1.35; }
.markdown-body :deep(h1:first-child),
.markdown-body :deep(h2:first-child),
.markdown-body :deep(h3:first-child) { margin-top: 0; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) { padding-left: 1.5em; }
.markdown-body :deep(blockquote) { margin: 1em 0; padding-left: 12px; border-left: 3px solid var(--color-primary); color: var(--text-secondary); }
.markdown-body :deep(code) { padding: 2px 5px; border-radius: 5px; background: var(--toolbar-bg); font-size: 0.92em; }
.markdown-body :deep(pre) { overflow-x: auto; padding: 13px; border-radius: 10px; background: var(--ink-dark); color: var(--text-on-dark); }
.markdown-body :deep(pre code) { padding: 0; background: transparent; }
.markdown-body :deep(table) { display: block; overflow-x: auto; border-collapse: collapse; }
.markdown-body :deep(th),
.markdown-body :deep(td) { padding: 8px 10px; border: 1px solid var(--border-color); text-align: left; }
.markdown-body :deep(a) { color: var(--color-primary); }

@media (hover: hover) and (pointer: fine) {
  /* 桌面端操作按钮平时收起，悬停/聚焦时浮现 */
  .message-actions { opacity: 0; }
  .message-row:hover .message-actions,
  .message-row:focus-within .message-actions { opacity: 1; }
  .message-actions button:hover { background: var(--color-primary-light); color: var(--color-primary); }
  .scroll-latest:hover {
    transform: translateY(-2px);
    box-shadow: var(--dash-glass-highlight), var(--dash-glass-shadow-hover);
  }
}

@media (max-width: 640px) {
  .chat-thread { padding: 20px 14px 16px; }
  .thread-welcome { padding-top: 18px; }
  .user-message { max-width: 92%; }
}

@media (prefers-reduced-motion: reduce) {
  .thread-welcome,
  .typing-dots i,
  .stream-placeholder { animation: none; }
  .markdown-body.is-streaming :deep(> :last-child)::after { animation: none; opacity: 0.6; }
  .msg-enter-active,
  .fab-enter-active,
  .fab-leave-active { transition: none; }
  .scroll-latest:hover { transform: none; }
}
</style>
