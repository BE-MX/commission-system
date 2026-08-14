<template>
  <div class="dashboard-page" :class="{ 'is-editing': editing }">
    <!-- 金色极光背景（纯装饰；本体在 styles/liquid-glass.css，发票页共享） -->
    <div class="dashboard-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="dashboard-sections anim-stagger">
      <!-- ① Hero 欢迎区（AI 助理问候 + 深色玻璃锚点） -->
      <HeroSection :data="dash" />

      <!-- ② 最近使用快跳（不可配置，随访问自动更新） -->
      <QuickNav v-if="!editing" />

      <!-- ③ 待办提醒（紧急信息，不可配置） -->
      <TodoAlerts v-if="!editing" :data="dash" />

      <!-- ④ 主辅双列：数据指标+快捷操作 ｜ 节假日日历+物流进度 -->
      <div class="dashboard-columns" :class="{ 'has-aside': !editing }">
        <div class="column-main">
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
        </div>

        <aside v-if="!editing" class="column-aside">
          <HolidayCard :data="dash" />
          <LogisticsCard
            v-if="authStore.hasAnyPermission(['tracking:read'])"
            :data="dash"
          />
        </aside>
      </div>

      <!-- ⑤ 动态概览（不可配置） -->
      <OverviewPanels v-if="!editing" :data="dash" />
    </div>

    <!-- 编辑态底部操作条 -->
    <CustomizeBar
      :editing="editing"
      :saving="saving"
      :dirty="dirty"
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
import QuickNav from './components/QuickNav.vue'
import TodoAlerts from './components/TodoAlerts.vue'
import MetricsGrid from './components/MetricsGrid.vue'
import ActionsGrid from './components/ActionsGrid.vue'
import HolidayCard from './components/HolidayCard.vue'
import LogisticsCard from './components/LogisticsCard.vue'
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
  editing, saving, dirty,
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
/* 编辑态底部 fixed 操作条会盖住末行卡片的眼睛/把手，留出滚动余量（审查 P1） */
.dashboard-page.is-editing {
  padding-bottom: 120px;
}

/* 极光层本体在 styles/liquid-glass.css（.lg-aurora，发票等页面共享）。
   这里只做页面级外溢：盖住 main-content 的 24/28 padding 环，
   否则 wash 与 --page-bg 的色差会在页面边缘形成硬接缝 */
.dashboard-aurora {
  inset: -24px -28px;
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

/* ========== 主辅双列 ========== */
.dashboard-columns {
  display: grid;
  grid-template-columns: 1fr;
  gap: 20px;
  align-items: start;
}
.dashboard-columns.has-aside {
  grid-template-columns: minmax(0, 1fr) 340px;
}
.column-main {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}
.column-aside {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
  /* 侧栏两张卡稍晚入场，形成由主到辅的视觉次序 */
  animation-delay: 120ms;
}
.column-aside > * {
  animation: dashFadeInUp 260ms var(--ease-out-strong) both;
}
.column-aside > *:nth-child(2) {
  animation-delay: 60ms;
}

@media (max-width: 1100px) {
  .dashboard-columns.has-aside {
    grid-template-columns: 1fr;
  }
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
.anim-stagger > *:nth-child(6) { animation-delay: 250ms; }

@keyframes dashFadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .anim-stagger > * {
    animation: dashFadeIn 200ms ease forwards;
  }
  .column-aside > * {
    animation: dashFadeIn 200ms ease both;
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
  .dashboard-aurora {
    inset: -16px;
  }
}
</style>
