<template>
  <article class="generation-card" :class="`is-${job.status}`">
    <div v-if="job.status === 'queued' || job.status === 'running'" class="generation-state">
      <span class="status-pulse" aria-hidden="true" />
      <div>
        <strong>{{ job.status === 'queued' ? '已进入队列' : '正在生成' }}</strong>
        <p>{{ job.status === 'queued' ? '可以离开页面，完成后会保留在这里' : '通常需要几十秒到数分钟' }}</p>
      </div>
    </div>

    <div v-else-if="job.status === 'failed'" class="generation-state failure-state">
      <el-icon><WarningFilled /></el-icon>
      <div>
        <strong>本轮未生成成功</strong>
        <p>{{ failureCopy }}</p>
        <GlassButton v-permission="'design_image:write'" variant="outline" size="sm" @click="emit('retry', job)">
          手动重试
        </GlassButton>
      </div>
    </div>

    <Transition name="result">
      <div v-if="job.status === 'succeeded' && outputAsset" class="result-media">
        <img
          v-if="assetUrl(outputAsset.id)"
          :src="assetUrl(outputAsset.id)"
          :alt="`生成结果 ${outputAsset.id}`"
          loading="lazy"
        />
        <el-skeleton v-else animated class="image-placeholder" />
        <div class="result-actions">
          <GlassButton variant="outline" size="sm" @click="emit('download', outputAsset)">下载</GlassButton>
          <GlassButton variant="ghost" size="sm" @click="emit('preview', outputAsset)">查看大图</GlassButton>
          <GlassButton v-permission="'design_image:write'" variant="soft" size="sm" @click="emit('edit', outputAsset)">
            基于这张图修改
          </GlassButton>
        </div>
        <p class="accuracy-warning">AI 文字可能出错，正式物料使用前必须校对。</p>
      </div>
    </Transition>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'

const props = defineProps({
  job: { type: Object, required: true },
  assets: { type: Array, default: () => [] },
  assetUrl: { type: Function, required: true },
})
const emit = defineEmits(['retry', 'download', 'preview', 'edit'])

const outputAsset = computed(() => props.assets.find(asset => asset.id === props.job.output_asset_id) ?? null)
const failureCopy = computed(() => {
  const code = String(props.job.error_code || '').toLowerCase()
  if (code.includes('moderation')) return '请调整提示词或参考图后重新发送。'
  if (code.includes('timeout')) return '模型本次响应超时，可以修改要求后重试。'
  if (code.includes('quota')) return '今日额度已用完，如为紧急任务请联系管理员。'
  if (code.includes('rate') || code.includes('429')) return '当前生成任务较多，请稍后手动重试。'
  return '生图服务暂时不可用，任务已保留，请稍后重试。'
})
</script>

<style scoped>
.generation-card { max-width: 680px; margin: 10px 0 24px 38px; }
.generation-state {
  display: flex; align-items: flex-start; gap: 12px; padding: 16px;
  border: 1px solid var(--border-color); border-radius: var(--dash-card-radius); background: var(--toolbar-bg);
}
.generation-state strong { color: var(--text-primary); font-size: 14px; }
.generation-state p { margin: 5px 0 0; color: var(--text-secondary); font-size: 13px; }
.status-pulse { width: 10px; height: 10px; margin-top: 4px; border-radius: 50%; background: var(--color-primary); animation: status-pulse 1.4s linear infinite; }
.failure-state { background: var(--color-danger-bg); color: var(--color-danger-text); }
.failure-state p { margin-bottom: 12px; }
.result-media { overflow: hidden; border: 1px solid var(--border-color); border-radius: var(--dash-card-radius); background: var(--card-bg); box-shadow: var(--card-shadow); }
.result-media img { display: block; width: 100%; max-height: 680px; object-fit: contain; background: var(--toolbar-bg); }
.image-placeholder { min-height: 280px; }
.result-actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 14px 6px; }
.accuracy-warning { margin: 6px 14px 14px; color: var(--color-warning-text); font-size: 12px; }
.result-enter-active { transition: opacity 180ms cubic-bezier(0.23, 1, 0.32, 1), transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.result-enter-from { opacity: 0; transform: scale(0.97); }
@keyframes status-pulse { 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) {
  .result-enter-active { transition: opacity 180ms linear; }
  .result-enter-from { opacity: 0; transform: none; }
  .status-pulse { animation: none; opacity: 0.65; }
}
</style>
