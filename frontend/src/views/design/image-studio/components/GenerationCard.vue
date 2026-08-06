<template>
  <article class="generation-card" :class="`is-${job.status}`">
    <div v-if="job.status === 'queued' || job.status === 'running'" class="generation-state">
      <span class="status-orb" aria-hidden="true"><el-icon><MagicStick /></el-icon></span>
      <div class="state-copy">
        <strong>{{ job.status === 'queued' ? '已进入队列' : '正在生成' }}</strong>
        <p>{{ job.status === 'queued' ? '可以离开页面，完成后会保留在这里' : '通常需要几十秒到数分钟' }}</p>
      </div>
      <span class="state-shimmer" aria-hidden="true" />
    </div>

    <div v-else-if="job.status === 'failed'" class="generation-state failure-state">
      <span class="failure-orb" aria-hidden="true"><el-icon><WarningFilled /></el-icon></span>
      <div class="state-copy">
        <strong>本轮未生成成功</strong>
        <p>{{ failureCopy }}</p>
        <GlassButton v-if="canRetry" v-permission="'design_image:write'" variant="outline" size="sm" @click="emit('retry', job)">
          <template #left-icon><el-icon><RefreshRight /></el-icon></template>
          手动重试
        </GlassButton>
      </div>
    </div>

    <Transition name="result">
      <div v-if="job.status === 'succeeded' && outputAsset" class="result-media">
        <button class="result-frame" type="button" aria-label="查看大图" @click="emit('preview', outputAsset)">
          <img
            v-if="assetUrl(outputAsset.id)"
            :src="assetUrl(outputAsset.id)"
            :alt="`生成结果 ${outputAsset.id}，点击查看大图`"
            loading="lazy"
          />
          <el-skeleton v-else animated class="image-placeholder" />
          <span class="result-zoom" aria-hidden="true"><el-icon><ZoomIn /></el-icon>查看大图</span>
        </button>
        <div class="result-footer">
          <p class="accuracy-warning">
            <el-icon><InfoFilled /></el-icon>AI 文字可能出错，正式物料使用前必须校对
          </p>
          <div class="result-actions">
            <GlassButton variant="ghost" size="sm" title="下载原图" @click="emit('download', outputAsset)">
              <template #left-icon><el-icon><Download /></el-icon></template>
              下载
            </GlassButton>
            <GlassButton v-permission="'design_image:write'" variant="soft" size="sm" title="以这张图为基础继续修改" @click="emit('edit', outputAsset)">
              <template #left-icon><el-icon><MagicStick /></el-icon></template>
              基于这张图修改
            </GlassButton>
          </div>
        </div>
      </div>
    </Transition>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { Download, InfoFilled, MagicStick, RefreshRight, WarningFilled, ZoomIn } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'

const props = defineProps({
  job: { type: Object, required: true },
  assets: { type: Array, default: () => [] },
  assetUrl: { type: Function, required: true },
})
const emit = defineEmits(['retry', 'download', 'preview', 'edit'])

const outputAsset = computed(() => props.assets.find(asset => asset.id === props.job.output_asset_id) ?? null)
const isModerationFailure = computed(() => {
  const code = String(props.job.error_code || '').toLowerCase()
  return code.includes('moderation') || code.includes('content_policy') || code.includes('safety')
})
const canRetry = computed(() => !isModerationFailure.value)
const failureCopy = computed(() => {
  const code = String(props.job.error_code || '').toLowerCase()
  if (isModerationFailure.value) return '请调整提示词或参考图后重新发送。'
  if (code.includes('timeout')) return '模型本次响应超时，可以修改要求后重试。'
  if (code.includes('quota')) return '今日额度已用完，如为紧急任务请联系管理员。'
  if (code.includes('rate') || code.includes('429')) return '当前生成任务较多，请稍后手动重试。'
  return '生图服务暂时不可用，任务已保留，请稍后重试。'
})
</script>

<style scoped>
.generation-card { margin: -4px auto 26px; padding-left: 40px; }

/* ── 队列/生成中 ── */
.generation-state {
  position: relative; display: flex; align-items: center; gap: 12px; overflow: hidden;
  padding: 16px 18px; border: 1px solid rgba(255, 255, 255, 0.85); border-radius: var(--dash-card-radius);
  background: rgba(255, 255, 255, 0.72); box-shadow: 0 6px 18px rgba(146, 103, 24, 0.1);
}
.status-orb {
  display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center;
  border-radius: 50%; background: linear-gradient(135deg, var(--color-gold) 0%, var(--color-primary) 100%);
  box-shadow: 0 4px 12px rgba(146, 103, 24, 0.3); color: var(--text-on-dark); font-size: 17px;
  animation: orb-breathe 1.8s cubic-bezier(0.77, 0, 0.175, 1) infinite;
}
.state-copy { min-width: 0; }
.state-copy strong { color: var(--text-primary); font-size: 14px; }
.state-copy p { margin: 4px 0 0; color: var(--text-secondary); font-size: 12px; }
.state-shimmer {
  position: absolute; right: 0; bottom: 0; left: 0; height: 2px; overflow: hidden;
  background: var(--color-primary-light);
}
.state-shimmer::after {
  content: ""; position: absolute; top: 0; bottom: 0; left: 0; width: 38%;
  border-radius: 2px; background: linear-gradient(90deg, var(--color-gold), var(--color-primary));
  transform: translateX(-100%);
  animation: shimmer-slide 1.4s cubic-bezier(0.77, 0, 0.175, 1) infinite;
}

/* ── 失败 ── */
.failure-state { align-items: flex-start; border-color: rgba(192, 57, 43, 0.18); background: var(--color-danger-bg); }
.failure-orb {
  display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center;
  border-radius: 50%; background: rgba(192, 57, 43, 0.12); color: var(--color-danger-text); font-size: 17px;
}
.failure-state .state-copy strong { color: var(--color-danger-text); }
.failure-state .state-copy p { margin-bottom: 12px; color: var(--color-danger-text); }

/* ── 结果卡 ── */
.result-media {
  overflow: hidden; border: 1px solid rgba(255, 255, 255, 0.85); border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg-strong); box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}
.result-frame {
  position: relative; display: block; width: 100%; padding: 0; border: 0;
  background: var(--toolbar-bg); cursor: zoom-in;
}
.result-frame img { display: block; width: 100%; max-height: 640px; object-fit: contain; }
.image-placeholder { min-height: 280px; }
.result-zoom {
  position: absolute; right: 12px; bottom: 12px; display: inline-flex; align-items: center; gap: 5px;
  padding: 6px 12px; border: 1px solid rgba(255, 255, 255, 0.5); border-radius: 999px;
  background: rgba(30, 27, 24, 0.55); color: var(--text-on-dark); font-size: 12px;
  opacity: 0; transform: translateY(4px);
  transition: opacity 180ms cubic-bezier(0.23, 1, 0.32, 1), transform 180ms cubic-bezier(0.23, 1, 0.32, 1);
  pointer-events: none;
}
.result-footer {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 14px; border-top: 1px solid var(--border-color);
}
.accuracy-warning {
  display: inline-flex; min-width: 0; align-items: center; gap: 6px; margin: 0;
  color: var(--color-warning-text); font-size: 12px; line-height: 1.5;
}
.accuracy-warning .el-icon { flex: 0 0 auto; }
.result-actions { display: flex; flex: 0 0 auto; gap: 8px; }

.result-enter-active { transition: opacity 200ms cubic-bezier(0.23, 1, 0.32, 1), transform 200ms cubic-bezier(0.23, 1, 0.32, 1); }
.result-enter-from { opacity: 0; transform: translateY(10px) scale(0.98); }

@keyframes orb-breathe { 50% { transform: scale(0.88); opacity: 0.75; } }
@keyframes shimmer-slide { 100% { transform: translateX(264%); } }

@media (hover: hover) and (pointer: fine) {
  .result-frame:hover .result-zoom { opacity: 1; transform: translateY(0); }
}
@media (max-width: 640px) {
  .generation-card { padding-left: 0; }
  .result-footer { flex-direction: column; align-items: stretch; }
  .result-actions { justify-content: flex-end; }
}
@media (prefers-reduced-motion: reduce) {
  .result-enter-active { transition: opacity 160ms linear; }
  .result-enter-from { opacity: 0; transform: none; }
  .status-orb, .state-shimmer::after { animation: none; }
  .state-shimmer::after { transform: translateX(80%); opacity: 0.55; }
  .result-zoom { transition: opacity 160ms linear; }
}
</style>
