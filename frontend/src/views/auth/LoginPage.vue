<template>
  <div class="login-page">
    <!-- Static ambient light and watermark keep the form surface stable. -->
    <div class="login-atmosphere" aria-hidden="true"></div>
    <img :src="logoGold" class="bg-watermark" aria-hidden="true" alt="" />
    <div class="login-map">
      <WorldMapCanvas />
    </div>

    <!-- Content Overlay -->
    <div class="login-layout">
      <!-- Left Panel - Brand Zone -->
      <div
        class="brand-panel"
      >
        <!-- Brand Header -->
        <div class="brand-header login-enter">
          <div class="brand-lockup">
            <img :src="logoGold" class="brand-logo" alt="leShine Hair" />
            <span class="brand-divider"></span>
            <span class="brand-wordmark-sub">ARK&nbsp;PLATFORM</span>
          </div>
        </div>

        <!-- Main Title Block -->
        <div class="brand-copy login-enter">
          <p class="brand-eyebrow"><span class="brand-dot"></span>AI 驱动的企业协同平台</p>
          <h1 class="brand-title">
            <span class="brand-wake" aria-hidden="true">
              <i v-for="lane in 5" :key="`lane-${lane}`" class="wake-stream" :style="{ '--lane': lane }"></i>
              <i v-for="particle in wakeParticles" :key="particle.id" class="wake-particle" :style="particle.style"></i>
            </span>
            <span class="brand-title-text">莱莎方舟</span>
          </h1>
          <p class="brand-latin">LeShine Ark Platform</p>
          <span class="brand-rule"></span>
          <p class="brand-desc">贯通业务 <b>·</b> 沉淀知识 <b>·</b> 智能协同</p>
          <div class="brand-pillars">
            <span>客户经营</span><i></i><span>产销履约</span><i></i><span>业绩核算</span><i></i><span>创意设计</span><i></i><span>知识洞察</span>
          </div>
        </div>

        <!-- Footer -->
        <div class="brand-bottom">
          <p class="brand-footer">© 2026 LeShine Co., Ltd. <span>企业内部平台</span></p>
        </div>
      </div>

      <!-- Right Panel - Login Form -->
      <div class="form-side">
        <div class="login-card login-enter">
          <!-- Form Header (brand logo serves all viewports) -->
          <div class="mb-8">
            <img :src="logoGold" class="form-logo" alt="leShine Hair" />
            <p class="text-sm text-white/60 mt-4">欢迎登录莱莎方舟企业协同平台</p>
          </div>

          <form @submit.prevent="handleSubmit">
            <!-- Username -->
            <div class="relative">
              <svg class="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
              </svg>
              <input
                v-model="username"
                aria-label="用户名"
                autocomplete="username"
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
                aria-label="密码"
                autocomplete="current-password"
                :type="showPassword ? 'text' : 'password'"
                placeholder="请输入密码"
                class="tech-input w-full h-12 pl-12 pr-12 text-sm"
              />
              <button
                type="button"
                @click="showPassword = !showPassword"
                class="password-toggle"
                :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                :aria-pressed="showPassword"
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
            <div class="login-options">
              <label class="flex items-center gap-2 cursor-pointer group">
                <input v-model="remember" type="checkbox" class="remember-checkbox" />
                <span class="text-sm text-white/60">记住登录状态</span>
              </label>
              <a href="#" class="forgot-link">
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
        <footer
          class="site-filing"
          aria-label="网站备案信息"
        >
          <a
            href="https://beian.miit.gov.cn/"
            target="_blank"
            rel="noopener noreferrer"
          >鲁ICP备2023012060号-3</a>
          <span class="site-filing__divider" aria-hidden="true"></span>
          <span>鄄城莱莎发制品有限公司</span>
        </footer>
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
import { EXPO_KIOSK_PATH } from '@/router/expoKioskRoute'
import { readSessionItem } from '@/utils/safeSessionStorage'

// Deterministic stagger keeps the wake continuous from the first frame.
const wakeParticles = Array.from({ length: 38 }, (_, id) => ({
  id,
  style: {
    '--origin-y': `${22 + (id * 17 % 57)}%`,
    '--drift-y': `${(id * 23 % 65) - 32}px`,
    '--travel': `${130 + (id * 31 % 130)}px`,
    '--duration': `${2.6 + (id % 9) * 0.2}s`,
    '--delay': `${-(id * 0.37 % 4.2)}s`,
    '--size': `${id % 5 === 0 ? 3 : 1.5}px`,
    '--length': `${id % 6 === 0 ? 16 : id % 3 === 0 ? 5 : 2}px`,
  },
}))

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
    const desktopMode = readSessionItem('ark_desktop_mode') === '1'
    if (isMobileUA && !desktopMode && !redirect.startsWith('/expo')) {
      window.location.href = '/m/'
      return
    }
    if (redirect === EXPO_KIOSK_PATH && !authStore.hasPermission('expo:write')) {
      ElMessage.error('当前账号没有展会试戴权限，请更换展会设备账号')
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
.login-page {
  position: relative; isolation: isolate; width: 100%; min-height: 100vh; min-height: 100svh;
  overflow: clip; background: var(--login-bg); color: var(--login-text);
}
.login-page :where(*, *::before, *::after) { box-sizing: border-box; }
.login-atmosphere {
  position: absolute; inset: 0; pointer-events: none;
  background: radial-gradient(ellipse at 18% 24%, var(--login-wash), transparent 56%),
    radial-gradient(ellipse at 90% 70%, var(--login-wash), transparent 46%);
}
.bg-watermark {
  position: absolute; left: -6%; bottom: 4%; width: 65%; height: auto;
  opacity: 0.01; pointer-events: none; user-select: none;
}
.login-map {
  position: absolute; left: 0; top: 49%; transform: translateY(-50%);
  width: calc(100% - 490px); height: clamp(400px, 68vh, 700px); opacity: 0.85;
}
.login-layout { position: relative; z-index: 1; display: flex; min-height: 100vh; min-height: 100svh; }
.brand-panel { display: flex; flex: 1; min-width: 0; flex-direction: column; padding: 48px 32px 30px clamp(48px, 7vw, 140px); }
.brand-copy {
  flex: 1; display: flex; flex-direction: column; justify-content: center; align-items: flex-start;
  padding: 0 0 28px clamp(42px, 7vw, 110px);
}
.brand-lockup { display: flex; align-items: center; gap: 18px; }
.brand-logo { height: 40px; width: auto; display: block; }
.brand-divider { width: 1px; height: 24px; background: var(--login-border); }
.brand-wordmark-sub { font-family: 'Outfit', sans-serif; font-size: 10px; letter-spacing: 0.3em; color: var(--login-muted); }
.brand-eyebrow { display: flex; align-items: center; gap: 10px; margin: 0 0 18px; font-size: 13px; letter-spacing: 0.18em; color: var(--login-gold); }
.brand-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--login-gold); }
.brand-title {
  position: relative; margin: 0; white-space: nowrap; font-size: clamp(42px, 4.4vw, 64px);
  font-weight: 700; line-height: 1.2; letter-spacing: 0.06em;
  animation: ark-sailing 7s cubic-bezier(0.37, 0, 0.63, 1) infinite;
}
.brand-title-text {
  position: relative; z-index: 1;
  background: linear-gradient(115deg, var(--login-gold-light), var(--login-gold));
  background-clip: text; -webkit-background-clip: text; color: transparent;
  filter: drop-shadow(0 2px 8px var(--login-bg));
}
/* The wake travels LEFT from the title, implying forward sailing to the right. */
.brand-wake {
  position: absolute; right: calc(100% - 8px); top: -18%; width: 270px; height: 136%;
  pointer-events: none; mask-image: linear-gradient(90deg, transparent, var(--login-bg) 30%);
}
.brand-wake::before {
  content: ''; position: absolute; right: -4px; top: 5%; width: 95%; height: 90%;
  background: radial-gradient(ellipse at right, var(--login-wake-glow), transparent 72%);
}
.wake-stream {
  position: absolute; right: 0; top: calc(16% + var(--lane) * 11%);
  width: calc(52% + var(--lane) * 8%); height: 1px; opacity: 0.42;
  transform-origin: right; transform: rotate(calc((var(--lane) - 3) * 2deg));
  background: linear-gradient(90deg, transparent, var(--login-wake-glow) 40%, var(--login-gold));
}
.wake-particle {
  position: absolute; right: 0; top: var(--origin-y); width: var(--length); height: var(--size);
  border-radius: 50%; background: linear-gradient(90deg, var(--login-gold), var(--login-gold-light));
  animation: ark-wake var(--duration) linear var(--delay) infinite both;
}
@keyframes ark-wake {
  0% { transform: translate(0, 0) scale(1); opacity: 0; }
  12% { opacity: 0.85; }
  55% { opacity: 0.35; }
  100% { transform: translate(calc(-1 * var(--travel)), var(--drift-y)) scale(0.4); opacity: 0; }
}
@keyframes ark-sailing {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(8px, -3px); }
}
.brand-latin { position: relative; text-shadow: 0 1px 8px var(--login-bg); margin: 12px 0 0; font-family: 'Outfit', sans-serif; font-size: 11px; letter-spacing: 0.28em; text-transform: uppercase; color: var(--login-dim); }
.brand-rule { display: block; width: 36px; height: 1px; margin: 24px 0; background: var(--login-gold); }
.brand-desc { position: relative; text-shadow: 0 1px 8px var(--login-bg); margin: 0; font-size: 15px; letter-spacing: 0.08em; color: var(--login-muted); }
.brand-desc b { margin: 0 5px; color: var(--login-gold); font-weight: 400; }
.brand-pillars { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 14px; font-size: 11px; color: var(--login-dim); }
.brand-pillars i { width: 1px; height: 10px; background: var(--login-border); }
.brand-footer { margin: 0; font-size: 11px; line-height: 1.8; color: var(--login-dim); }
.brand-footer span { margin-left: 12px; }
.form-side { position: relative; flex: 0 0 500px; display: flex; align-items: center; justify-content: center; min-width: 0; padding: 64px 48px 88px 24px; }
.login-card {
  width: 100%; max-width: 420px; padding: 40px 34px; border-radius: 20px;
  background: linear-gradient(145deg, var(--login-surface), var(--login-bg));
  border: 1px solid var(--login-border);
  box-shadow: 0 24px 64px var(--login-shadow), inset 0 1px 0 var(--login-wash);
}
.form-logo { height: 36px; width: auto; display: block; }
.login-card .text-white\/60 { color: var(--login-muted); }
.tech-input { color: var(--login-text); border-color: var(--login-border); transition: border-color 160ms ease, box-shadow 160ms ease; }
.tech-input::placeholder { color: var(--login-dim); }
.password-toggle {
  position: absolute; right: 4px; top: 50%; transform: translateY(-50%); display: grid; place-items: center;
  width: 40px; height: 40px; padding: 0; border: 0; border-radius: 6px;
  color: var(--login-muted); background: transparent; cursor: pointer; transition: color 160ms ease;
}
.login-options { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 20px; }
.remember-checkbox { width: 15px; height: 15px; margin: 0; accent-color: var(--login-gold); cursor: pointer; }
.forgot-link { color: var(--login-gold); font-size: 13px; white-space: nowrap; text-decoration: none; }
.tech-btn-primary { background: linear-gradient(115deg, var(--login-gold-light), var(--login-gold)); color: var(--login-bg); transition: transform 140ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 160ms ease; }
.tech-btn-primary:hover { filter: none; box-shadow: none; }
.tech-btn-primary:disabled { opacity: 0.7; cursor: wait; }
.tech-btn-primary:disabled:active { transform: none; }
.login-card :is(button, a, input[type='checkbox']):focus-visible { outline: 2px solid var(--login-gold); outline-offset: 4px; }
@media (hover: hover) and (pointer: fine) {
  .password-toggle:hover { color: var(--login-gold-light); }
  .forgot-link:hover { text-decoration: underline; }
  .tech-btn-primary:not(:disabled):hover { box-shadow: 0 4px 20px var(--login-wash); }
}
.site-filing {
  position: absolute; right: 24px; bottom: 18px; left: 24px;
  display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 6px 10px;
  font-size: 11px; line-height: 1.6; color: var(--login-dim);
}
.site-filing a { color: var(--login-muted); text-decoration: none; transition: color 160ms ease; }
.site-filing a:hover { color: var(--login-gold-light); }
.site-filing a:focus-visible { outline: 1px solid currentColor; outline-offset: 4px; }
.site-filing__divider { width: 1px; height: 10px; background: var(--login-border); }
.login-enter { animation: login-enter 280ms cubic-bezier(0.23, 1, 0.32, 1) both; }
.brand-copy { animation-delay: 60ms; }
@keyframes login-enter { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
@media (min-width: 1024px) and (max-height: 760px) {
  .brand-copy { padding-bottom: 16px; }
  .brand-rule { margin: 18px 0; }
}
@media (max-width: 1023px) {
  .brand-panel { display: none; }
  .form-side { flex: 1; min-height: 100vh; min-height: 100svh; padding: 100px 24px 96px; }
  .login-map { left: 0; top: 0; bottom: auto; width: 100%; height: 300px; transform: none; opacity: 0.45; }
  .bg-watermark { width: 100%; left: 0; bottom: 8%; }
}
@media (max-width: 640px) {
  .form-side { padding: 72px 20px 96px; }
  .login-card { padding: 32px 24px; }
  .tech-input { font-size: 16px; }
  .site-filing { bottom: 18px; flex-wrap: wrap; gap: 4px 10px; }
  .site-filing__divider { display: none; }
  .site-filing span:last-child { flex-basis: 100%; text-align: center; }
}
@media (max-width: 359px) {
  .form-side { padding-inline: 12px; }
  .login-card { padding-inline: 18px; }
  .login-options { gap: 8px; }
  .login-options .text-sm { font-size: 12px; }
}
@media (min-width: 1024px) and (max-height: 600px) {
  .login-layout { min-height: 600px; }
  .login-map { top: 290px; }
}
@media (prefers-reduced-motion: reduce) {
  .login-enter, .brand-title { animation: none; }
  .wake-particle { animation: none; opacity: 0; }
  .tech-btn-primary { transition: none; }
  .tech-btn-primary:active { transform: none; }
}
</style>
