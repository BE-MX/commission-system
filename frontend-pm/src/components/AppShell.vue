<template>
  <div class="shell">
    <header class="topbar">
      <div class="topbar-inner">
        <router-link to="/dashboard" class="brand">
          <SealMark :size="26" />
          <span class="brand-name">莱莎 AI 陪跑项目站</span>
        </router-link>

        <nav class="nav" aria-label="主导航">
          <router-link
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            :class="{ active: isActive(item) }"
          >
            {{ item.label }}
          </router-link>
        </nav>

        <div class="identity">
          <span class="identity-label">当前身份</span>
          <span class="identity-name">{{ identity.displayName || identity.username }}</span>
          <button class="identity-switch" type="button" @click="switchIdentity">切换</button>
        </div>
      </div>
    </header>

    <main class="main">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { useRoute, useRouter } from 'vue-router'
import SealMark from './SealMark.vue'
import { identity } from '../stores/identity.js'

const route = useRoute()
const router = useRouter()

const navItems = [
  { to: '/dashboard', label: '总览', match: ['dashboard'] },
  { to: '/tasks', label: '任务', match: ['tasks'] },
  { to: '/materials', label: '资料库', match: ['materials', 'material-detail'] },
  { to: '/activity', label: '动态', match: ['activity'] },
]

const isActive = (item) => item.match.includes(route.name)

function switchIdentity() {
  identity.signOut()
  router.push({ name: 'gate' })
}
</script>

<style scoped>
.shell { min-height: 100vh; }

.topbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: color-mix(in srgb, var(--paper) 88%, transparent);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--hairline);
}
.topbar-inner {
  max-width: var(--content-max);
  margin: 0 auto;
  padding: 0 32px;
  height: 58px;
  display: flex;
  align-items: center;
  gap: 36px;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.brand-name {
  font-family: var(--font-serif);
  font-size: 15.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.nav {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
}
.nav-link {
  position: relative;
  padding: 6px 12px;
  font-size: 13.5px;
  color: var(--ink-3);
  transition: color var(--dur-fast) var(--ease-out);
}
.nav-link::after {
  content: '';
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: 1px;
  height: 1.5px;
  background: var(--ink);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform var(--dur-med) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
  .nav-link:hover { color: var(--ink); }
}
.nav-link.active { color: var(--ink); }
.nav-link.active::after { transform: scaleX(1); }

.identity {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding: 5px 6px 5px 12px;
  border: 1px solid var(--hairline);
  border-radius: 999px;
  background: var(--paper-raised);
}
.identity-label {
  font-size: 11px;
  color: var(--ink-4);
  letter-spacing: 0.06em;
}
.identity-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--cinnabar);
}
.identity-switch {
  font-size: 12px;
  color: var(--ink-3);
  padding: 3px 10px;
  border-radius: 999px;
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}
.identity-switch:active { transform: scale(0.95); }
@media (hover: hover) and (pointer: fine) {
  .identity-switch:hover { color: var(--ink); background: var(--paper-sunken); }
}

.main { min-height: calc(100vh - 58px); }

@media (max-width: 760px) {
  .topbar-inner { gap: 14px; padding: 0 16px; }
  .brand-name { display: none; }
  .identity-label { display: none; }
  .nav-link { padding: 6px 8px; font-size: 13px; }
}
</style>
