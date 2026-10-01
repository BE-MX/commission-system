import { readFileSync } from 'node:fs'
import { parse } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import { useListPage } from '../../src/composables/useListPage.js'
import { useCursorResource } from '../../src/composables/useCursorResource.js'
import { clearListResource, watchListResourceScope } from '../../src/composables/useListResourceScope.js'
import { useAsyncResource } from '../../src/composables/useAsyncResource.js'
import { useTableSort } from '../../src/composables/useTableSort.js'
import * as money from '../../src/utils/money.js'
import * as status from '../../src/utils/status.js'
import * as datetime from '../../src/utils/datetime.js'

export function viewController(t, path, names, extraModules = {}) {
  const scope = Vue.effectScope(), messages = []
  const auth = Vue.reactive({ user: { id: 7 }, hasPermission: () => true })
  const modules = {
    vue: { ...Vue, onMounted() {}, onUnmounted() {}, onBeforeUnmount() {}, onActivated() {}, onDeactivated() {} },
    'vue-router': { useRoute: () => Vue.reactive({ params: {}, query: {} }), useRouter: () => ({ push() {} }) },
    '@/stores/auth': { useAuthStore: () => auth },
    '@/composables/useListPage': { useListPage }, '@/composables/useAsyncResource': { useAsyncResource },
    '@/composables/useCursorResource': { useCursorResource }, '@/composables/useListResourceScope': { clearListResource, watchListResourceScope },
    '@/composables/useTableSort': { useTableSort }, '@/composables/useTableView': { useTableView: (_, columns = []) => ({
      visibleKeys: Vue.ref(columns.map(column => column.key)), density: Vue.ref('normal'), densityClass: Vue.ref(''),
      panelRef: Vue.ref(null), isFullscreen: Vue.ref(false), toggleFullscreen() {},
    }) },
    '@/utils/money': money, '@/utils/status': status, '@/utils/datetime': datetime,
    '@/utils/feedback': { msgSuccessText: text => messages.push(text), msgSuccess: text => messages.push(text), msgError: text => messages.push(text), msgWarning: text => messages.push(text), confirmAction: async () => {} },
    ...extraModules,
  }
  const content = readFileSync(new URL(path, import.meta.url), 'utf8')
  const script = (path.endsWith('.vue') ? parse(content).descriptor.scriptSetup.content : content)
    .replace(/import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/g, (_, raw, key) => {
      modules[key] ??= {}
      const binding = raw.trim()
      if (binding.startsWith('* as ')) return 'const ' + binding.slice(5) + ' = modules[' + JSON.stringify(key) + '];'
      const declaration = binding.startsWith('{') ? binding.replace(/\bas\b/g, ':') : '{ default: ' + binding + ' }'
      return 'const ' + declaration + ' = modules[' + JSON.stringify(key) + '];'
    }).replace(/export (?=(?:function|const))/g, '')
  const vm = scope.run(() => new Function('modules', 'defineProps', 'defineEmits', script + '\nreturn { ' + names + ' };')(
    modules, () => extraModules['@props'] || {}, () => (event, ...args) => messages.push({ event, args }),
  ))
  t.after(() => scope.stop())
  return { vm, auth, messages }
}

