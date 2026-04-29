/**
 * Auth Store — 管理登录状态、token、用户信息
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import router from '@/router'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(null)
  const user = ref(null)

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
    accessToken.value = data.access_token
    user.value = data.user
    return data
  }

  async function logout() {
    try { await authApi.logout() } catch { /* ignore */ }
    accessToken.value = null
    user.value = null
    router.push('/login')
  }

  async function refreshToken() {
    const data = await authApi.refresh()
    accessToken.value = data.access_token
    return data.access_token
  }

  async function fetchMe() {
    const data = await authApi.getMe()
    user.value = data
    return data
  }

  return {
    accessToken, user, isLoggedIn, permissions, roles,
    hasPermission, hasAnyPermission, login, logout, refreshToken, fetchMe,
  }
})
