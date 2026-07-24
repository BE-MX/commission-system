<template>
  <div class="dashboard-page">
    <!-- 金色极光背景（纯装饰，transform 慢漂移；玻璃卡的 blur 透出它） -->
    <div class="dashboard-aurora" aria-hidden="true">
      <div class="aurora-blob aurora-gold" />
      <div class="aurora-blob aurora-amber" />
      <div class="aurora-blob aurora-blue" />
    </div>

    <div class="dashboard-sections anim-stagger">
      <!-- ① Hero 欢迎区（深色玻璃锚点） -->
      <HeroSection :data="dash" />

      <!-- ② 待办提醒（紧急信息，不可配置） -->
      <TodoAlerts v-if="!editing" :data="dash" />

      <!-- ③ 指标卡（可配置） -->
      <section>
        <div class="section-toolbar">
          <span v-if="editing" class="section-label">数据指标</span>
          <span v-else />
          <GlassButton
            v-if="!editing"
            variant="ghost"
            size="sm"
            :left-icon="Setting"
            @click="enterEdit"
          >
            自定义
          </GlassButton>
        </div>
        <MetricsGrid
          :data="dash"
          :cards="metricCards"
          :editing="editing"
          :is-hidden-fn="isHidden"
          @reorder="keys => reorder('metrics', keys)"
          @toggle="key => toggleHidden('metrics', key)"
        />
      </section>

      <!-- ④ 快捷操作（可配置） -->
      <section>
        <div v-if="editing" class="section-toolbar">
          <span class="section-label">快捷操作</span>
        </div>
        <ActionsGrid
          :data="dash"
          :cards="actionCards"
          :editing="editing"
          :is-hidden-fn="isHidden"
          @reorder="keys => reorder('actions', keys)"
          @toggle="key => toggleHidden('actions', key)"
        />
      </section>

      <!-- ⑤ 动态概览（不可配置） -->
      <OverviewPanels v-if="!editing" :data="dash" />
    </div>

    <!-- 编辑态底部操作条 -->
    <CustomizeBar
      :editing="editing"
      :saving="saving"
      @save="saveEdit"
      @cancel="cancelEdit"
      @reset="resetToDefault"
    />

    <!-- 登录欢迎弹框 -->
    <WelcomeModal
      :user-name="authStore.user?.real_name || '用户'"
      :avatar-url="authStore.user?.avatar_url || ''"
      :pending-count="dash.pendingApprovals"
      :shoot-count="dash.todayShootCount"
    />
  </div>
</template>

<script setup>
import { computed, reactive } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { Setting } from '@element-plus/icons-vue'
import WelcomeModal from '@/components/WelcomeModal.vue'
import GlassButton from '@/components/GlassButton.vue'

import HeroSection from './components/HeroSection.vue'
import TodoAlerts from './components/TodoAlerts.vue'
import MetricsGrid from './components/MetricsGrid.vue'
import ActionsGrid from './components/ActionsGrid.vue'
import OverviewPanels from './components/OverviewPanels.vue'
import CustomizeBar from './components/CustomizeBar.vue'

import { ACTION_CARDS, METRIC_CARDS } from './cards'
import { useDashboardData } from './composables/useDashboardData'
import { useDashboardConfig } from './composables/useDashboardConfig'
import './glass.css'

const authStore = useAuthStore()

// reactive() 深度解包 refs：注册表取数函数直接 d.incompleteCount 拿值
const dash = reactive(useDashboardData())

const {
  editing, saving,
  arrange, isHidden,
  enterEdit, cancelEdit, toggleHidden, reorder, saveEdit, resetToDefault,
} = useDashboardConfig()

const metricCards = computed(() => arrange('metrics', METRIC_CARDS))
const actionCards = computed(() => arrange('actions', ACTION_CARDS))
</script>

<style scoped>
/* ========== 页面容器与光斑层 ========== */
.dashboard-page {
  position: relative;
  max-width: 1440px;
  margin: 0 auto;
  padding: 24px 28px;
}

.dashboard-aurora {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}

.aurora-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(70px);
  will-change: transform;
}

.aurora-gold {
  width: 560px;
  height: 560px;
  top: -140px;
  right: -80px;
  background: radial-gradient(circle, rgba(245, 203, 92, 0.20), transparent 65%);
  animation: auroraDrift 70s ease-in-out infinite alternate;
}

.aurora-amber {
  width: 480px;
  height: 480px;
  top: 320px;
  left: -160px;
  background: radial-gradient(circle, rgba(212, 148, 28, 0.14), transparent 65%);
  animation: auroraDrift 90s ease-in-out infinite alternate-reverse;
}

.aurora-blue {
  width: 520px;
  height: 520px;
  bottom: -120px;
  right: 15%;
  background: radial-gradient(circle, rgba(107, 140, 186, 0.12), transparent 65%);
  animation: auroraDrift 80s ease-in-out infinite alternate;
}

@keyframes auroraDrift {
  from { transform: translate(0, 0) scale(1); }
  33%  { transform: translate(60px, 40px) scale(1.08); }
  66%  { transform: translate(-40px, 80px) scale(0.96); }
  to   { transform: translate(30px, -30px) scale(1.04); }
}

@media (prefers-reduced-motion: reduce) {
  .aurora-blob {
    animation: none;
  }
}

/* ========== 分区容器 ========== */
.dashboard-sections {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 32px;
  margin-bottom: 10px;
}

.section-label {
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-secondary);
}

/* ========== 入场动效（Emil：高频页面收敛到 250ms/8px/50ms 间隔） ========== */
.anim-stagger > * {
  animation: dashFadeInUp 250ms var(--ease-out-strong) forwards;
  opacity: 0;
}
.anim-stagger > *:nth-child(1) { animation-delay: 0ms; }
.anim-stagger > *:nth-child(2) { animation-delay: 50ms; }
.anim-stagger > *:nth-child(3) { animation-delay: 100ms; }
.anim-stagger > *:nth-child(4) { animation-delay: 150ms; }
.anim-stagger > *:nth-child(5) { animation-delay: 200ms; }

@keyframes dashFadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .anim-stagger > * {
    animation: dashFadeIn 200ms ease forwards;
  }
  @keyframes dashFadeIn {
    from { opacity: 0; }
    to   { opacity: 1; }
  }
}

/* ========== 响应式 ========== */
@media (max-width: 767px) {
  .dashboard-page {
    padding: 16px;
  }
}
</style>
