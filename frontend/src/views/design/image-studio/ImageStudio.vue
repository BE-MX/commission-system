<template>
  <div class="image-studio">
    <ConversationSidebar
      v-model:drawer-open="studio.drawerOpen.value"
      :sessions="studio.sessions.value"
      :current-session-id="studio.currentSessionId.value"
      :active-job="studio.activeJob.value"
      :has-more="Boolean(studio.nextCursor.value)"
      :loading="studio.sessionsLoading.value"
      @new="studio.newConversation"
      @select="studio.selectSession"
      @more="studio.loadMoreSessions"
    />

    <main class="studio-main lg-card is-static">
      <header class="studio-header">
        <GlassButton class="conversation-trigger" variant="ghost" size="sm" @click="studio.drawerOpen.value = true">
          <template #left-icon><el-icon><ChatDotRound /></el-icon></template>
          会话
        </GlassButton>
        <div>
          <h1>{{ studio.currentSession.value?.title || 'AI 生图工作台' }}</h1>
          <p>用自然语言生成，并从任意结果继续修改</p>
        </div>
        <div class="quota" :class="{ 'is-empty': studio.config.value.remaining_today === 0 }">
          <span>今日剩余</span>
          <strong>{{ studio.config.value.remaining_today ?? '—' }} / {{ studio.config.value.daily_limit ?? '—' }}</strong>
        </div>
      </header>

      <MessageThread
        :messages="studio.messages.value"
        :jobs="studio.jobs.value"
        :assets="studio.assets.value"
        :asset-url="studio.assetUrl"
        :loading="studio.initializing.value"
        @retry="studio.retry"
        @download="studio.downloadAsset"
        @preview="studio.openLightbox"
        @edit="studio.chooseBaseAsset"
      />

      <PromptComposer
        v-model:prompt="studio.prompt.value"
        v-model:size="studio.size.value"
        v-model:quality="studio.quality.value"
        :attachments="studio.draftAttachments.value"
        :base-asset="studio.baseAsset.value"
        :sizes="studio.config.value.sizes || []"
        :qualities="studio.config.value.qualities || []"
        :upload-fn="studio.uploadReference"
        :asset-url="studio.assetUrl"
        :upload-disabled="studio.sendInFlight.value || studio.draftAttachments.value.length >= 4"
        :can-send="studio.canSend.value"
        :sending="studio.sendInFlight.value"
        @remove="studio.removeAttachment"
        @clear-base="studio.baseAsset.value = null"
        @submit="studio.submit"
      />
    </main>

    <ImageLightbox :asset="studio.lightboxAsset.value" :url="studio.lightboxUrl.value" @close="studio.closeLightbox" />
  </div>
</template>

<script setup>
import { ChatDotRound } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import ConversationSidebar from './components/ConversationSidebar.vue'
import ImageLightbox from './components/ImageLightbox.vue'
import MessageThread from './components/MessageThread.vue'
import PromptComposer from './components/PromptComposer.vue'
import { useImageStudio } from './composables/useImageStudio'

const studio = useImageStudio()
</script>

<style scoped>
.image-studio { display: flex; width: 100%; max-width: 1070px; height: calc(100vh - var(--header-height) - 48px); min-height: 560px; gap: 16px; margin: 0 auto; overflow: hidden; }
.studio-main { display: flex; min-width: 0; min-height: 0; flex: 1; flex-direction: column; overflow: hidden; border: 1px solid var(--dash-glass-border); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight); }
.studio-header { display: flex; min-height: 72px; flex: 0 0 auto; align-items: center; gap: 12px; padding: 12px 20px; border-bottom: 1px solid var(--border-color); }
.studio-header h1 { margin: 0; color: var(--text-primary); font-family: var(--font-display); font-size: 18px; }
.studio-header p { margin: 3px 0 0; color: var(--text-muted); font-size: 12px; }
.quota { margin-left: auto; padding: 7px 10px; border-radius: var(--radius-md, 8px); background: var(--color-success-bg); color: var(--color-success-text); text-align: right; }
.quota span { display: block; font-size: 10px; }
.quota strong { font-size: 13px; }
.quota.is-empty { background: var(--color-warning-bg); color: var(--color-warning-text); }
.conversation-trigger { display: none; }
@media (max-width: 900px) {
  .image-studio { height: calc(100dvh - var(--header-height) - 48px); min-height: 0; }
  .conversation-trigger { display: inline-flex; }
  .studio-header { padding-inline: 12px; }
  .studio-header p { display: none; }
}
@media (max-width: 640px) {
  .studio-header h1 { max-width: 34vw; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
</style>
