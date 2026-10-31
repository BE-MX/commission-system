<template>
  <GlassButton variant="ghost" :left-icon="Search" class="quick-navigation-trigger" aria-label="打开快捷导航" @click="openPanel">
    <span class="quick-navigation-label">搜索页面</span><kbd class="quick-navigation-key">{{ shortcut }}</kbd>
  </GlassButton>
  <el-dialog v-model="open" title="快捷导航" width="640px" style="max-width: calc(100vw - 24px)" class="quick-navigation-dialog" append-to-body destroy-on-close
    @opened="focusSearch" @closed="restoreFocus">
    <el-input ref="input" v-model="query" clearable :prefix-icon="Search" placeholder="搜索页面或分组"
      aria-label="搜索页面或分组" role="combobox" aria-autocomplete="list" :aria-expanded="open" :aria-controls="listId"
      :aria-activedescendant="matches.length ? `${listId}-${active}` : undefined" @keydown="onInputKey" />
    <ul :id="listId" ref="listElement" class="quick-navigation-results" role="listbox" aria-label="可访问页面">
      <li v-for="(item, index) in matches" :id="`${listId}-${index}`" :key="item.path" role="option"
        :aria-selected="index === active" class="quick-navigation-option" :class="{ active: index === active }"
        @mouseenter="active = index" @mousedown.prevent @click="navigate(item)">
        <el-icon aria-hidden="true"><component :is="item.icon || Document" /></el-icon>
        <span class="quick-navigation-text"><strong>{{ item.title }}</strong><small>{{ item.groupTitle }}</small></span>
        <span v-if="item.external" class="quick-navigation-external">新窗口<el-icon aria-hidden="true"><TopRight /></el-icon></span>
      </li>
      <li v-if="!matches.length" class="quick-navigation-empty" role="presentation">未找到可访问的页面</li>
    </ul>
    <div class="quick-navigation-help" aria-hidden="true">↑ ↓ 选择 · Enter 打开 · Esc 关闭</div>
  </el-dialog>
</template>
<script setup>
import { computed, getCurrentInstance, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { isNavigationFailure, useRoute, useRouter } from 'vue-router'
import { Document, Search, TopRight } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAuthStore } from '@/stores/auth'
import { MENU_GROUPS, NAV_ENTRIES } from '@/config/navigation'
import { msgError } from '@/utils/feedback'
import { accessibleNavigationSections, isQuickNavigationShortcut, quickNavigationItems } from './navigationSearch'

const auth = useAuthStore(), router = useRouter(), route = useRoute()
const open = ref(false), query = ref(''), active = ref(0), input = ref(null), listElement = ref(null)
const listId = `quick-navigation-${getCurrentInstance().uid}`
const shortcut = /Mac|iPhone|iPad/.test(globalThis.navigator?.platform || '') ? '⌘ K' : 'Ctrl K'
let trigger = null
const sections = computed(() => accessibleNavigationSections(NAV_ENTRIES, MENU_GROUPS, auth))
const matches = computed(() => quickNavigationItems(sections.value, query.value))
watch(matches, () => { active.value = 0 })
watch(() => auth.user?.id, () => { open.value = false; query.value = '' })
function openPanel(event) {
  if (!auth.user) return
  trigger = event?.currentTarget || document.activeElement
  query.value = ''
  active.value = 0
  open.value = true
}
function focusSearch() { input.value?.focus() }
function restoreFocus() { if (trigger?.isConnected) trigger.focus() }
async function navigate(item) {
  // Re-resolve after permission changes; never trust a previously rendered result.
  const current = quickNavigationItems(sections.value).find(entry => entry.path === item.path)
  if (!current) return
  if (current.external) {
    window.open(current.path, '_blank', 'noopener,noreferrer')
    open.value = false
    return
  }
  if (route.path === current.path) { open.value = false; return }
  try {
    const failure = await router.push(current.path)
    if (!isNavigationFailure(failure)) open.value = false
  } catch (error) { msgError('页面打开失败，请重试', error) }
}
async function onInputKey(event) {
  if (event.isComposing || event.keyCode === 229) return
  if (event.key === 'Enter') {
    event.preventDefault()
    if (matches.value[active.value]) navigate(matches.value[active.value])
    return
  }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || !matches.value.length) return
  event.preventDefault()
  const last = matches.value.length - 1
  active.value = event.key === 'Home' ? 0 : event.key === 'End' ? last : (active.value + (event.key === 'ArrowDown' ? 1 : last)) % matches.value.length
  await nextTick()
  listElement.value?.children[active.value]?.scrollIntoView({ block: 'nearest' })
}
function onShortcut(event) {
  if (!isQuickNavigationShortcut(event) || !auth.user) return
  const editing = event.target?.isContentEditable || event.target?.closest?.('[contenteditable="true"]')
  const otherDialog = !open.value && [...document.querySelectorAll('[role="dialog"], [role="alertdialog"]')].some(element => element.getClientRects().length)
  if (editing || otherDialog) return
  event.preventDefault()
  if (open.value) open.value = false
  else openPanel()
}
onMounted(() => document.addEventListener('keydown', onShortcut))
onBeforeUnmount(() => document.removeEventListener('keydown', onShortcut))
</script>
<style scoped>
.quick-navigation-trigger { gap: 8px; }
.quick-navigation-key { font-family: inherit; font-size: 11px; color: var(--text-secondary); border: 1px solid var(--border-color); padding: 1px 4px; border-radius: 4px; }
.quick-navigation-results { list-style: none; padding: 0; margin: 12px 0 0; max-height: min(420px, 50dvh); overflow-y: auto; }
.quick-navigation-option { display: flex; align-items: center; gap: 12px; padding: 10px 12px; min-height: 48px; border-radius: 8px; color: var(--text-primary); cursor: pointer; }
.quick-navigation-option.active { background: var(--color-primary-light); outline: 1px solid var(--border-color); outline-offset: -1px; }
.quick-navigation-text { display: flex; flex-direction: column; min-width: 0; gap: 3px; }
.quick-navigation-text strong { font-size: 14px; font-weight: 500; }
.quick-navigation-text small { font-size: 12px; color: var(--text-secondary); }
.quick-navigation-external { display: inline-flex; align-items: center; gap: 4px; margin-left: auto; color: var(--text-secondary); font-size: 12px; white-space: nowrap; }
.quick-navigation-empty { padding: 28px 12px; text-align: center; color: var(--text-secondary); }
.quick-navigation-help { border-top: 1px solid var(--border-color); padding-top: 10px; margin-top: 8px; color: var(--text-secondary); font-size: 12px; }
@media (max-width: 640px) { .quick-navigation-label, .quick-navigation-key { display: none; } }
</style>
