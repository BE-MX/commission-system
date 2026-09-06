<template>
  <router-view />
  <GlobalLoading />
</template>

<script setup>
import { onMounted } from 'vue'
import GlobalLoading from '@/components/GlobalLoading.vue'
import { clearAuthState, useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

// 页面刷新时恢复登录态。
// 注意：accessToken 会从 localStorage 预恢复（供移动端 /m/ 共享），
// 所以 isLoggedIn=true 不代表用户信息已加载——只要 user 为空就必须拉 /me，
// 否则会卡在"半登录态"：token 在、权限为空，右上角显示"用户"、到处提示权限不足。
onMounted(async () => {
  if (!auth.user) {
    try {
      // 内存/localStorage 没有可用 token 时，先用 HttpOnly Cookie 换一个
      if (!auth.isLoggedIn) await auth.refreshToken()
      await auth.fetchMe()
    } catch {
      // localStorage 里的 token 可能已过期：用 refresh 换新后再拉一次
      try {
        await auth.refreshToken()
        await auth.fetchMe()
      } catch {
        // 彻底失败（未登录/会话过期/后端不可用）：清残留 token，
        // 由路由守卫带 redirect 参数跳登录页
        clearAuthState()
        auth.accessToken = null // clearAuthState 不触达 store ref，需同步复位 isLoggedIn
      }
    }
  }
  auth.markInitialized()
})
</script>

<style src="./styles/app.css"></style>
