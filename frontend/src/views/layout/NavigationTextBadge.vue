<template>
  <span v-if="item.textBadge && !suppressed && (item.badgePlace === 'icon') === icon" class="navigation-text-badge"
    :class="[`tone-${item.badgeTone}`, { 'at-icon': icon }]" :title="item.textBadge">{{ item.textBadge }}</span>
</template>
<script setup>
defineProps({ item: { type: Object, required: true }, icon: Boolean, suppressed: Boolean })
</script>
<style scoped>
.navigation-text-badge {
  --badge-tint: var(--color-gold);
  display: inline-block;
  flex-shrink: 0;
  padding: 1px 4px;
  margin-left: 6px;
  border: 1px solid color-mix(in srgb, var(--badge-tint) 44%, transparent);
  border-radius: 4px;
  background: linear-gradient(160deg, color-mix(in srgb, var(--badge-tint) 20%, transparent), color-mix(in srgb, var(--badge-tint) 7%, transparent));
  color: var(--badge-tint);
  box-shadow: inset 0 1px 0 color-mix(in srgb, var(--card-bg) 24%, transparent), 0 0 9px color-mix(in srgb, var(--badge-tint) 22%, transparent);
  backdrop-filter: blur(8px) saturate(1.35);
  -webkit-backdrop-filter: blur(8px) saturate(1.35);
  text-shadow: 0 0 6px color-mix(in srgb, var(--badge-tint) 22%, transparent);
  font-family: var(--font-body);
  font-size: 10px;
  font-style: normal;
  font-weight: 600;
  line-height: 14px;
  white-space: nowrap;
}
.tone-blue { --badge-tint: var(--tag-info-border); }
.tone-neutral { --badge-tint: var(--tag-neutral-border); }
.at-icon { position: absolute; bottom: -9px; right: -12px; z-index: 1; margin: 0; padding: 1px 3px; font-size: 8px; line-height: 10px; pointer-events: none; }
.el-menu-item.is-active .navigation-text-badge { --badge-tint: var(--sidebar-bg-from); text-shadow: none; }
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .navigation-text-badge { background: color-mix(in srgb, var(--sidebar-bg-from) 88%, var(--badge-tint)); }
}
@media (prefers-reduced-transparency: reduce) {
  .navigation-text-badge { backdrop-filter: none; -webkit-backdrop-filter: none; background: color-mix(in srgb, var(--sidebar-bg-from) 88%, var(--badge-tint)); }
}
</style>
