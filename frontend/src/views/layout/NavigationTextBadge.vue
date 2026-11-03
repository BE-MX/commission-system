<template>
  <span v-if="item.textBadge && !suppressed && (item.badgePlace === 'icon') === icon" class="navigation-text-badge"
    :class="[`tone-${item.badgeTone}`, { 'at-icon': icon }]">{{ item.textBadge }}</span>
</template>
<script setup>
defineProps({ item: { type: Object, required: true }, icon: Boolean, suppressed: Boolean })
</script>
<style scoped>
.navigation-text-badge { font-size: 10px; line-height: 15px; border-radius: 3px; padding: 0 4px; margin-left: 6px; flex-shrink: 0; background: var(--tag-gold-bg); color: var(--tag-gold-text); }
.tone-blue { color: var(--tag-info-text); background: var(--tag-info-bg); }
.tone-neutral { color: var(--text-secondary); background: var(--tag-neutral-bg); }
.at-icon { position: absolute; top: -8px; right: -12px; margin: 0; white-space: nowrap; }
</style>
