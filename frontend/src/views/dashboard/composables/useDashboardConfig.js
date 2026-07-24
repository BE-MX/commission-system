/**
 * 工作台布局配置 composable — 加载/合并/编辑态/保存
 *
 * 数据流：localStorage 镜像先渲染（防排序闪跳）→ GET 服务端真相覆盖 → 写回镜像。
 * 可见卡片 = 注册表 ∩ 权限 ∩ 用户配置（hidden/order）。
 * 未知 key（注册表已下线）被忽略；注册表新增卡片不在 order 里 → 追加尾部默认可见。
 */
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import {
  getDashboardPreference,
  resetDashboardPreference,
  saveDashboardPreference,
} from '@/api/dashboard'
import { msgSuccess } from '@/utils/feedback'

const STORAGE_PREFIX = 'ark_dashboard_prefs_'

function emptySection() {
  return { hidden: [], order: [] }
}

// localStorage 镜像没有 pydantic 保形状——合法 JSON 但字段类型损坏（截断/篡改/
// 版本回滚）不能让全员落地页渲染炸掉，数组字段必须逐个兜底（对抗性审查 P1 2026-07-25）
function normalizeList(value) {
  return Array.isArray(value) ? value.filter(item => typeof item === 'string') : []
}

function normalizeSection(raw) {
  const section = raw && typeof raw === 'object' ? raw : {}
  return { hidden: normalizeList(section.hidden), order: normalizeList(section.order) }
}

function normalizePrefs(raw) {
  if (!raw || typeof raw !== 'object') return null
  return {
    version: Number.isInteger(raw.version) && raw.version >= 1 ? raw.version : 1,
    metrics: normalizeSection(raw.metrics),
    actions: normalizeSection(raw.actions),
  }
}

export function useDashboardConfig() {
  const authStore = useAuthStore()

  const prefs = ref(null)      // 服务端真相；null = 默认布局（注册表顺序、全部可见）
  const editing = ref(false)
  const draft = ref(null)      // 编辑中的副本，保存前不落地
  const saving = ref(false)

  const storageKey = () => STORAGE_PREFIX + (authStore.user?.id ?? 'anon')

  function readCache() {
    try {
      const raw = localStorage.getItem(storageKey())
      if (raw) prefs.value = normalizePrefs(JSON.parse(raw))
    } catch { /* 缓存损坏按默认布局渲染 */ }
  }

  function writeCache(value) {
    try {
      if (value) localStorage.setItem(storageKey(), JSON.stringify(value))
      else localStorage.removeItem(storageKey())
    } catch { /* 隐私模式等写失败不影响功能 */ }
  }

  async function loadFromServer() {
    try {
      const res = await getDashboardPreference()
      prefs.value = normalizePrefs(res.data)
      writeCache(prefs.value)
    } catch { /* 拦截器已提示；离线时沿用镜像布局 */ }
  }

  /**
   * 排列一个分区的卡片：权限过滤 → order 排序（未知 key 忽略、新卡片追尾）→
   * 非编辑态再过滤 hidden。编辑态返回全量（含隐藏卡，渲染层降透明度）。
   */
  function arrange(sectionKey, cards) {
    const source = editing.value ? draft.value : prefs.value
    const section = source?.[sectionKey] || emptySection()
    const allowed = cards.filter(c => !c.perms || authStore.hasAnyPermission(c.perms))
    const orderIndex = new Map(section.order.map((k, i) => [k, i]))
    const sorted = [...allowed].sort((a, b) => {
      const ai = orderIndex.has(a.key) ? orderIndex.get(a.key) : Infinity
      const bi = orderIndex.has(b.key) ? orderIndex.get(b.key) : Infinity
      return ai - bi // sort 稳定：都是 Infinity 时保持注册表相对顺序
    })
    if (editing.value) return sorted
    const hidden = new Set(section.hidden)
    return sorted.filter(c => !hidden.has(c.key))
  }

  function isHidden(sectionKey, key) {
    const source = editing.value ? draft.value : prefs.value
    return (source?.[sectionKey]?.hidden || []).includes(key)
  }

  // ── 编辑流 ─────────────────────────────────────────────
  function enterEdit() {
    const base = prefs.value || { version: 1, metrics: emptySection(), actions: emptySection() }
    draft.value = JSON.parse(JSON.stringify(base))
    editing.value = true
  }

  function cancelEdit() {
    editing.value = false
    draft.value = null
  }

  function toggleHidden(sectionKey, key) {
    if (!draft.value) return
    const hidden = draft.value[sectionKey].hidden
    const idx = hidden.indexOf(key)
    if (idx >= 0) hidden.splice(idx, 1)
    else hidden.push(key)
  }

  function reorder(sectionKey, orderedKeys) {
    if (!draft.value) return
    draft.value[sectionKey].order = orderedKeys
  }

  async function saveEdit() {
    if (!draft.value) return
    saving.value = true
    try {
      const res = await saveDashboardPreference(draft.value)
      prefs.value = normalizePrefs(res.data)
      writeCache(prefs.value)
      editing.value = false
      draft.value = null
      msgSuccess('保存布局')
    } catch { /* 拦截器已提示；保持编辑态不丢 draft */ } finally {
      saving.value = false
    }
  }

  async function resetToDefault() {
    saving.value = true
    try {
      await resetDashboardPreference()
      prefs.value = null
      writeCache(null)
      editing.value = false
      draft.value = null
      msgSuccess('恢复默认布局')
    } catch { /* 拦截器已提示 */ } finally {
      saving.value = false
    }
  }

  const dirty = computed(() => {
    if (!editing.value || !draft.value) return false
    const base = prefs.value || { version: 1, metrics: emptySection(), actions: emptySection() }
    return JSON.stringify(draft.value) !== JSON.stringify(base)
  })

  onMounted(() => {
    readCache()
    loadFromServer()
  })

  return {
    prefs, editing, draft, saving, dirty,
    arrange, isHidden,
    enterEdit, cancelEdit, toggleHidden, reorder, saveEdit, resetToDefault,
  }
}
