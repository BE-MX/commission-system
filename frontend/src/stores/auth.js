/**
 * Auth Store — 管理登录状态、token、用户信息
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import router from '@/router'
import { removeSessionItem } from '@/utils/safeSessionStorage'

// 模块级 token 存储，供 axios 拦截器同步读取（不依赖 Pinia 初始化顺序）
function readStoredAccessToken() {
  try {
    return localStorage.getItem('ark_access_token')
  } catch {
    return null
  }
}

let _globalAccessToken = readStoredAccessToken()
// A fresh login/refresh is a new authority even if its token bytes are identical.
let _authEpoch = 0
let _authController = null
function beginAuthOperation() {
  _authController?.abort()
  _authController = new AbortController()
  return { epoch: ++_authEpoch, signal: _authController.signal }
}
export function getAuthEpoch() {
  return _authEpoch
}
export function isAuthOperationSuperseded(error) {
  return error?.code === 'ARK_AUTH_OPERATION_SUPERSEDED'
}
function supersededOperation() {
  const error = new Error('Authentication operation superseded')
  error.code = 'ARK_AUTH_OPERATION_SUPERSEDED'
  return error
}
export function getAccessToken() {
  if (_globalAccessToken) return _globalAccessToken
  _globalAccessToken = readStoredAccessToken()
  return _globalAccessToken
}

/** 不依赖 Pinia store 实例，直接清除认证状态 */
export function clearAuthState() {
  _authController?.abort()
  _authEpoch += 1
  _globalAccessToken = null
  localStorage.removeItem('ark_access_token')
}

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(getAccessToken())
  const user = ref(null)

  // 刷新完成前为 null（等待中），完成后为 true/false
  // 路由守卫通过此 Promise 等待初始化结束
  let _resolveInit
  const initPromise = new Promise(resolve => { _resolveInit = resolve })

  /** 同步更新全局 token（供 axios 拦截器读取） */
  function _setGlobalToken(token) {
    _authEpoch += 1
    _globalAccessToken = token
    accessToken.value = token
    if (token) {
      localStorage.setItem('ark_access_token', token)
    } else {
      localStorage.removeItem('ark_access_token')
    }
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

  // User intent starts a new generation before the transport can settle.
  // A superseded failure must not trigger a caller's recovery for a new login.
  async function currentResult(promise, isCurrent) {
    try {
      const result = await promise
      if (!isCurrent()) throw supersededOperation()
      return result
    } catch (error) {
      if (!isCurrent()) throw supersededOperation()
      throw error
    }
  }

  async function login(username, password) {
    const { epoch, signal } = beginAuthOperation()
    const data = await currentResult(authApi.login({ username, password }, { signal }), () => epoch === _authEpoch)
    if (epoch !== _authEpoch) throw supersededOperation()
    _setGlobalToken(data.access_token)
    user.value = data.user
    markInitialized()
    return data
  }

  async function logout(target = '/login') {
    const { epoch, signal } = beginAuthOperation()
    try { await authApi.logout({ signal }) } catch { /* Current logout clears local state even if transport fails. */ }
    if (epoch !== _authEpoch) return false
    _setGlobalToken(null)
    user.value = null
    removeSessionItem('leshine_welcome_shown_session')
    await router.push(target)
    return true
  }

  async function refreshToken(options) {
    const { epoch, signal } = beginAuthOperation()
    const data = await currentResult(authApi.refresh({ ...options, signal }), () => epoch === _authEpoch)
    if (epoch !== _authEpoch) throw supersededOperation()
    _setGlobalToken(data.access_token)
    return data.access_token
  }

  let meSequence = 0
  async function fetchMe() {
    const epoch = _authEpoch
    const sequence = ++meSequence
    const data = await currentResult(authApi.getMe(), () => epoch === _authEpoch && sequence === meSequence)
    if (epoch !== _authEpoch || sequence !== meSequence) throw supersededOperation()
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
