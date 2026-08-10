<template>
  <div v-if="open" class="slash-menu" :style="positionStyle" role="listbox" aria-label="插入内容">
    <div class="slash-heading">插入内容</div>
    <button
      v-for="(item, index) in items"
      :key="item.id"
      type="button"
      role="option"
      :aria-selected="index === activeIndex"
      :class="{ active: index === activeIndex }"
      @mousedown.prevent="$emit('select', item.id)"
      @mouseenter="$emit('activate', index)"
    >
      <span class="command-icon">{{ iconFor(item.id) }}</span>
      <span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span>
    </button>
    <div v-if="!items.length" class="slash-empty">没有匹配的命令</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  open: Boolean, items: { type: Array, default: () => [] }, activeIndex: { type: Number, default: 0 },
  position: { type: Object, default: () => ({ left: 0, top: 0 }) },
})
defineEmits(['select', 'activate'])

const positionStyle = computed(() => ({ left: `${props.position.left}px`, top: `${props.position.top}px` }))
function iconFor(id) {
  if (id.startsWith('heading-')) return `H${id.slice(-1)}`
  return ({ paragraph: 'T', 'bullet-list': '•', 'ordered-list': '1.', 'task-list': '☑', blockquote: '❝', 'code-block': '</>', 'horizontal-rule': '―', table: '▦' })[id] || '+'
}
</script>

<style scoped>
.slash-menu { position: fixed; z-index: 40; width: 290px; max-height: min(420px, 60vh); overflow: auto; padding: 6px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--surface-card); box-shadow: 0 16px 40px rgba(26, 26, 46, .16); }
.slash-heading { padding: 7px 9px; color: var(--text-muted-blue); font-size: 11px; font-weight: 700; letter-spacing: .08em; }
button { display: grid; width: 100%; grid-template-columns: 34px 1fr; align-items: center; gap: 9px; padding: 8px; border: 0; border-radius: 8px; color: var(--text-primary); background: transparent; cursor: pointer; text-align: left; }
button.active { background: var(--color-primary-light); }
.command-icon { display: grid; width: 32px; height: 32px; place-items: center; border: 1px solid var(--border-color); border-radius: 7px; color: var(--text-secondary); font-size: 13px; font-weight: 700; }
strong, small { display: block; }
strong { font-size: 13px; }
small { margin-top: 2px; color: var(--text-muted-blue); font-size: 11px; }
.slash-empty { padding: 20px 10px; color: var(--text-muted-blue); font-size: 13px; text-align: center; }
</style>
