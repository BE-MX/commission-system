<template>
  <div class="navview">
    <div class="navtree">
      <template v-for="group in navGroups" :key="group.key">
        <div class="nav-group" :class="{ exempt: group.exempt }">{{ group.title }}</div>
        <div
          v-for="page in group.pages"
          :key="page.key"
          class="nav-item"
          :class="{ on: currentKey === page.key }"
          @click="currentKey = page.key"
        >
          <span :class="page.satisfied ? 'ok' : 'no'">{{ page.satisfied ? '✓' : '✗' }}</span>
          {{ page.title }}
        </div>
      </template>
    </div>
    <div v-if="current" class="navdetail">
      <div class="pg">
        {{ current.title }}
        <span :class="current.satisfied ? 'ok' : 'no'" class="state">
          {{ current.satisfied ? '✓ 当前勾选可见' : '✗ 当前勾选不可见' }}
        </span>
      </div>
      <div class="path">{{ current.path }}<template v-if="current.name"> · {{ current.name }}</template></div>
      <div v-if="current.exempt" class="exempt-note">⚠ 此入口不在侧边导航中（豁免登记）：{{ current.note }}</div>
      <div class="req">{{ current.required.length ? '可见需要（任一）：' : '无权限要求，所有登录用户可见' }}</div>
      <span
        v-for="code in current.required"
        :key="code"
        class="chip"
        :class="{ on: selectedSet.has(code) }"
        @click="$emit('locate', code)"
      >{{ code }}<i v-if="labelMap[code]" class="k">{{ labelMap[code] }}</i></span>
      <div v-if="current.required.length && !current.satisfied" class="warn">
        ⚠ 当前勾选集合不满足以上任一权限，「{{ current.title }}」将不出现在该角色的菜单中
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { NAV_ENTRIES, MENU_GROUPS } from '@/config/navigation'

const props = defineProps({
  /** 当前勾选的权限 code 数组 */
  selectedCodes: { type: Array, default: () => [] },
  /** code → 中文 label 映射（chip 角标） */
  labelMap: { type: Object, default: () => ({}) },
})
defineEmits(['locate'])

const currentKey = ref(null)

const selectedSet = computed(() => new Set(props.selectedCodes))

/** 选中页始终从最新 navGroups 派生，勾选变化后 ✓/✗ 实时刷新 */
const current = computed(() => {
  for (const g of navGroups.value) {
    const hit = g.pages.find(p => p.key === currentKey.value)
    if (hit) return hit
  }
  return null
})

/** 页面可见所需权限：菜单级优先，回退路由级（anyPermission 语义，单权限视为长度 1 的任一） */
function requiredOf(entry) {
  const m = entry.menu || {}
  if (m.anyPermission?.length) return m.anyPermission
  if (m.permission) return [m.permission]
  if (entry.anyPermission?.length) return entry.anyPermission
  if (entry.permission) return [entry.permission]
  return []
}

/** NAV_ENTRIES 之外的权限入口豁免登记（反查视角盲区补齐） */
const EXEMPT_PAGES = [
  {
    key: 'exempt-expo-kiosk', title: '展会试戴 kiosk', path: '/expo/kiosk', name: 'ExpoKiosk',
    required: ['expo:write'], exempt: true,
    note: '展位 iPad 全屏页在 router 顶层注册，勾掉 expo:write 菜单无变化但展位会被拦',
  },
  {
    key: 'exempt-mobile-asset', title: '移动端素材（/m/）', path: '/m/', name: '',
    required: ['asset:read'], exempt: true,
    note: '移动端独立页面依赖 asset:read，勾掉后手机端素材库不可用',
  },
]

const navGroups = computed(() => {
  const groups = []
  // 顶级页面（无分组，如工作台）
  const topPages = NAV_ENTRIES.filter(e => e.menu && !e.menu.group && !e.hideInMenu)
  if (topPages.length) {
    groups.push({
      key: '_top', title: '通用',
      pages: topPages.map(e => buildPage(e)),
    })
  }
  for (const [key, group] of Object.entries(MENU_GROUPS)) {
    const pages = NAV_ENTRIES
      .filter(e => e.menu?.group === key && !e.hideInMenu)
      .map(e => buildPage(e))
    if (pages.length) groups.push({ key, title: group.title, pages })
  }
  groups.push({
    key: '_exempt', title: '豁免登记 · 导航之外', exempt: true,
    pages: EXEMPT_PAGES.map(p => ({ ...p, satisfied: satisfied(p.required) })),
  })
  return groups
})

function buildPage(entry) {
  const required = requiredOf(entry)
  return {
    key: entry.name || entry.path,
    title: entry.menu?.title || entry.title,
    path: entry.path,
    name: entry.name,
    required,
    satisfied: satisfied(required),
    exempt: false,
  }
}

function satisfied(required) {
  if (!required.length) return true
  return required.some(code => selectedSet.value.has(code))
}
</script>

<style scoped>
.navview {
  display: grid;
  grid-template-columns: 280px 1fr;
  min-height: 320px;
  border: 1px solid var(--border-color, #e2e5ef);
  border-radius: 10px;
  overflow: hidden;
}
.navtree {
  border-right: 1px solid var(--border-color, #e2e5ef);
  padding: 16px;
  overflow-y: auto;
  max-height: 62vh;
}
.nav-group {
  font-size: 12px;
  color: #8b6914;
  letter-spacing: 0.15em;
  margin: 12px 0 6px;
  font-weight: 700;
}
.nav-group.exempt { color: var(--color-danger, #dc3545); }
.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  padding: 6px 10px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--text-primary);
}
.nav-item:hover { background: #fffdf6; }
.nav-item.on { background: var(--color-primary-light, rgba(212, 148, 28, 0.08)); }
.ok { color: var(--color-success, #2d9f6f); font-weight: 700; }
.no { color: #cbd5e1; font-weight: 700; }

.navdetail { padding: 20px 26px; }
.navdetail .pg { font-weight: 700; font-size: 15px; margin-bottom: 4px; color: var(--text-primary); }
.navdetail .pg .state { font-size: 13px; margin-left: 8px; }
.navdetail .path { font-size: 12px; color: var(--text-secondary, #718096); margin-bottom: 16px; }
.req { font-size: 12px; color: var(--text-secondary, #718096); margin: 14px 0 6px; }
.warn { margin-top: 18px; font-size: 12px; color: #8b6914; line-height: 1.7; }
.exempt-note { font-size: 12px; color: var(--color-danger, #dc3545); margin-bottom: 10px; line-height: 1.7; }

.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  border: 1px solid var(--border-color, #e2e5ef);
  border-radius: 12px;
  padding: 2px 9px;
  margin: 2px;
  color: var(--text-secondary, #718096);
  background: #fafbfe;
  cursor: pointer;
}
.chip.on {
  border-color: var(--color-primary);
  color: var(--color-primary-hover, #bb8218);
  background: var(--color-primary-light, rgba(212, 148, 28, 0.08));
}
.chip .k { font-size: 9px; background: #eef1f7; border-radius: 6px; padding: 0 4px; color: #8b95a5; font-style: normal; }
.chip.on .k { background: #f7e8c8; color: #8b6914; }
</style>
