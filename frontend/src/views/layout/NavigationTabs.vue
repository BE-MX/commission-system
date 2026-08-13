<template>
  <nav class="navigation-tabs" aria-label="已打开页面">
    <div class="tab-strip" role="tablist">
      <div
        v-for="tab in tabs"
        :key="tab.key"
        class="page-tab"
        :class="{ 'is-active': tab.key === activeKey }"
        :title="tab.title"
      >
        <button
          :id="getTabButtonId(tab.key)"
          :ref="element => setTabElement(tab.key, element)"
          class="tab-select"
          type="button"
          role="tab"
          :aria-selected="tab.key === activeKey"
          :aria-controls="tab.key === activeKey ? getTabPanelId(tab.key) : undefined"
          :tabindex="tab.key === activeKey ? 0 : -1"
          @click="$emit('select', tab.key)"
          @keydown="handleTabKeydown($event, tab.key)"
        >
          <span class="tab-dot" aria-hidden="true"></span>
          <span class="tab-title">{{ tab.title }}</span>
        </button>
        <button
          v-if="tab.closable"
          class="tab-close"
          type="button"
          :aria-label="`关闭${tab.title}`"
          @click.stop="$emit('close', tab.key)"
        >
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </div>
  </nav>
</template>

<script setup>
import { nextTick, onBeforeUpdate, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { getTabButtonId, getTabPanelId } from './navigationTabState'

const props = defineProps({
  tabs: { type: Array, required: true },
  activeKey: { type: String, required: true },
})

const emit = defineEmits(['select', 'close'])

const tabElements = new Map()

function setTabElement(key, element) {
  if (element) tabElements.set(key, element)
}

function handleTabKeydown(event, key) {
  const currentIndex = props.tabs.findIndex(tab => tab.key === key)
  if (currentIndex === -1) return

  let targetIndex = null
  if (event.key === 'ArrowRight') targetIndex = (currentIndex + 1) % props.tabs.length
  else if (event.key === 'ArrowLeft') targetIndex = (currentIndex - 1 + props.tabs.length) % props.tabs.length
  else if (event.key === 'Home') targetIndex = 0
  else if (event.key === 'End') targetIndex = props.tabs.length - 1

  if (targetIndex == null) return
  event.preventDefault()
  const targetKey = props.tabs[targetIndex].key
  tabElements.get(targetKey)?.focus()
  emit('select', targetKey)
}

onBeforeUpdate(() => tabElements.clear())

watch(() => props.activeKey, async key => {
  await nextTick()
  const reduceMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  tabElements.get(key)?.scrollIntoView({
    behavior: reduceMotion ? 'auto' : 'smooth',
    block: 'nearest',
    inline: 'nearest',
  })
}, { immediate: true })
</script>

<style scoped>
.navigation-tabs {
  min-width: 0;
  flex-shrink: 0;
  padding: 7px 18px 0;
  border-bottom: 1px solid var(--border-color);
  background: var(--toolbar-bg);
}
.tab-strip {
  display: flex;
  min-width: 0;
  gap: 5px;
  overflow-x: auto;
  overscroll-behavior-x: contain;
  scrollbar-width: thin;
  scrollbar-color: var(--scrollbar-thumb) transparent;
}
.page-tab {
  display: inline-flex;
  min-width: 112px;
  max-width: 210px;
  height: 36px;
  flex: 0 0 auto;
  align-items: center;
  padding: 0 6px 0 0;
  border: 1px solid transparent;
  border-bottom: 0;
  border-radius: 9px 9px 0 0;
  color: var(--text-secondary);
  background: transparent;
  transition: color 0.18s ease, background-color 0.18s ease, border-color 0.18s ease;
}
.page-tab:hover { color: var(--text-primary); background: var(--color-primary-light); }
.page-tab.is-active {
  color: var(--color-primary-hover);
  border-color: var(--border-color);
  background: var(--card-bg);
  box-shadow: inset 0 2px 0 var(--color-primary);
}
.tab-select {
  display: inline-flex;
  min-width: 0;
  height: 100%;
  flex: 1;
  align-items: center;
  gap: 7px;
  padding: 0 4px 0 10px;
  border: 0;
  color: inherit;
  background: transparent;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.tab-select:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; border-radius: 7px; }
.tab-dot {
  width: 6px;
  height: 6px;
  flex: 0 0 6px;
  border-radius: 50%;
  background: var(--text-muted);
  opacity: 0.45;
}
.is-active .tab-dot { background: var(--color-primary); opacity: 1; }
.tab-title { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.tab-close {
  display: inline-flex;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 5px;
  color: var(--text-muted);
  font-size: 11px;
}
.tab-close:hover { color: var(--color-danger); background: var(--color-danger-bg); }
.tab-close:focus-visible { outline: 1px solid var(--color-primary); outline-offset: 1px; }

@media (max-width: 640px) {
  .navigation-tabs { padding-inline: 8px; }
  .page-tab { min-width: 96px; max-width: 160px; }
}
@media (prefers-reduced-motion: reduce) {
  .page-tab { transition: none; }
}
</style>
