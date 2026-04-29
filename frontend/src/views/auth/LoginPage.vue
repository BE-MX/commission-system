<template>
  <div class="login-page">
    <!-- Gold frame border -->
    <div class="gold-frame">
      <div class="frame-corner frame-tl"></div>
      <div class="frame-corner frame-tr"></div>
      <div class="frame-corner frame-bl"></div>
      <div class="frame-corner frame-br"></div>
    </div>

    <div class="page-inner">
      <!-- Top nav -->
      <header class="top-nav">
        <div class="nav-logo">
          <span class="logo-script">leShine</span>
          <sup class="logo-sup">Hair</sup>
        </div>
      </header>

      <!-- Main content -->
      <main class="main-content">
        <!-- Left showcase panel -->
        <section class="showcase-panel">
          <!-- World map decoration -->
          <div class="map-decoration">
            <svg class="map-svg" viewBox="0 0 800 500" preserveAspectRatio="xMidYMid slice">
              <!-- Grid lines -->
              <g class="grid-lines" opacity="0.06">
                <line v-for="i in 9" :key="'h'+i" x1="0" :y1="i * 50" x2="800" :y2="i * 50" stroke="#c8a96e" stroke-width="0.5"/>
                <line v-for="i in 15" :key="'v'+i" :x1="i * 53" y1="0" :x2="i * 53" y2="500" stroke="#c8a96e" stroke-width="0.5"/>
              </g>
              <!-- Connection lines -->
              <g class="connections" opacity="0.15">
                <line x1="200" y1="150" x2="380" y2="180" stroke="#c8a96e" stroke-width="0.8"/>
                <line x1="380" y1="180" x2="520" y2="160" stroke="#c8a96e" stroke-width="0.8"/>
                <line x1="520" y1="160" x2="650" y2="200" stroke="#c8a96e" stroke-width="0.8"/>
                <line x1="380" y1="180" x2="420" y2="280" stroke="#c8a96e" stroke-width="0.8"/>
                <line x1="200" y1="150" x2="180" y2="260" stroke="#c8a96e" stroke-width="0.8"/>
                <line x1="650" y1="200" x2="680" y2="280" stroke="#c8a96e" stroke-width="0.8"/>
                <line x1="520" y1="160" x2="600" y2="120" stroke="#c8a96e" stroke-width="0.8"/>
                <line x1="300" y1="200" x2="380" y2="180" stroke="#c8a96e" stroke-width="0.8"/>
              </g>
              <!-- Glow dots (major cities) -->
              <g class="city-dots">
                <circle v-for="(dot, i) in mapDots" :key="'dot'+i"
                  :cx="dot.x" :cy="dot.y" :r="dot.r"
                  fill="#c8a96e" :opacity="dot.opacity"
                  :class="'pulse-dot pulse-' + (i % 4)"
                />
                <circle v-for="(dot, i) in mapDots" :key="'glow'+i"
                  :cx="dot.x" :cy="dot.y" :r="dot.r * 3"
                  fill="#c8a96e" opacity="0.08"
                />
              </g>
            </svg>
            <!-- Central globe glow -->
            <div class="globe-glow"></div>
          </div>

          <div class="showcase-content">
            <h1 class="showcase-title">莱莎方舟综合管理平台</h1>
            <p class="showcase-subtitle">LeShine Hair Management Platform</p>

            <div class="stats-row">
              <div class="stat-card">
                <div class="stat-icon-box">
                  <svg viewBox="0 0 24 24" fill="none" stroke="#c8a96e" stroke-width="1.5">
                    <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 16.8l-6.2 4.5 2.4-7.4L2 9.4h7.6z"/>
                  </svg>
                </div>
                <div class="stat-info">
                  <span class="stat-label">全球精品发制品</span>
                </div>
              </div>
              <div class="stat-card">
                <div class="stat-number">1200<span class="stat-plus">+</span></div>
                <div class="stat-info">
                  <span class="stat-label">数据驱动 · 智慧管理</span>
                </div>
              </div>
              <div class="stat-card">
                <div class="stat-number">568</div>
                <div class="stat-info">
                  <span class="stat-label">合作客户</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Right login form -->
        <section class="login-section">
          <div class="login-card">
            <div class="card-logo">
              <span class="logo-script small">leShine</span>
              <sup class="logo-sup small">Hair</sup>
            </div>

            <p class="welcome-text">欢迎登录莱莎方舟综合管理平台</p>

            <el-form
              ref="loginFormRef"
              :model="loginForm"
              :rules="loginRules"
              class="login-form"
              @submit.prevent="handleLogin"
            >
              <el-form-item prop="username" class="gold-form-item">
                <el-input
                  v-model="loginForm.username"
                  placeholder="账号"
                  size="large"
                  :disabled="loading"
                  autocomplete="username"
                  @keyup.enter="handleLogin"
                >
                  <template #prefix>
                    <el-icon><User /></el-icon>
                  </template>
                </el-input>
              </el-form-item>

              <el-form-item prop="password" class="gold-form-item">
                <el-input
                  v-model="loginForm.password"
                  :type="showPassword ? 'text' : 'password'"
                  placeholder="密码"
                  size="large"
                  :disabled="loading"
                  autocomplete="current-password"
                  @keyup.enter="handleLogin"
                >
                  <template #prefix>
                    <el-icon><Lock /></el-icon>
                  </template>
                  <template #suffix>
                    <el-icon class="pwd-toggle" @click="showPassword = !showPassword">
                      <component :is="showPassword ? View : Hide" />
                    </el-icon>
                  </template>
                </el-input>
              </el-form-item>

              <div class="form-options">
                <el-checkbox v-model="rememberMe" :disabled="loading">
                  <span class="remember-label">记住登录状态</span>
                </el-checkbox>
                <span class="forgot-link" @click="handleForgotPassword">忘记密码？</span>
              </div>

              <el-form-item>
                <el-button
                  class="login-btn"
                  :loading="loading"
                  @click="handleLogin"
                >
                  <span v-if="!loading">登 录</span>
                  <span v-else>登录中...</span>
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </section>
      </main>

      <!-- Copyright -->
      <footer class="copyright-bar">
        <p>© 2026 LeShine Co., Ltd. All Rights Reserved.</p>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { User, Lock, View, Hide } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const loginFormRef = ref(null)
const loading = ref(false)
const showPassword = ref(false)
const rememberMe = ref(false)

const loginForm = reactive({
  username: '',
  password: ''
})

const loginRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 50, message: '用户名长度在 2 到 50 个字符', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于 6 位', trigger: 'blur' }
  ]
}

const mapDots = [
  { x: 200, y: 150, r: 3, opacity: 0.7 },
  { x: 180, y: 260, r: 2, opacity: 0.5 },
  { x: 220, y: 200, r: 2, opacity: 0.4 },
  { x: 300, y: 200, r: 2.5, opacity: 0.6 },
  { x: 380, y: 180, r: 3.5, opacity: 0.8 },
  { x: 420, y: 280, r: 2, opacity: 0.5 },
  { x: 400, y: 220, r: 2, opacity: 0.4 },
  { x: 520, y: 160, r: 3, opacity: 0.7 },
  { x: 550, y: 200, r: 2, opacity: 0.5 },
  { x: 600, y: 120, r: 2.5, opacity: 0.6 },
  { x: 650, y: 200, r: 3.5, opacity: 0.8 },
  { x: 680, y: 280, r: 2, opacity: 0.5 },
  { x: 700, y: 160, r: 2, opacity: 0.4 },
  { x: 350, y: 320, r: 2, opacity: 0.4 },
  { x: 480, y: 300, r: 2.5, opacity: 0.5 },
  { x: 150, y: 180, r: 2, opacity: 0.3 },
  { x: 620, y: 250, r: 2, opacity: 0.4 },
]

async function handleLogin() {
  if (!loginFormRef.value) return

  const valid = await loginFormRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true

  try {
    const result = await authStore.login(loginForm.username, loginForm.password)

    ElMessage({
      message: `欢迎回来，${result.user.real_name}！`,
      type: 'success',
      duration: 2000
    })

    const redirectPath = (route.query.redirect) || '/dashboard'
    await router.push(redirectPath)

  } catch (error) {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail

    if (status === 401) {
      ElMessage.error('用户名或密码错误，请重新输入')
    } else if (status === 423) {
      ElMessage({
        message: detail || '账号已被锁定，请30分钟后再试',
        type: 'error',
        duration: 5000
      })
    } else if (status === 403) {
      ElMessage.error('账号已被禁用，请联系管理员')
    } else if (status === 0 || !status) {
      ElMessage.error('无法连接到服务器，请检查网络')
    } else {
      ElMessage.error(detail || '登录失败，请稍后重试')
    }
  } finally {
    loading.value = false
  }
}

function handleForgotPassword() {
  ElMessageBox.alert(
    '请联系系统管理员重置密码，或发送邮件至 admin@leisa.com',
    '忘记密码',
    {
      confirmButtonText: '知道了',
      type: 'info',
      confirmButtonClass: 'forgot-confirm-btn'
    }
  )
}

onMounted(() => {
  if (authStore.isLoggedIn) {
    router.replace('/dashboard')
  }
})
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;1,400;1,700&display=swap');

/* ── Reset ─────────────────────────────────────────── */
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

/* ── Full page ─────────────────────────────────────── */
.login-page {
  position: relative;
  width: 100%;
  min-height: 100vh;
  background: #070709;
  overflow: hidden;
}

/* ── Gold frame ────────────────────────────────────── */
.gold-frame {
  position: absolute;
  inset: 8px;
  border: 2px solid;
  border-image: linear-gradient(
    135deg,
    #a08540 0%,
    #f0d68a 20%,
    #c8a96e 40%,
    #8a6f30 60%,
    #f0d68a 80%,
    #c8a96e 100%
  ) 1;
  pointer-events: none;
  z-index: 10;
}

.frame-corner {
  position: absolute;
  width: 32px;
  height: 32px;
  border-color: #d4b876;
  border-style: solid;
}

.frame-tl { top: -2px; left: -2px; border-width: 3px 0 0 3px; }
.frame-tr { top: -2px; right: -2px; border-width: 3px 3px 0 0; }
.frame-bl { bottom: -2px; left: -2px; border-width: 0 0 3px 3px; }
.frame-br { bottom: -2px; right: -2px; border-width: 0 3px 3px 0; }

/* ── Page inner ────────────────────────────────────── */
.page-inner {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  padding: 20px 32px;
}

/* ── Top nav ───────────────────────────────────────── */
.top-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 0 16px;
  flex-shrink: 0;
}

.nav-logo {
  display: flex;
  align-items: baseline;
  gap: 0;
}

.logo-script {
  font-family: 'Playfair Display', Georgia, 'Times New Roman', serif;
  font-style: italic;
  font-size: 28px;
  font-weight: 700;
  color: #e8d5a3;
  letter-spacing: 1px;
  text-shadow: 0 0 20px rgba(200, 169, 110, 0.3);
}

.logo-sup {
  font-family: 'Playfair Display', Georgia, serif;
  font-style: italic;
  font-size: 11px;
  color: rgba(200, 169, 110, 0.6);
  margin-left: 2px;
  vertical-align: super;
}

.logo-script.small {
  font-size: 32px;
}

.logo-sup.small {
  font-size: 12px;
}

/* ── Main content ──────────────────────────────────── */
.main-content {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0;
  min-height: 0;
}

/* ── Left showcase ─────────────────────────────────── */
.showcase-panel {
  flex: 1.3;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 480px;
  padding: 40px;
}

/* Map decoration */
.map-decoration {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.map-svg {
  position: absolute;
  width: 100%;
  height: 100%;
  opacity: 0.9;
}

.globe-glow {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 420px;
  height: 420px;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    rgba(200, 169, 110, 0.06) 0%,
    rgba(200, 169, 110, 0.02) 40%,
    transparent 70%
  );
}

/* Pulse animations for dots */
.pulse-dot { animation: pulse 3s ease-in-out infinite; }
.pulse-0 { animation-delay: 0s; }
.pulse-1 { animation-delay: 0.8s; }
.pulse-2 { animation-delay: 1.6s; }
.pulse-3 { animation-delay: 2.4s; }

@keyframes pulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}

/* Showcase content */
.showcase-content {
  position: relative;
  z-index: 2;
  max-width: 520px;
}

.showcase-title {
  font-size: 36px;
  font-weight: 700;
  color: #f0e6d0;
  letter-spacing: 4px;
  line-height: 1.3;
  text-shadow: 0 2px 20px rgba(200, 169, 110, 0.2);
  margin-bottom: 12px;
}

.showcase-subtitle {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 14px;
  color: rgba(200, 169, 110, 0.5);
  letter-spacing: 2px;
  margin-bottom: 48px;
}

/* Stats row */
.stats-row {
  display: flex;
  gap: 16px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  background: rgba(200, 169, 110, 0.05);
  border: 1px solid rgba(200, 169, 110, 0.12);
  border-radius: 10px;
  backdrop-filter: blur(8px);
  min-width: 120px;
  transition: border-color 0.3s;
}

.stat-card:hover {
  border-color: rgba(200, 169, 110, 0.3);
}

.stat-icon-box {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
}

.stat-icon-box svg {
  width: 100%;
  height: 100%;
}

.stat-number {
  font-size: 28px;
  font-weight: 700;
  color: #e8d5a3;
  line-height: 1;
  letter-spacing: 1px;
}

.stat-plus {
  font-size: 18px;
  color: #c8a96e;
}

.stat-label {
  font-size: 11px;
  color: rgba(200, 169, 110, 0.6);
  letter-spacing: 1px;
  white-space: nowrap;
}

/* ── Right login section ───────────────────────────── */
.login-section {
  flex: 0 0 420px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.login-card {
  width: 100%;
  max-width: 340px;
  padding: 40px 36px;
  background: rgba(15, 15, 22, 0.7);
  border: 1px solid rgba(200, 169, 110, 0.1);
  border-radius: 16px;
  backdrop-filter: blur(20px);
}

.card-logo {
  display: flex;
  align-items: baseline;
  margin-bottom: 20px;
}

.welcome-text {
  font-size: 14px;
  color: rgba(200, 169, 110, 0.65);
  letter-spacing: 1px;
  margin-bottom: 32px;
  line-height: 1.6;
}

/* ── Form styling ──────────────────────────────────── */
.login-form {
  width: 100%;
}

.gold-form-item {
  margin-bottom: 22px;
}

:deep(.el-input__wrapper) {
  background: rgba(200, 169, 110, 0.04) !important;
  border: 1px solid rgba(200, 169, 110, 0.15) !important;
  border-radius: 8px;
  box-shadow: none !important;
  padding: 2px 14px;
  transition: all 0.25s ease;
}

:deep(.el-input__wrapper:hover) {
  border-color: rgba(200, 169, 110, 0.3) !important;
  background: rgba(200, 169, 110, 0.06) !important;
}

:deep(.el-input__wrapper.is-focus) {
  border-color: #c8a96e !important;
  background: rgba(200, 169, 110, 0.06) !important;
  box-shadow: 0 0 0 3px rgba(200, 169, 110, 0.08) !important;
}

:deep(.el-input__inner) {
  height: 42px;
  font-size: 14px;
  color: #e8d5a3 !important;
  caret-color: #c8a96e;
}

:deep(.el-input__inner::placeholder) {
  color: rgba(200, 169, 110, 0.35) !important;
}

:deep(.el-input__prefix .el-icon),
:deep(.el-input__prefix-icon) {
  color: rgba(200, 169, 110, 0.4) !important;
  font-size: 16px;
}

:deep(.el-form-item__error) {
  color: #e8a087;
  padding-top: 4px;
  font-size: 12px;
}

/* Password toggle */
.pwd-toggle {
  cursor: pointer;
  color: rgba(200, 169, 110, 0.4) !important;
  transition: color 0.2s;
  font-size: 16px;
}

.pwd-toggle:hover {
  color: #c8a96e !important;
}

/* Form options */
.form-options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  margin-top: -4px;
}

.remember-label {
  font-size: 13px;
  color: rgba(200, 169, 110, 0.5);
}

:deep(.el-checkbox__label) {
  color: rgba(200, 169, 110, 0.5) !important;
  font-size: 13px;
}

:deep(.el-checkbox__inner) {
  background: transparent;
  border-color: rgba(200, 169, 110, 0.25);
}

:deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: #c8a96e;
  border-color: #c8a96e;
}

.forgot-link {
  font-size: 13px;
  color: rgba(200, 169, 110, 0.5);
  cursor: pointer;
  transition: color 0.2s;
}

.forgot-link:hover {
  color: #e8d5a3;
}

/* Login button */
.login-btn {
  width: 100%;
  height: 46px;
  border: none !important;
  border-radius: 8px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 6px;
  background: linear-gradient(135deg, #c8a96e 0%, #a08540 50%, #c8a96e 100%) !important;
  background-size: 200% 100% !important;
  color: #0a0a0f !important;
  cursor: pointer;
  transition: all 0.4s ease;
  box-shadow: 0 4px 20px rgba(200, 169, 110, 0.2);
}

.login-btn:hover:not(:disabled) {
  background-position: 100% 0 !important;
  box-shadow: 0 6px 28px rgba(200, 169, 110, 0.35);
  transform: translateY(-1px);
}

.login-btn:active:not(:disabled) {
  transform: translateY(0);
}

:deep(.el-button.is-loading) {
  background: linear-gradient(135deg, #c8a96e 0%, #a08540 100%) !important;
  color: #0a0a0f !important;
  opacity: 0.8;
}

/* ── Copyright bar ─────────────────────────────────── */
.copyright-bar {
  text-align: center;
  padding: 12px 0 4px;
  flex-shrink: 0;
}

.copyright-bar p {
  font-size: 11px;
  color: rgba(200, 169, 110, 0.25);
  letter-spacing: 1px;
}

/* ── Responsive: tablet ────────────────────────────── */
@media screen and (max-width: 1024px) {
  .showcase-panel {
    flex: 1;
    padding: 24px;
  }

  .login-section {
    flex: 0 0 380px;
    padding: 24px;
  }

  .showcase-title {
    font-size: 28px;
  }

  .stats-row {
    flex-wrap: wrap;
  }
}

/* ── Responsive: mobile ────────────────────────────── */
@media screen and (max-width: 768px) {
  .gold-frame {
    inset: 4px;
  }

  .page-inner {
    padding: 12px 16px;
  }

  .main-content {
    flex-direction: column;
    gap: 0;
  }

  .showcase-panel {
    flex: none;
    min-height: auto;
    padding: 20px 16px 32px;
  }

  .showcase-title {
    font-size: 22px;
    letter-spacing: 2px;
    margin-bottom: 8px;
  }

  .showcase-subtitle {
    margin-bottom: 24px;
    font-size: 12px;
  }

  .stats-row {
    gap: 8px;
  }

  .stat-card {
    padding: 10px 12px;
    min-width: 0;
    flex: 1;
  }

  .stat-number {
    font-size: 20px;
  }

  .stat-label {
    font-size: 10px;
  }

  .login-section {
    flex: none;
    width: 100%;
    padding: 0 8px 24px;
  }

  .login-card {
    max-width: 100%;
    padding: 28px 24px;
  }

  .logo-script {
    font-size: 22px;
  }

  .logo-script.small {
    font-size: 26px;
  }
}

@media screen and (max-width: 480px) {
  .stat-icon-box {
    display: none;
  }

  .stat-card {
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }
}
</style>
