<template>
  <div class="relative w-screen h-screen overflow-hidden bg-[#0a0a0f]">
    <div class="absolute top-0 left-0 h-full w-full lg:w-[55%]" style="z-index: 0;">
      <WorldMapCanvas />
    </div>

    <!-- Content Overlay -->
    <div class="relative z-10 flex h-full">
      <!-- Left Panel - Brand Zone -->
      <div
        class="hidden lg:flex flex-col justify-between w-[55%] h-full p-10 will-animate animate-fade-in"
      >
        <!-- Brand Header -->
        <div class="pt-4 will-animate animate-fade-in-left delay-200">
          <span class="text-2xl font-semibold italic text-[#d4af6e]">leShine</span>
          <span class="ml-2 text-sm text-white/40 tracking-[0.15em]">ARK PLATFORM</span>
        </div>

        <!-- Main Title Block -->
        <div class="flex-1 flex flex-col justify-center will-animate animate-fade-in-left delay-350">
          <h1 class="text-5xl font-bold text-[#f0f0f5] tracking-tight">
            莱莎方舟综合管理平台
          </h1>
          <p class="mt-4 text-lg text-white/50 tracking-wider">
            LeShine Hair Management Platform
          </p>

          <!-- Statistics Row -->
          <div class="flex gap-6 mt-12 will-animate animate-fade-in-left delay-500">
            <div class="glass-card px-6 py-4 flex items-center gap-3">
              <svg class="w-5 h-5 text-[#d4af6e]" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
              </svg>
              <span class="text-sm text-white/70">全球精品发制品</span>
            </div>
            <div class="glass-card px-6 py-4 flex items-center gap-3">
              <span class="text-3xl font-bold font-mono text-[#d4af6e]">1200+</span>
              <span class="text-sm text-white/70">数据驱动 · 智慧管理</span>
            </div>
            <div class="glass-card px-6 py-4 flex items-center gap-3">
              <span class="text-3xl font-bold font-mono text-[#d4af6e]">568</span>
              <span class="text-sm text-white/70">合作客户</span>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="pb-4 will-animate animate-fade-in-left delay-650">
          <p class="text-xs text-white/30">
            © 2026 LeShine Co., Ltd. All Rights Reserved.
          </p>
        </div>
      </div>

      <!-- Right Panel - Login Form -->
      <div class="flex-1 flex items-center justify-center p-6">
        <div class="glass-card gold-glow w-full max-w-[420px] p-10 md:p-12 will-animate animate-fade-in-right delay-300">
          <!-- Mobile brand (visible only on small screens) -->
          <div class="lg:hidden mb-8 text-center">
            <span class="text-xl font-semibold italic text-[#d4af6e]">leShine</span>
            <span class="ml-1 text-xs text-white/40">Hair</span>
            <p class="mt-2 text-xs text-white/50">莱莎方舟综合管理平台</p>
          </div>

          <!-- Form Header -->
          <div class="mb-8">
            <div class="flex items-baseline gap-2 mb-3">
              <span class="text-2xl font-semibold italic text-[#d4af6e]">leShine</span>
              <span class="text-sm text-white/50">Hair</span>
            </div>
            <p class="text-sm text-white/60">欢迎登录莱莎方舟综合管理平台</p>
          </div>

          <form @submit.prevent="handleSubmit">
            <!-- Username -->
            <div class="relative">
              <svg class="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
              </svg>
              <input
                v-model="username"
                type="text"
                placeholder="请输入用户名"
                class="tech-input w-full h-12 pl-12 pr-4 text-sm"
              />
            </div>

            <!-- Password -->
            <div class="relative mt-4">
              <svg class="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
              </svg>
              <input
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                placeholder="请输入密码"
                class="tech-input w-full h-12 pl-12 pr-12 text-sm"
              />
              <button
                type="button"
                @click="showPassword = !showPassword"
                class="absolute right-4 top-1/2 -translate-y-1/2 text-white/20 hover:text-white/50 transition-colors"
              >
                <svg v-if="showPassword" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"/>
                </svg>
                <svg v-else class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
                </svg>
              </button>
            </div>

            <!-- Options -->
            <div class="flex items-center justify-between mt-5">
              <label class="flex items-center gap-2 cursor-pointer group">
                <div
                  @click="remember = !remember"
                  :class="[
                    'w-4 h-4 rounded border transition-all duration-200 flex items-center justify-center',
                    remember
                      ? 'bg-[#d4af6e] border-[#d4af6e]'
                      : 'border-white/30 group-hover:border-white/50'
                  ]"
                >
                  <svg v-if="remember" class="w-3 h-3 text-[#0a0a0f]" viewBox="0 0 12 12" fill="none">
                    <path d="M2 6L5 9L10 3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </div>
                <span class="text-sm text-white/60">记住登录状态</span>
              </label>
              <a href="#" class="text-sm text-[#d4af6e] hover:underline transition-all">
                忘记密码?
              </a>
            </div>

            <!-- Submit -->
            <button
              type="submit"
              class="tech-btn-primary w-full h-12 mt-8 text-base font-semibold"
            >
              登 录
            </button>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import WorldMapCanvas from '@/components/WorldMapCanvas.vue'

const router = useRouter()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const remember = ref(false)

const handleSubmit = async () => {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }

  try {
    await authStore.login(username.value, password.value)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (error) {
    ElMessage.error(error.message || '登录失败，请检查用户名和密码')
  }
}
</script>

<style scoped>
/* Tailwind utilities are available globally via kimi-design.css */
</style>
