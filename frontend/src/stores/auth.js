/**
 * Auth Store — 管理登录状态、token、用户信息
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import router from '@/router'

// 模块级 token 存储，供 axios 拦截器同步读取（不依赖 Pinia 初始化顺序）
let _globalAccessToken = null
export function getAccessToken() { return _globalAccessToken }

/** 不依赖 Pinia store 实例，直接清除认证状态 */
export function clearAuthState() {
  _globalAccessToken = null
}

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(null)
  const user = ref(null)

  // 刷新完成前为 null（等待中），完成后为 true/false
  // 路由守卫通过此 Promise 等待初始化结束
  let _resolveInit
  const initPromise = new Promise(resolve => { _resolveInit = resolve })

  /** 同步更新全局 token（供 axios 拦截器读取） */
  function _setGlobalToken(token) {
    _globalAccessToken = token
    accessToken.value = token
  }

  const isLoggedIn = computed(() => !!accessToken.value)
  const permissions = computed(() => user.value?.permissions ?? [])
  const roles = computed(() => user.value?.roles ?? [])

  function hasPermission(permission) {
    if (roles.value.includes('super_admin')) return true
    return permissions.value.includes(permission)
  }

  function hasAnyPermission(perms) {
    return perms.some(p => hasPermission(p))
  }

  async function login(username, password) {
    const data = await authApi.login({ username, password })
    _setGlobalToken(data.access_token)
    user.value = data.user
    return data
  }

  async function logout() {
    try { await authApi.logout() } catch { /* ignore */ }
    _setGlobalToken(null)
    user.value = null
    // 清除欢迎弹框的会话标记，下次登录时重新弹出
    sessionStorage.removeItem('leshine_welcome_shown_session')
    router.push('/login')
  }

  async function refreshToken() {
    const data = await authApi.refresh()
    _setGlobalToken(data.access_token)
    return data.access_token
  }

  async function fetchMe() {
    const data = await authApi.getMe()
    user.value = data
    return data
  }

  /** App.vue 初始化完成后调用，解除路由守卫的等待 */
  function markInitialized() {
    _resolveInit()
  }

  return {
    accessToken, user, isLoggedIn, permissions, roles,
    hasPermission, hasAnyPermission, login, logout, refreshToken, fetchMe,
    initPromise, markInitialized,
  }
})
