<template><main class="handoff"><div class="eyebrow">LESHINE ARK · 私海助理</div><h1>继续查看今日跟进</h1><p>请使用收到早报的本人账号继续。</p><el-alert v-if="error" :title="error" type="error" :closable="false" /><el-button type="primary" :loading="busy" :disabled="!ticket" @click="redeem">继续</el-button><el-button @click="login">登录方舟</el-button><p class="muted">链接过期或已使用时，可登录后从私海助理查看。</p></main></template>
<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clientDeskApi } from '@/api/clientDesk'
import { safeDestination, errorText } from './deskController'
const route = useRoute(), router = useRouter()
const ticket = new URLSearchParams(route.hash.slice(1)).get('ticket') || ''
const busy = ref(false), error = ref(ticket ? '' : '链接缺少有效票据，请登录后查看私海助理。')
function login() { router.push({ path: '/login', query: { redirect: route.fullPath } }) }
async function redeem() {
  if (busy.value || !ticket) return
  busy.value = true; error.value = ''
  try { const result = await clientDeskApi.redeem(ticket); const url = safeDestination(result.url); if (!url) throw new Error('跳转目标不可用，请登录方舟查看。'); window.history.replaceState(null, '', '/client-desk/handoff'); if (url.startsWith('/')) await router.replace(url); else window.location.replace(url) }
  catch (e) { const code = e.response?.data?.detail?.code || e.response?.data?.code; if (e.response?.status === 401 || code === 'AUTH_REQUIRED') login(); else error.value = errorText(e) }
  finally { busy.value = false }
}
</script>
<style scoped>.handoff{max-width:480px;margin:12vh auto;padding:28px;color:var(--text-primary)}.eyebrow{font-size:11px;letter-spacing:.1em;color:var(--button-primary-text)}h1{font-size:26px;letter-spacing:-.03em}.muted{font-size:12px;color:var(--text-secondary)}.el-button{margin-top:16px}</style>
