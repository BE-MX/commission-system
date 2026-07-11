<template>
  <section class="approval-card">
    <div class="section-title"><el-icon><Connection /></el-icon><span>审批路线</span></div>
    <div class="steps">
      <div v-for="(step, index) in steps" :key="step.code" class="step" :class="step.state">
        <div class="node"><el-icon v-if="step.state === 'done'"><Check /></el-icon><span v-else>{{ index + 1 }}</span></div>
        <div><strong>{{ step.label }}</strong><span>{{ stateLabel(step.state) }}</span></div>
      </div>
    </div>
    <div v-if="caseData.has_compensation" class="route-note">涉及价值补偿，主管通过后必须由销售总监终审。</div>
    <div v-else class="route-note safe">不涉及赔偿，直属主管通过即完成审批。</div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { approvalSteps } from '../aftersalesRules'
const props = defineProps({ caseData: { type: Object, required: true } })
const steps = computed(() => approvalSteps(props.caseData))
function stateLabel(state) { return ({ done: '已完成', active: '当前节点', skipped: '自动跳过', pending: '待处理' })[state] }
</script>

<style scoped>
.approval-card { padding: 18px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--card-bg); box-shadow: var(--card-shadow); }.section-title { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; color: var(--text-primary); font: 700 15px/1.3 var(--font-display); }.steps { display: grid; gap: 10px; }.step { display: grid; grid-template-columns: 28px 1fr; gap: 10px; align-items: center; color: var(--text-muted); }.node { display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid var(--border-color); border-radius: 50%; background: var(--toolbar-bg); font-size: 11px; }.step div:last-child { display: flex; justify-content: space-between; gap: 10px; }.step strong { color: var(--text-secondary); font-size: 13px; }.step span { font-size: 11px; }.step.done .node { color: var(--color-success-text); border-color: var(--color-success); background: var(--color-success-bg); }.step.active .node { color: var(--text-primary); border-color: var(--color-primary); background: var(--color-gold-soft); }.step.active strong { color: var(--text-primary); }.step.skipped .node { color: var(--text-muted); }.route-note { padding: 9px 10px; margin-top: 14px; border-radius: 8px; color: var(--color-warning-text); background: var(--color-warning-bg); font-size: 12px; }.route-note.safe { color: var(--color-success-text); background: var(--color-success-bg); }
</style>
