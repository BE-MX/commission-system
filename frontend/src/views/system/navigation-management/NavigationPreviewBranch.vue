<template>
  <div class="navigation-preview-branch">
    <template v-for="item in items" :key="item.key || item.id || item.path || item.label">
      <div class="navigation-preview-item" :class="{ 'is-selected': selectedId === item.id }" :title="item.label || item.title" :data-navigation-preview="item.id">
        <span class="navigation-preview-icon"><el-icon><component :is="typeof item.icon === 'string' ? iconSet[item.icon] : item.icon || iconSet.Folder" /></el-icon><span v-if="item.badge && item.badgePlace === 'icon'" class="navigation-text-badge icon-place" :class="item.badgeTone">{{ item.badge }}</span></span>
        <span v-if="!compact" class="navigation-preview-label">{{ item.label || item.title }} <span v-if="item.badge && item.badgePlace !== 'icon'" class="navigation-text-badge" :class="item.badgeTone">{{ item.badge }}</span></span><span v-if="item.items?.length && !compact">⌄</span>
      </div>
      <NavigationPreviewBranch v-if="item.items?.length && !compact" :items="item.items" :selected-id="selectedId" />
    </template>
  </div>
</template>
<script setup>
import * as iconSet from '@element-plus/icons-vue'
defineProps({ items: { type: Array, default: () => [] }, compact: Boolean, selectedId: String })
</script>
