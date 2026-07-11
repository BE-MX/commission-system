<template>
  <div class="review-actions">
    <div><strong>{{ waiver ? '当前需要你确认是否豁免取证要求' : '当前需要你的审核决定' }}</strong><span>{{ waiver ? '请核对客户无法继续补证的原因；同意后仍需完成正式方案初审。' : '退回或拒绝必须填写原因；赔偿方案通过前会再次确认金额。' }}</span></div>
    <div class="buttons">
      <GlassButton v-if="!waiver" variant="secondary" left-icon="RefreshLeft" @click="$emit('review', 'return')">退回补充</GlassButton>
      <GlassButton variant="danger" left-icon="CloseBold" @click="$emit('review', 'reject')">拒绝</GlassButton>
      <GlassButton variant="success" left-icon="Check" @click="$emit('review', 'approve')">{{ waiver ? '同意豁免' : '通过' }}</GlassButton>
    </div>
  </div>
</template>

<script setup>
defineProps({ waiver: Boolean })
defineEmits(['review'])
</script>

<style scoped>
.review-actions { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 14px 18px; border: 1px solid var(--color-gold-muted); border-radius: 12px; background: var(--color-gold-soft); box-shadow: var(--card-shadow); }.review-actions > div:first-child { display: flex; flex-direction: column; gap: 3px; }.review-actions strong { color: var(--text-primary); font-size: 13px; }.review-actions span { color: var(--text-secondary); font-size: 11px; }.buttons { display: flex; gap: 8px; flex-shrink: 0; }
@media (max-width: 760px) { .review-actions { align-items: stretch; flex-direction: column; }.buttons { flex-wrap: wrap; } }
</style>
