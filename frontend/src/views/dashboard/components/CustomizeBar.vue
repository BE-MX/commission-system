<template>
  <Transition name="bar-slide">
    <div v-if="editing" class="customize-bar">
      <div class="bar-hint">
        <el-icon><Rank /></el-icon>
        <span>拖拽排序 · 点眼睛显隐 · 保存后生效</span>
      </div>
      <div class="bar-actions">
        <GlassButton variant="ghost" size="sm" @click="onReset">恢复默认</GlassButton>
        <GlassButton variant="secondary" size="sm" @click="$emit('cancel')">取消</GlassButton>
        <GlassButton variant="primary" size="sm" :loading="saving" :disabled="!dirty" @click="$emit('save')">
          保存布局
        </GlassButton>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { Rank } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { confirmDanger } from '@/utils/feedback'

defineProps({
  editing: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  dirty: { type: Boolean, default: false },
})

const emit = defineEmits(['save', 'cancel', 'reset'])

function onReset() {
  confirmDanger('恢复默认', '工作台布局', '你的显隐与排序调整将被清除。')
    .then(() => emit('reset'))
    .catch(() => { /* 用户取消 */ })
}
</script>

<style scoped>
.customize-bar {
  position: fixed;
  left: 50%;
  bottom: 28px;
  transform: translateX(-50%);
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 12px 20px;
  border-radius: 16px;
  background: var(--glass-bg-strong);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(1.5);
  backdrop-filter: blur(var(--glass-blur)) saturate(1.5);
  border: 1px solid var(--glass-border);
  box-shadow: var(--glass-highlight), var(--glass-shadow-hover);
}
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .customize-bar {
    background: var(--card-bg);
  }
}

.bar-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-body);
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.bar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 入场 ease-out 220ms、退场更快 150ms（Emil：exit 快于 enter） */
.bar-slide-enter-active {
  transition: transform 220ms var(--ease-out-strong), opacity 220ms var(--ease-out-strong);
}
.bar-slide-leave-active {
  transition: transform 150ms var(--ease-out-strong), opacity 150ms var(--ease-out-strong);
}
.bar-slide-enter-from,
.bar-slide-leave-to {
  transform: translateX(-50%) translateY(calc(100% + 28px));
  opacity: 0;
}

@media (max-width: 767px) {
  .customize-bar {
    left: 12px;
    right: 12px;
    transform: none;
    justify-content: space-between;
    gap: 10px;
  }
  .bar-hint {
    display: none;
  }
  .bar-slide-enter-from,
  .bar-slide-leave-to {
    transform: translateY(calc(100% + 28px));
  }
}

/* 放在响应式块之后：手机 + 减少动态用户也要去掉滑入位移（审查 P2） */
@media (prefers-reduced-motion: reduce) {
  .bar-slide-enter-from,
  .bar-slide-leave-to {
    transform: translateX(-50%);
    opacity: 0;
  }
}
@media (prefers-reduced-motion: reduce) and (max-width: 767px) {
  .bar-slide-enter-from,
  .bar-slide-leave-to {
    transform: none;
  }
}
</style>
