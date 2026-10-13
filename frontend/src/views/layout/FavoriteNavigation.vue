<template>
  <section class="favorite-navigation" :class="{ collapsed }" aria-label="常用导航" :aria-busy="loading || saving">
    <div v-if="!collapsed" class="favorite-heading">
      <span><el-icon><Star /></el-icon> 常用导航</span>
      <button type="button" class="favorite-manage" aria-label="管理常用导航" title="管理常用导航" @click="managerOpen = true">
        <el-icon><Setting /></el-icon>
      </button>
    </div>
    <p v-if="!collapsed && loading" class="favorite-hint" role="status">正在加载…</p>
    <p v-else-if="!collapsed && !items.length && !error" class="favorite-hint">
      <button type="button" class="favorite-empty-add" @click="managerOpen = true">＋ 添加常用导航</button>
    </p>
    <div v-if="!collapsed && error" class="favorite-error" role="status">
      {{ error }} <button type="button" :disabled="loading || saving" @click="load">重试读取</button>
    </div>
    <draggable :model-value="items" item-key="name" handle=".favorite-drag" :disabled="collapsed || locked"
      :animation="0" :delay="180" :delay-on-touch-only="true" :touch-start-threshold="4"
      class="favorite-list" ghost-class="favorite-ghost" @update:model-value="reorder">
      <template #item="{ element: item, index }">
        <div class="favorite-row" :data-favorite-key="item.name">
          <button v-if="!collapsed" type="button" class="favorite-drag" :disabled="locked"
            :aria-label="`调整${item.title}顺序`" title="拖拽排序；Alt + 上下方向键调整顺序"
            @keydown.alt.up.prevent="move(index, -1, $event)" @keydown.alt.down.prevent="move(index, 1, $event)">
            <el-icon><Rank /></el-icon>
          </button>
          <component :is="item.external ? 'a' : RouterLink"
            v-bind="item.external ? { href: item.path, target: '_blank', rel: 'noopener' } : { to: item.path }" class="favorite-link"
            :class="{ 'is-active': !item.external && activePath === item.path }"
            :aria-current="!item.external && activePath === item.path ? 'page' : undefined"
            :aria-label="item.title" :title="item.title">
            <el-icon><component :is="item.icon" /></el-icon>
            <span v-if="!collapsed">{{ item.title }}</span>
            <el-icon v-if="!collapsed && item.external" class="favorite-external"><TopRight /></el-icon>
          </component>
        </div>
      </template>
    </draggable>
    <span v-if="!collapsed && saving" class="favorite-hint" role="status">正在保存…</span>

    <el-dialog v-model="managerOpen" title="管理常用导航" width="480px" append-to-body>
      <p class="manager-hint">勾选即可添加，取消勾选即可移除。返回导航栏拖拽调整顺序。</p>
      <el-input v-model="query" :prefix-icon="Search" clearable placeholder="搜索页面或分组" aria-label="搜索常用导航候选" />
      <p v-if="error" class="manager-error" role="status">{{ error }}
        <GlassButton variant="link" :disabled="loading || saving" @click="load">重试读取</GlassButton>
      </p>
      <div class="favorite-choices" v-loading="loading">
        <label v-for="item in choices" :key="item.name" class="favorite-choice">
          <input type="checkbox" :checked="keys.includes(item.name)" :disabled="locked" :aria-label="item.title" @change="toggle(item.name)" />
          <span>{{ item.title }}</span><small>{{ item.groupTitle }}</small>
        </label>
        <p v-if="!choices.length" class="manager-hint">未找到可添加的导航</p>
      </div>
      <template #footer>
        <span class="manager-hint" role="status">{{ saving ? '正在保存…' : `已添加 ${items.length} 项` }}</span>
        <GlassButton variant="primary" :disabled="saving" @click="managerOpen = false">完成</GlassButton>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import draggable from 'vuedraggable'
import { Rank, Search, Setting, Star, TopRight } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import GlassButton from '@/components/GlassButton.vue'
import { useFavoriteNavigation } from './useFavoriteNavigation'
import { normalizeNavigationQuery } from './navigationSearch'

const props = defineProps({ collapsed: Boolean, available: { type: Array, required: true } })
const auth = useAuthStore(), route = useRoute(), managerOpen = ref(false), query = ref('')
const available = computed(() => props.available)
const { keys, items, loading, saving, locked, error, load, toggle, reorder } = useFavoriteNavigation(auth, available)
const activePath = computed(() => route.meta.activeMenu || route.path)
const choices = computed(() => {
  const search = normalizeNavigationQuery(query.value)
  return available.value.filter(item => normalizeNavigationQuery(`${item.title} ${item.groupTitle} ${item.path}`).includes(search))
})
watch(managerOpen, () => { query.value = '' })
watch(() => auth.user?.id, () => { managerOpen.value = false })

async function move(index, direction, event) {
  if (locked.value) return
  const target = index + direction
  if (target < 0 || target >= items.value.length) return
  const handle = event.currentTarget
  const order = [...items.value]
  ;[order[index], order[target]] = [order[target], order[index]]
  await reorder(order)
  await nextTick()
  if (handle.isConnected) handle.focus()
}
</script>

<style scoped>
.favorite-navigation { position: relative; z-index: 1; flex-shrink: 0; margin: 8px 12px 0; padding-bottom: 8px; border-bottom: 1px solid var(--sidebar-glow-gold); color: var(--text-on-dark); }
.favorite-heading { display: flex; align-items: center; justify-content: space-between; padding-left: 8px; font-size: 12px; font-weight: 600; }
.favorite-heading > span { display: inline-flex; align-items: center; gap: 7px; }
.favorite-heading .el-icon { color: var(--color-gold); }
.favorite-manage, .favorite-drag { display: grid; place-items: center; flex-shrink: 0; width: 28px; height: 32px; padding: 0; border: 0; border-radius: 6px; background: transparent; color: inherit; cursor: pointer; }
.favorite-manage:hover, .favorite-drag:hover { background: var(--sidebar-glow-gold); }
.favorite-manage:focus-visible, .favorite-drag:focus-visible, .favorite-link:focus-visible, .favorite-empty-add:focus-visible { outline: 2px solid var(--color-gold); outline-offset: 1px; }
.favorite-drag { cursor: grab; touch-action: none; color: var(--color-gold); }
.favorite-drag:active { cursor: grabbing; }
.favorite-drag:disabled { opacity: 0.4; cursor: default; }
.favorite-list { max-height: 32vh; overflow-y: auto; overscroll-behavior: contain; }
.favorite-row { display: flex; align-items: center; min-height: 38px; border-radius: 8px; }
.favorite-link { display: flex; align-items: center; gap: 9px; min-width: 0; flex: 1; height: 38px; padding: 0 8px; border-radius: 8px; color: inherit; font-family: var(--font-display); font-size: 13px; text-decoration: none; }
.favorite-link > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.favorite-link .el-icon { flex-shrink: 0; }
.favorite-link:hover { background: var(--sidebar-glow-slate); }
.favorite-link.is-active { color: var(--color-gold); background: var(--sidebar-glow-gold); font-weight: 600; }
.favorite-external { margin-left: auto; font-size: 11px; }
.favorite-ghost { opacity: 0.4; background: var(--sidebar-glow-gold); }
.favorite-hint { display: block; margin: 6px 8px; font-size: 12px; line-height: 1.5; }
.favorite-empty-add, .favorite-error button { border: 0; padding: 4px 0; background: transparent; color: var(--color-gold); font: inherit; cursor: pointer; }
.favorite-error { margin: 6px 8px; font-size: 12px; line-height: 1.6; }
.collapsed { margin: 8px 8px 0; }
.collapsed .favorite-link { justify-content: center; padding: 0; }
.manager-hint { margin: 0 0 14px; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.favorite-choices { display: flex; flex-direction: column; gap: 4px; max-height: 48vh; overflow-y: auto; margin: 14px 0 0; }
.favorite-choice { display: flex; align-items: center; gap: 10px; width: 100%; margin: 0; min-height: 36px; cursor: pointer; }
.favorite-choice input { width: 16px; height: 16px; accent-color: var(--color-primary); flex-shrink: 0; }
.favorite-choice input:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
.favorite-choice span { font-size: 14px; }
.favorite-choice small { margin-left: auto; color: var(--text-secondary); white-space: nowrap; }
.manager-error { color: var(--button-danger-text); font-size: 12px; }
</style>
