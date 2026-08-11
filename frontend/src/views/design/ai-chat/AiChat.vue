<template>
  <div class="ai-chat-page">
    <div class="ai-chat-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <AiWorkspaceTabs />

    <div class="chat-workspace">
      <ChatSidebar
        v-model:drawer-open="chat.drawerOpen.value"
        :sessions="chat.sessions.value"
        :current-session-id="chat.currentSessionId.value"
        :loading="chat.initializing.value"
        :can-write="chat.canWrite.value"
        @new="startConversation"
        @select="chat.selectSession"
      />

      <main class="chat-main lg-card is-static">
        <header class="chat-header">
          <button type="button" class="session-trigger" @click="chat.drawerOpen.value = true">
            <el-icon aria-hidden="true"><Menu /></el-icon>
            会话
          </button>
          <div class="chat-title">
            <span class="title-mark" aria-hidden="true"><el-icon><ChatLineRound /></el-icon></span>
            <div>
              <h2>{{ chat.currentSession.value?.title || '方案对话' }}</h2>
              <p>把客户背景和约束讲清楚，一起形成可执行方案</p>
            </div>
          </div>
          <span class="privacy-label"><el-icon aria-hidden="true"><Lock /></el-icon> 仅自己可见</span>
        </header>

        <div v-if="!chat.config.value.configured" class="notice-banner" role="alert">
          <span>{{ chat.config.value.message || '方案助手尚未配置，请联系管理员。' }}</span>
        </div>
        <div v-if="chat.error.value" class="error-banner" role="alert">
          <span>{{ chat.error.value.message }}</span>
          <button v-if="chat.currentSessionId.value" type="button" @click="chat.refreshCurrent">刷新会话</button>
        </div>

        <ChatThread
          :messages="chat.messages.value"
          :loading="chat.initializing.value || chat.sessionLoading.value"
          :can-write="chat.canWrite.value"
          @starter="applyStarter"
          @retry="chat.retry"
        />

        <ChatComposer
          ref="composerRef"
          v-model:prompt="chat.prompt.value"
          :attachments="chat.draftAttachments.value"
          :upload-fn="chat.uploadDraft"
          :can-write="chat.canWrite.value && chat.config.value.configured"
          :can-submit="chat.canSubmit.value && chat.config.value.configured"
          :streaming="chat.streaming.value"
          @remove="chat.removeDraft"
          @send="chat.send"
          @stop="chat.stop"
        />
      </main>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import { ChatLineRound, Lock, Menu } from '@element-plus/icons-vue'
import AiWorkspaceTabs from '../ai-workspace/AiWorkspaceTabs.vue'
import ChatComposer from './components/ChatComposer.vue'
import ChatSidebar from './components/ChatSidebar.vue'
import ChatThread from './components/ChatThread.vue'
import { useAiChat } from './composables/useAiChat'

const chat = useAiChat()
const composerRef = ref(null)

async function applyStarter(prompt) {
  chat.prompt.value = prompt
  await nextTick()
  composerRef.value?.focus()
}

async function startConversation() {
  chat.newConversation()
  await nextTick()
  composerRef.value?.focus()
}
</script>

<style scoped>
.ai-chat-page {
  position: relative;
  display: flex;
  width: 100%;
  max-width: 1240px;
  height: calc(100dvh - var(--header-height) - 48px);
  min-height: 560px;
  flex-direction: column;
  gap: 10px;
  margin: 0 auto;
  overflow: hidden;
}

.ai-chat-aurora { inset: -24px -28px; }

.chat-workspace {
  position: relative;
  z-index: 1;
  display: flex;
  min-height: 0;
  flex: 1;
  gap: 18px;
  animation: workspace-in 280ms var(--ease-out-strong);
}

@keyframes workspace-in {
  from { opacity: 0; transform: translateY(8px); }
}

.chat-main {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--dash-glass-border);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-highlight), var(--dash-glass-shadow);
}

.chat-header {
  display: grid;
  min-height: 72px;
  flex: 0 0 auto;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--border-color);
  background: var(--dash-glass-bg-strong);
}

.chat-title { display: flex; min-width: 0; align-items: center; gap: 11px; }
.title-mark {
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  place-items: center;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--color-gold-soft), var(--color-gold));
  box-shadow: var(--card-shadow);
  color: var(--color-gold-muted);
}
.chat-title h2 {
  margin: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-title p { margin: 3px 0 0; color: var(--text-muted-blue); font-size: 11px; }
.privacy-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 9px;
  border-radius: 999px;
  background: var(--color-primary-light);
  color: var(--color-warning-text);
  font-size: 11px;
  font-weight: 600;
}

.session-trigger {
  display: none;
  min-height: 34px;
  align-items: center;
  gap: 5px;
  padding: 0 9px;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  transition:
    border-color 180ms ease,
    box-shadow 180ms ease,
    color 180ms ease;
}

.notice-banner,
.error-banner {
  display: flex;
  min-height: 38px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 18px;
  border-bottom: 1px solid var(--border-color);
  font-size: 12px;
  animation: banner-in 260ms var(--ease-out-strong);
}

@keyframes banner-in {
  from { opacity: 0; transform: translateY(-6px); }
}
.notice-banner { background: var(--color-warning-bg); color: var(--color-warning-text); }
.error-banner { background: var(--color-danger-bg); color: var(--color-danger-text); }
.error-banner button {
  flex: 0 0 auto;
  padding: 4px 8px;
  border: 1px solid currentColor;
  border-radius: 7px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: 11px;
}

.session-trigger:focus-visible,
.error-banner button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }

@media (hover: hover) and (pointer: fine) {
  .session-trigger:hover { border-color: var(--border-hover); box-shadow: var(--card-shadow); color: var(--text-primary); }
  .error-banner button:hover { box-shadow: var(--card-shadow); }
}

@media (max-width: 899px) {
  .chat-workspace { gap: 0; }
  .session-trigger { display: inline-flex; }
  .chat-header { grid-template-columns: auto minmax(0, 1fr) auto; padding: 10px 12px; }
  .title-mark { display: none; }
  .chat-title p { display: none; }
}

@media (max-width: 640px) {
  .ai-chat-page { height: calc(100dvh - var(--header-height) - 24px); min-height: 0; gap: 8px; }
  .chat-header { min-height: 60px; }
  .privacy-label { padding: 5px 7px; }
  .notice-banner,
  .error-banner { padding: 7px 12px; }
}

@media (prefers-reduced-motion: reduce) {
  .chat-workspace,
  .notice-banner,
  .error-banner { animation: none; }
}
</style>
