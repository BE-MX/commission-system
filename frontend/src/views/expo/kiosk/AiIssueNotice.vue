<template>
  <Transition name="xconfirm">
    <div v-if="issue?.state === 'retrying'" class="xk-ai-retry" role="status">
      {{ issue.message }}
    </div>
  </Transition>

  <Transition name="xconfirm">
    <div v-if="issue?.state === 'contact_admin'" class="xk-ai-contact">
      <div class="xk-ai-contact-panel" role="alertdialog" aria-modal="true">
        <div class="xac-title">请联系管理员</div>
        <div class="xac-sub">
          {{ issue.stage === 'analysis' ? '人脸识别' : '效果图合成' }}环节发生问题
        </div>
        <div class="xac-phone">管理员电话：{{ issue.admin_phone || '暂未配置' }}</div>
        <button
          class="xk-btn xac-action"
          :disabled="flow.contactAdminPending.value || issue.notified || issue.notifying"
          @click="flow.contactAdmin()"
        >
          {{ issue.notified ? '已通知管理员' : ((flow.contactAdminPending.value || issue.notifying) ? '正在通知…' : '联系管理员') }}
        </button>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { computed, inject } from 'vue'

const flow = inject('tryonFlow')
const issue = computed(() => flow.aiIssue.value)
</script>

<style scoped>
.xk-ai-retry {
  position: absolute;
  left: 50%; bottom: calc(24px + env(safe-area-inset-bottom)); z-index: 71;
  width: min(88vw, 620px); transform: translateX(-50%);
  padding: 12px 22px; border: 1px solid var(--xk-gold-line); border-radius: 24px;
  background: rgba(20, 17, 13, 0.94); color: var(--xk-gold-hi);
  box-shadow: 0 8px 28px rgba(6, 5, 3, 0.42);
  text-align: center; font-size: 13px; letter-spacing: 0.08em;
}
.xk-ai-contact {
  position: absolute; inset: 52px 0 0; z-index: 74;
  display: flex; align-items: center; justify-content: center;
  background: rgba(6, 5, 3, 0.78);
  -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px);
}
.xk-ai-contact-panel {
  width: min(82vw, 440px); padding: 34px 30px; border: 1px solid var(--xk-gold-line);
  border-radius: 22px; background: var(--xk-ink-2); text-align: center;
  box-shadow: 0 18px 54px rgba(6, 5, 3, 0.58);
}
.xac-title {
  color: var(--xk-warn); font-family: 'Noto Serif SC', serif;
  font-size: 24px; letter-spacing: 0.16em;
}
.xac-sub { margin-top: 12px; color: var(--xk-mut); font-size: 13px; letter-spacing: 0.08em; }
.xac-phone { margin-top: 22px; color: var(--xk-gold-hi); font-size: 17px; letter-spacing: 0.08em; }
.xac-action { margin: 28px auto 0; min-width: 220px; }
</style>
