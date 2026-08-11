export const LIBRARY_CATEGORIES = Object.freeze({
  company: Object.freeze({ label: '公司级', tone: 'company' }),
  department: Object.freeze({ label: '部门级', tone: 'department' }),
  personal: Object.freeze({ label: '个人级', tone: 'personal' }),
})

export const SIDEBAR_COLLAPSED_KEY = 'knowledge-sidebar-collapsed'

export function readSidebarCollapsed(storage = window.localStorage) {
  try {
    return storage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

export function writeSidebarCollapsed(collapsed, storage = window.localStorage) {
  try {
    storage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed === true ? 'true' : 'false')
  } catch {
    // Ignore unavailable preference storage.
  }
}

export function isDuplicateMember(members, userId) {
  return members.some(member => member.user_id === userId)
}

export function isTextOverflowing(element) {
  return Boolean(element && element.scrollWidth > element.clientWidth)
}

export function overflowTooltipVisible({ overflowing, hovering, focused }) {
  return Boolean(overflowing && (hovering || focused))
}

