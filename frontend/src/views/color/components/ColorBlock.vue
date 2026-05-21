<template>
  <div
    class="color-block"
    :class="{ 'is-blend': isBlend, 'is-clickable': clickable }"
    @click="$emit('click', $event)"
  >
    <div class="color-preview" :style="previewStyle">
      <GradientBar
        v-if="isBlend && components && components.length"
        :components="components"
        :blend-type="blendType"
        :size="size"
      />
    </div>
    <div class="color-info">
      <div class="color-code">{{ code }}</div>
      <div class="color-name" :title="name">{{ name }}</div>
      <div v-if="hex" class="color-hex">{{ hex }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import GradientBar from './GradientBar.vue'

const props = defineProps({
  code: { type: String, default: '' },
  name: { type: String, default: '' },
  hex: { type: String, default: '' },
  isBlend: { type: Boolean, default: false },
  blendType: { type: String, default: '' },
  components: { type: Array, default: () => [] },
  size: { type: String, default: 'medium' }, // small / medium / large
  clickable: { type: Boolean, default: true },
})

defineEmits(['click'])

const previewStyle = computed(() => {
  if (props.isBlend) {
    return {}
  }
  return {
    backgroundColor: props.hex || '#ccc',
  }
})
</script>

<style scoped>
.color-block {
  border-radius: 8px;
  overflow: hidden;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  transition: all 0.2s ease;
  cursor: default;
}
.color-block.is-clickable {
  cursor: pointer;
}
.color-block.is-clickable:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  border-color: var(--el-color-primary-light-5);
}
.color-preview {
  width: 100%;
  aspect-ratio: 1;
  position: relative;
}
.color-info {
  padding: 8px 10px;
  text-align: center;
}
.color-code {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  line-height: 1.4;
}
.color-name {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.color-hex {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-family: monospace;
  margin-top: 2px;
}
</style>
