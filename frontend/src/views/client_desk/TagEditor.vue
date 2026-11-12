<template>
  <div class="tag-editor">
    <span v-for="tag in fixedTags" :key="tag.code" class="tag" :class="['tone-' + tagTone(tag), { solid: tag.kind === 'grade' && tag.code !== 'grade:none' }]">{{ tag.label }}</span>
    <span v-for="tag in aiTags" :key="tag.code" class="tag ai" :class="'tone-' + tagTone(tag)" :title="tag.reason || ''">
      ✦ {{ tag.label }}
      <button v-permission="'client_desk:write'" type="button" class="remove board-focus" :disabled="busy" :aria-label="`移除标签 ${tag.label}`" @click="$emit('toggle', tag.code, 'remove')">×</button>
    </span>
    <el-popover v-if="removedTags.length" trigger="click" :width="240" placement="bottom-start">
      <template #reference><button type="button" class="link-button">已移除 {{ removedTags.length }}</button></template>
      <p class="muted">移除后 AI 不会再自动打上这些标签。</p>
      <div class="restore">
        <span v-for="tag in removedTags" :key="tag.code" class="tag">
          {{ tag.label }}
          <button v-permission="'client_desk:write'" type="button" class="link-button" :disabled="busy" @click="$emit('toggle', tag.code, 'restore')">恢复</button>
        </span>
      </div>
    </el-popover>
  </div>
</template>

<script setup>
import { tagTone } from './boardModel'

defineProps({
  fixedTags: { type: Array, default: () => [] },
  aiTags: { type: Array, default: () => [] },
  removedTags: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})
defineEmits(['toggle'])
</script>

<style src="./board.css" scoped></style>
<style scoped>
.tag-editor { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.tag.ai { padding-right: 2px; }
.remove { display: grid; place-items: center; width: 16px; height: 16px; padding: 0; border: 0; border-radius: 4px; background: transparent; color: inherit; font-size: 13px; line-height: 1; cursor: pointer; opacity: 0.6; }
.remove:hover { opacity: 1; background: var(--card-bg); }
.restore { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
</style>
