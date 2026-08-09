<template>
  <div class="image-workspace-page">
    <!-- 金色极光背景（纯装饰；与工作台/素材库同源 styles/liquid-glass.css） -->
    <div class="studio-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <AiWorkspaceTabs />

    <div v-if="studio" class="image-studio">
      <ConversationSidebar
        v-model:drawer-open="studio.drawerOpen.value"
        :sessions="studio.sessions.value"
        :current-session-id="studio.currentSessionId.value"
        :active-session-ids="studio.activeSessionIds.value"
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
        <div class="studio-title">
          <span class="studio-title-icon" aria-hidden="true"><el-icon><MagicStick /></el-icon></span>
          <div class="studio-title-copy">
            <h1>{{ studio.currentSession.value?.title || 'AI 生图工作台' }}</h1>
            <p>用自然语言生成，并从任意结果继续修改</p>
          </div>
        </div>
        <div
          class="quota"
          :class="{ 'is-empty': studio.config.value.remaining_today === 0 }"
          title="每日生成额度，次日重置"
        >
          <span class="quota-dot" aria-hidden="true" />
          <span class="quota-label">今日剩余</span>
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
        @use-prompt="applySuggestion"
      />

      <PromptComposer
        ref="composerRef"
        v-model:prompt="studio.prompt.value"
        v-model:size="studio.size.value"
        v-model:quality="studio.quality.value"
        :attachments="studio.draftAttachments.value"
        :base-asset="studio.baseAsset.value"
        :sizes="studio.config.value.sizes || []"
        :qualities="studio.config.value.qualities || []"
        :upload-fn="studio.uploadReference"
        :asset-url="studio.assetUrl"
        :max-upload-bytes="studio.config.value.max_upload_bytes"
        :upload-disabled="studio.newSessionInFlight.value || studio.sendInFlight.value || studio.draftAttachments.value.length >= 4"
        :can-send="studio.canSend.value"
        :sending="studio.sendInFlight.value"
        @remove="studio.removeAttachment"
        @clear-base="studio.clearBaseAsset"
        @submit="studio.submit"
        @open-prompt-library="promptLibraryOpen = true"
        @open-reference-library="referenceLibraryOpen = true"
      />
    </main>

    <PromptLibraryDialog v-model:visible="promptLibraryOpen" @apply="applyPrompt" />
    <ReferenceLibraryDialog
      v-model:visible="referenceLibraryOpen"
      :max-upload-mb="Math.max((studio.config.value.max_upload_bytes || 0) / (1024 * 1024), 0.01)"
      @select="applyLibraryAsset"
    />

      <ImageLightbox :asset="studio.lightboxAsset.value" :url="studio.lightboxUrl.value" @close="studio.closeLightbox" />
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ChatDotRound, MagicStick } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { cloneLibraryAsset } from '@/api/designImage'
import { useAuthStore } from '@/stores/auth'
import { msgError } from '@/utils/feedback'
import AiWorkspaceTabs from '../ai-workspace/AiWorkspaceTabs.vue'
import ConversationSidebar from './components/ConversationSidebar.vue'
import ImageLightbox from './components/ImageLightbox.vue'
import MessageThread from './components/MessageThread.vue'
import PromptComposer from './components/PromptComposer.vue'
import PromptLibraryDialog from './components/PromptLibraryDialog.vue'
import ReferenceLibraryDialog from './components/ReferenceLibraryDialog.vue'
import { useImageStudio } from './composables/useImageStudio'

const auth = useAuthStore()
const router = useRouter()
const canUseImage = auth.hasPermission('design_image:read')
if (!canUseImage) router.replace({ name: 'DesignAiChat' })
const studio = canUseImage ? useImageStudio() : null
const composerRef = ref(null)
const promptLibraryOpen = ref(false)
const referenceLibraryOpen = ref(false)

async function applySuggestion(text) {
  studio.prompt.value = text
  await nextTick()
  composerRef.value?.focus()
}

/* 提示词库拼装结果：输入框为空则填入，非空则换行追加 */
async function applyPrompt(text) {
  const current = studio.prompt.value.trim()
  studio.prompt.value = current ? `${current}\n${text}` : text
  await nextTick()
  composerRef.value?.focus()
}

/* 参考图库选图：确保有会话后克隆为会话草稿资产，设为基准图 */
async function applyLibraryAsset(item) {
  const session = await studio.ensureSession()
  if (!session) return
  try {
    const response = await cloneLibraryAsset(item.id, session.id)
    if (response?.data) await studio.selectLibraryBaseAsset(response.data)
  } catch {
    msgError('参考图设置失败，请稍后重试')
  }
}
</script>

<style scoped>
.image-workspace-page {
  position: relative; display: flex; width: 100%; max-width: 1240px;
  height: calc(100dvh - var(--header-height) - 48px); min-height: 560px;
  flex-direction: column; gap: 10px; margin: 0 auto; overflow: hidden;
}
.image-studio {
  position: relative; z-index: 1; display: flex; width: 100%; min-height: 0;
  flex: 1; gap: 18px;
}
.studio-aurora { inset: -24px -28px; }

/* 内容压到极光之上。必须点名内容块，不能用 > :not(.lg-aurora) 通配（会毁掉就地渲染的弹层定位）；
   侧栏是多根组件继承不到这里的 scoped 属性，它的 z-index 在自己的样式里声明 */
.studio-main { position: relative; z-index: 1; }

.studio-main {
  display: flex; min-width: 0; min-height: 0; flex: 1; flex-direction: column; overflow: hidden;
  border: 1px solid var(--dash-glass-border); background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

.studio-header {
  display: flex; min-height: 76px; flex: 0 0 auto; align-items: center; gap: 14px;
  padding: 14px 22px; border-bottom: 1px solid var(--border-color);
}
.studio-title { display: flex; min-width: 0; align-items: center; gap: 12px; }
.studio-title-icon {
  display: grid; width: 40px; height: 40px; flex: 0 0 40px; place-items: center;
  border-radius: 12px; background: linear-gradient(135deg, var(--color-gold) 0%, var(--color-primary) 100%);
  box-shadow: 0 4px 12px rgba(146, 103, 24, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.45);
  color: var(--text-on-dark); font-size: 19px;
}
.studio-title-copy { min-width: 0; }
.studio-header h1 {
  margin: 0; overflow: hidden; color: var(--text-primary);
  font-family: var(--font-display); font-size: 17px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap;
}
.studio-header p { margin: 3px 0 0; color: var(--text-muted); font-size: 12px; }

.quota {
  display: inline-flex; margin-left: auto; flex: 0 0 auto; align-items: center; gap: 7px;
  padding: 8px 14px; border: 1px solid rgba(255, 255, 255, 0.85); border-radius: 999px;
  background: rgba(255, 255, 255, 0.68); box-shadow: 0 2px 10px rgba(146, 103, 24, 0.08);
}
.quota-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--color-success); box-shadow: 0 0 0 3px var(--color-success-bg); }
.quota-label { color: var(--text-muted); font-size: 11px; }
.quota strong { color: var(--text-primary); font-size: 13px; font-variant-numeric: tabular-nums; }
.quota.is-empty .quota-dot { background: var(--el-warning); box-shadow: 0 0 0 3px var(--color-warning-bg); }
.quota.is-empty strong { color: var(--color-warning-text); }

.conversation-trigger { display: none; }

@media (max-width: 900px) {
  .image-workspace-page { min-height: 0; }
  .conversation-trigger { display: inline-flex; }
  .studio-header { min-height: 64px; padding: 10px 14px; }
  .studio-title-icon { width: 34px; height: 34px; flex-basis: 34px; font-size: 16px; }
  .studio-header p { display: none; }
}
@media (max-width: 640px) {
  .image-workspace-page { height: calc(100dvh - var(--header-height) - 24px); gap: 8px; }
  .studio-header h1 { max-width: 30vw; }
  .quota { padding: 6px 10px; }
  .quota-label { display: none; }
}
</style>
