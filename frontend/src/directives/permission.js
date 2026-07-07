/**
 * 按钮级权限指令（权限重设计方案第五节）。
 *
 *   <el-button v-permission="'commission:write'">确认批次</el-button>
 *   <GlassButton v-any-permission="['expo:admin', 'expo:write']">编辑</GlassButton>
 *
 * 无权限时 display:none —— 刻意不用 el.remove()：移除不可逆（权限刷新后回不来），
 * 且打在组件根元素上时删除节点会让 Vue 后续 patch 报错。
 * super_admin 由 authStore.hasPermission 内部自动绕过。
 * kind=data 的权限（read_all/self_read 等）不要用本指令——它们控查询口径，不控显隐。
 */
import { useAuthStore } from '@/stores/auth'

function apply(el, granted) {
  if (granted) {
    if (el.dataset.vpermDisplay !== undefined) {
      el.style.display = el.dataset.vpermDisplay
      delete el.dataset.vpermDisplay
    }
  } else if (el.dataset.vpermDisplay === undefined) {
    el.dataset.vpermDisplay = el.style.display || ''
    el.style.display = 'none'
  }
}

function makeDirective(anyMode) {
  const evaluate = (el, binding) => {
    const auth = useAuthStore()
    const value = binding.value
    const granted = anyMode
      ? auth.hasAnyPermission(Array.isArray(value) ? value : [value])
      : auth.hasPermission(String(value))
    apply(el, granted)
  }
  return { mounted: evaluate, updated: evaluate }
}

export const vPermission = makeDirective(false)
export const vAnyPermission = makeDirective(true)

export function registerPermissionDirectives(app) {
  app.directive('permission', vPermission)
  app.directive('any-permission', vAnyPermission)
}
