<template>
  <main class="public-radar">
    <header class="public-head"><div class="brand-mark">L</div><div><b>项目雷达</b><span>LeShine Ark · 短期签名详情</span></div><StatusBadge type="success">只读</StatusBadge></header>
    <div v-loading="loading" class="public-card">
      <el-result v-if="error" icon="warning" title="详情链接无效或已过期" :sub-title="error" />
      <ProjectRadarDetail v-else-if="item" :item="item" read-only />
      <el-skeleton v-else :rows="8" animated />
    </div>
    <p class="public-note">此链接仅可查看该项目，24 小时后失效。修改状态或笔记请登录方舟。</p>
  </main>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import StatusBadge from '@/components/StatusBadge.vue'
import ProjectRadarDetail from './components/ProjectRadarDetail.vue'
import { getPublicRadarSubscription } from '@/api/projectRadar'
import { errorMessage } from '@/utils/errors'

const route = useRoute()
const item = ref(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const response = await getPublicRadarSubscription(route.params.subscriptionId, {
      user_id: route.query.user_id, token: route.query.token,
    })
    item.value = response.data
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.public-radar { min-height: 100vh; padding: 22px 16px 40px; background: linear-gradient(155deg, var(--dash-wash-from), var(--dash-wash-mid) 55%, var(--dash-wash-to)); }
.public-head { display: flex; align-items: center; gap: 12px; max-width: 760px; margin: 0 auto 16px; }
.public-head > div:nth-child(2) { display: grid; flex: 1; }
.public-head span { color: var(--text-muted); font-size: 12px; }
.brand-mark { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 10px; background: linear-gradient(135deg, var(--color-gold), var(--color-primary)); color: var(--button-primary-ink); font-weight: 800; }
.public-card { box-sizing: border-box; width: 100%; max-width: 760px; min-width: 0; min-height: 240px; margin: auto; padding: 22px 24px; border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow); }
.public-note { max-width: 760px; margin: 12px auto; color: var(--text-muted); font-size: 12px; text-align: center; }
@media (max-width: 600px) { .public-radar { padding: 12px 0 0; } .public-head, .public-note { padding-inline: 14px; } .public-card { padding: 16px; border-radius: 0; } }
</style>
