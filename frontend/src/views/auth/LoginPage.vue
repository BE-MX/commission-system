<template>
  <div class="relative w-screen h-screen overflow-hidden bg-[#0a0a0f]">
    <!-- 全屏 LeShine 品牌水印，铺在地图下面（地图 canvas 已透明底，点阵浮其上） -->
    <img :src="logoGold" class="bg-watermark" aria-hidden="true" alt="" />
    <div class="absolute top-0 left-0 h-full w-full lg:w-[55%]" style="z-index: 1;">
      <WorldMapCanvas />
    </div>

    <!-- Content Overlay -->
    <div class="relative z-10 flex h-full">
      <!-- Left Panel - Brand Zone -->
      <div
        class="hidden lg:flex flex-col justify-between h-full brand-panel will-animate animate-fade-in"
      >
        <!-- Brand Header -->
        <div class="pt-4 will-animate animate-fade-in-left delay-200">
          <div class="brand-lockup">
            <img :src="logoGold" class="brand-logo" alt="leShine Hair" />
            <span class="brand-divider"></span>
            <span class="brand-wordmark-sub">ARK&nbsp;PLATFORM</span>
          </div>
        </div>

        <!-- Main Title Block -->
        <div class="flex-1 flex flex-col justify-center will-animate animate-fade-in-left delay-350">
          <p class="brand-eyebrow"><span class="brand-dot"></span>企业级 AI 综合中台</p>
          <h1 class="brand-title">
            <span class="brand-trails" aria-hidden="true"><i class="rail"></i><i class="rail"></i><i class="rail"></i></span>莱莎方舟
          </h1>
          <p class="brand-latin">LeShine Ark Platform</p>
          <span class="brand-rule"></span>
          <p class="brand-desc">二十大业务模块 <b>·</b> 一体协同</p>
          <div class="brand-pillars will-animate animate-fade-in-left delay-500">
            <span>提成</span><i></i><span>订单发票</span><i></i><span>方舟洞见</span><i></i><span>生产制造</span><i></i><span>全链路履约</span>
          </div>
        </div>

        <!-- Footer -->
        <div class="pb-4 will-animate animate-fade-in-left delay-650">
          <p class="brand-footer">© 2026 LeShine Co., Ltd. <span>企业内部平台</span></p>
        </div>
      </div>

      <!-- Right Panel - Login Form -->
      <div class="form-side flex-1 flex items-center justify-center p-6">
        <div class="glass-card gold-glow login-card w-full will-animate animate-fade-in-right delay-300">
          <!-- Form Header (brand logo serves all viewports) -->
          <div class="mb-8">
            <img :src="logoGold" class="form-logo" alt="leShine Hair" />
            <p class="text-sm text-white/60 mt-4">欢迎登录莱莎方舟综合管理平台</p>
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
              :disabled="loading"
              class="tech-btn-primary w-full h-12 mt-8 text-base font-semibold flex items-center justify-center gap-2 disabled:opacity-70 disabled:cursor-not-allowed"
            >
              <svg
                v-if="loading"
                class="w-4 h-4 animate-spin"
                viewBox="0 0 24 24"
                fill="none"
              >
                <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-opacity="0.25"/>
                <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
              </svg>
              <span>{{ loading ? '登 录 中...' : '登 录' }}</span>
            </button>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import WorldMapCanvas from '@/components/WorldMapCanvas.vue'
import logoGold from '@/assets/leshine-logo-gold.png'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const remember = ref(false)
const loading = ref(false)

const handleSubmit = async () => {
  if (loading.value) return
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }

  loading.value = true
  try {
    await authStore.login(username.value, password.value)
    ElMessage.success('登录成功')
    // 深链恢复：守卫带来的 redirect 优先（如展位 iPad 打开 /expo/kiosk 被引到登录页）
    const redirect = String(route.query.redirect || '')
    // 移动 UA 默认进移动端，除非用户主动选了「切换到完整版」（ark_desktop_mode=1）
    // 或目标是展会 kiosk（展位 iPad 不进移动端素材页）
    const isMobileUA = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
    const desktopMode = sessionStorage.getItem('ark_desktop_mode') === '1'
    if (isMobileUA && !desktopMode && !redirect.startsWith('/expo')) {
      window.location.href = '/m/'
      return
    }
    router.push(redirect.startsWith('/') ? redirect : '/')
  } catch (error) {
    ElMessage.error(error.message || '登录失败，请检查用户名和密码')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* Tailwind utilities are available globally via kimi-design.css */

/* ── 左侧品牌区排版（金色渐变文字 + Outfit 字标 + 结构分隔） ── */
/* 整块品牌文字往里推，避免贴左边缘、页面中段空旷 */
.brand-panel { padding: 46px 44px 46px clamp(96px, 12vw, 220px); }
/* lg 下右侧登录栏给固定像素宽（容纳 620 卡片 + 内边距），左栏 flex:1 吃掉剩余。
   确定性布局：卡片列宽固定，不再被左栏内容撑宽而挤出视口 */
@media (min-width: 1024px) {
  .brand-panel { flex: 1 1 0%; min-width: 0; }
  .form-side { flex: 0 0 520px; min-width: 0; }
}

.brand-wordmark {
  font-family: 'Outfit', sans-serif;
  font-weight: 700; font-size: 26px; letter-spacing: 0.01em; line-height: 1;
  background: linear-gradient(118deg, #f9ecc6, #d4af6e 70%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.brand-wordmark-sub {
  font-family: 'Outfit', sans-serif;
  font-weight: 500; font-size: 11.5px; letter-spacing: 0.34em;
  color: rgba(255, 255, 255, 0.42);
}
.brand-lockup { display: flex; align-items: center; gap: 16px; }
.brand-logo { height: 44px; width: auto; display: block; }
.brand-divider { width: 1px; height: 26px; background: rgba(212, 175, 110, 0.4); }

.brand-eyebrow {
  display: flex; align-items: center; gap: 12px; margin: 0 0 18px;
  font-family: 'Outfit', 'PingFang SC', sans-serif;
  font-weight: 600; font-size: 18px; letter-spacing: 0.18em;
  color: #e2c17c;
}
.brand-dot {
  width: 8px; height: 8px; border-radius: 50%; flex: none;
  background: linear-gradient(120deg, #f9ecc6, #d4af6e);
  box-shadow: 0 0 12px rgba(212, 175, 110, 0.6);
}

.brand-title {
  position: relative; margin: 0;
  font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', sans-serif;
  font-weight: 800; font-size: clamp(46px, 5vw, 66px); line-height: 1.05;
  letter-spacing: 0.02em;
  background: linear-gradient(135deg, #fbeecb 0%, #e7c882 44%, #c99a4e 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
  text-shadow: 0 2px 46px rgba(212, 175, 110, 0.14);
}

/* 方舟航迹：标题左侧的金色滑行光轨，向标题方向驶入——凸显「方舟」的动态意象、补白左侧 */
.brand-trails {
  position: absolute; top: 50%; right: calc(100% + 26px); transform: translateY(-50%);
  width: clamp(130px, 15vw, 300px); height: 118px; pointer-events: none;
}
.brand-trails .rail {
  position: absolute; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(212, 175, 110, 0.05) 55%, rgba(212, 175, 110, 0.22));
}
.brand-trails .rail:nth-child(1) { top: 28%; }
.brand-trails .rail:nth-child(2) { top: 50%; }
.brand-trails .rail:nth-child(3) { top: 72%; }
.brand-trails .rail::after {
  content: ''; position: absolute; top: -3px; left: 0;
  width: 42%; height: 6px; border-radius: 6px; filter: blur(1px);
  background: linear-gradient(90deg, transparent, #f7e3b0, #d4af6e, transparent);
  animation: ark-glide 4.6s cubic-bezier(0.42, 0, 0.2, 1) infinite;
}
.brand-trails .rail:nth-child(2)::after { animation-duration: 5.4s; animation-delay: 1.5s; }
.brand-trails .rail:nth-child(3)::after { animation-duration: 4s; animation-delay: 2.8s; }
@keyframes ark-glide {
  0%   { transform: translateX(-46%); opacity: 0; }
  16%  { opacity: 1; }
  72%  { opacity: 1; }
  100% { transform: translateX(255%); opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .brand-trails .rail::after { animation: none; opacity: 0.5; transform: translateX(120%); }
}

/* 全屏 LeShine 品牌水印：整枚金标放大铺在地图下面，地图点阵浮其上，登录卡毛玻璃也透出它 */
.bg-watermark {
  position: absolute; z-index: 0; pointer-events: none; user-select: none;
  left: 50%; top: 50%; transform: translate(-50%, -50%);
  width: min(1500px, 94vw); height: auto;
  opacity: 0.05; filter: saturate(0.75);
}

/* 登录卡内金标（替代打字的 LeShine Hair，全站品牌一致） */
.form-logo { height: 34px; width: auto; display: block; }

/* 登录卡：加宽 + 半透明暖调毛玻璃 + 金色边缘发光（叠在地图上也通透好看） */
.login-card {
  width: 100%; max-width: 414px; padding: 44px 46px; border-radius: 22px;
  background: linear-gradient(158deg, rgba(40, 33, 23, 0.40), rgba(14, 12, 16, 0.56));
  backdrop-filter: blur(28px) saturate(1.35);
  -webkit-backdrop-filter: blur(28px) saturate(1.35);
  border: 1px solid rgba(212, 175, 110, 0.24);
  box-shadow:
    0 24px 70px rgba(0, 0, 0, 0.5),
    0 0 44px rgba(212, 175, 110, 0.16),
    0 0 100px rgba(212, 175, 110, 0.06),
    inset 0 1px 0 rgba(255, 255, 255, 0.12);
}
@media (max-width: 640px) {
  .login-card { padding: 36px 28px; }
}
.brand-latin {
  margin: 14px 0 0;
  font-family: 'Outfit', sans-serif;
  font-weight: 500; font-size: 13.5px; letter-spacing: 0.3em; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.26);
}
.brand-rule {
  display: block; width: 60px; height: 3px; border-radius: 2px; margin: 30px 0;
  background: linear-gradient(90deg, #d4af6e, rgba(212, 175, 110, 0));
}
.brand-desc {
  margin: 0; font-size: 17px; font-weight: 500; letter-spacing: 0.04em;
  color: rgba(255, 255, 255, 0.66);
}
.brand-desc b { color: #d4af6e; font-weight: 500; margin: 0 4px; }

.brand-pillars {
  display: flex; align-items: center; gap: 13px; margin-top: 20px;
  font-size: 12.5px; letter-spacing: 0.14em; color: rgba(255, 255, 255, 0.42);
}
.brand-pillars i {
  width: 1px; height: 11px; flex: none; display: inline-block;
  background: rgba(212, 175, 110, 0.3);
}

.brand-footer {
  margin: 0; font-size: 12px; letter-spacing: 0.05em; color: rgba(255, 255, 255, 0.28);
}
.brand-footer span { color: rgba(212, 175, 110, 0.5); margin-left: 8px; }
</style>
