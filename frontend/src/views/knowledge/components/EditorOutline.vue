<template>
  <aside class="editor-outline" aria-label="文档大纲">
    <div class="outline-title">大纲</div>
    <button
      v-for="item in items"
      :key="item.id"
      type="button"
      :style="{ paddingLeft: `${8 + (item.level - 1) * 10}px` }"
      @click="$emit('navigate', item)"
    >{{ item.text }}</button>
    <p v-if="!items.length">添加标题后自动生成</p>
  </aside>
</template>

<script setup>
defineProps({ items: { type: Array, default: () => [] } })
defineEmits(['navigate'])
</script>

<style scoped>
.editor-outline { min-width: 0; overflow: auto; padding: 18px 12px; border-left: 1px solid var(--border-color); background: var(--surface-card); }
.outline-title { margin-bottom: 8px; color: var(--text-primary); font-size: 13px; font-weight: 700; }
button { display: block; width: 100%; overflow: hidden; padding-block: 4px; border: 0; border-radius: 6px; color: var(--text-secondary); background: transparent; cursor: pointer; font-size: 11.5px; line-height: 1.4; text-align: left; text-overflow: ellipsis; white-space: nowrap; transition: color .15s ease, background-color .15s ease; }
p { color: var(--text-muted-blue); font-size: 11.5px; line-height: 1.5; }
button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
@media (hover: hover) and (pointer: fine) { button:hover { color: var(--color-primary); background: var(--color-primary-light); } }
@media (prefers-reduced-motion: reduce) { button { transition: none; } }
</style>
