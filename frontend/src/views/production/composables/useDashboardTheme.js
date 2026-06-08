import { ref, computed, onMounted } from 'vue'

const STORAGE_KEY = 'ark-dashboard-theme'
const theme = ref('dark') // 全局单例

export function useDashboardTheme() {
  function applyTheme(t) {
    theme.value = t
    document.documentElement.setAttribute('data-theme', t)
    localStorage.setItem(STORAGE_KEY, t)
  }

  // toggle / toggleTheme 两个别名都可以用
  function toggle() {
    applyTheme(theme.value === 'dark' ? 'light' : 'dark')
  }
  const toggleTheme = toggle

  // isDark computed 方便模板直接用
  const isDark = computed(() => theme.value === 'dark')

  onMounted(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    applyTheme(saved || 'dark')
  })

  // ECharts 主题名：dark 主题用 'dark'，light 主题用 ''（默认亮色）
  function getEchartsTheme() {
    return theme.value === 'dark' ? 'dark' : ''
  }

  return { theme, isDark, toggle, toggleTheme, applyTheme, getEchartsTheme }
}
