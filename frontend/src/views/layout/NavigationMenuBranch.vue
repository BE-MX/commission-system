<template>
  <el-sub-menu ref="branch" :index="group.key" popper-class="ark-navigation-popup" :aria-label="group.title" tabindex="0"
    :data-nav-group-trigger="group.key" @keydown.enter.self.prevent.stop="activateGroup" @keydown.space.self.prevent.stop="activateGroup" @keydown.esc.prevent.stop="closeGroup">
    <template #title>
      <el-icon class="nav-group-icon"><component :is="group.icon" /><NavigationTextBadge v-if="group.iconBadge" :item="{ textBadge: group.iconBadge, badgePlace: 'icon', badgeTone: 'gold' }" icon /><NavigationTextBadge :item="group" icon /></el-icon>
      <span class="nav-title" :title="group.title">{{ group.title }}</span><NavigationTextBadge :item="group" />
    </template>
    <template v-for="item in group.items" :key="item.key || item.path">
      <NavigationMenuBranch v-if="item.items" :group="item" :collapsed="collapsed" :pending-reviews="pendingReviews"
        :document-anomalies="documentAnomalies" :document-badge-title="documentBadgeTitle"
        @quick-add="(event, entry) => emit('quick-add', event, entry)" @outbound-problems="emit('outbound-problems')" />
      <a v-else-if="item.external" class="el-menu-item external-item" :data-nav-group="group.key" :href="item.path" target="_blank" rel="noopener noreferrer" :aria-label="item.title">
        <el-icon class="nav-group-icon"><component :is="item.icon" /><NavigationTextBadge :item="item" icon /></el-icon>
        <span class="nav-title" :title="item.title">{{ item.title }}</span><NavigationTextBadge :item="item" /><el-icon><TopRight /></el-icon>
      </a>
      <el-menu-item v-else :index="item.path" :data-nav-group="group.key" :aria-label="item.title" tabindex="0" @keydown.enter.prevent.stop="activateItem" @keydown.space.prevent.stop="activateItem">
        <el-icon class="nav-group-icon"><component :is="item.icon" /><NavigationTextBadge :item="item" icon :suppressed="hasBusinessBadge(item)" /></el-icon>
        <template #title>
          <el-badge v-if="item.badge === 'domesticReviews'" :value="pendingReviews ?? 0" :max="Number.MAX_SAFE_INTEGER" :hidden="pendingReviews == null || pendingReviews === 0" class="nav-review-badge" :aria-label="pendingReviews == null ? `${item.title}，待审核数量暂未获取` : `${item.title}，${pendingReviews}笔待审核`"><span class="nav-title" :title="item.title">{{ item.title }}</span></el-badge>
          <span v-else class="nav-document-label" :title="documentBadgeTitle(item)"><span class="nav-title" :title="item.title">{{ item.title }}</span><template v-if="documentAnomalies[item.anomalyDomain]?.has_anomaly"><button v-if="item.anomalyDomain === 'outbound'" type="button" class="nav-document-anomaly" :aria-label="documentBadgeTitle(item)" @click.stop.prevent="emit('outbound-problems')" @keydown.enter.stop @keydown.space.stop>!</button><span v-else class="nav-document-anomaly" :aria-label="documentBadgeTitle(item)">!</span></template></span>
          <NavigationTextBadge :item="item" :suppressed="hasBusinessBadge(item)" />
          <button v-if="!collapsed && item.name" v-permission="'task:write'" type="button" class="nav-add" data-quick-task-trigger :aria-label="`为「${item.title}」记任务`" :title="`为「${item.title}」记任务`" @click.stop.prevent="emit('quick-add', $event, item)">+</button>
        </template>
      </el-menu-item>
    </template>
  </el-sub-menu>
</template>
<script setup>
import { nextTick, ref } from 'vue'
import { TopRight } from '@element-plus/icons-vue'
import NavigationTextBadge from './NavigationTextBadge.vue'
const props = defineProps({ group: { type: Object, required: true }, collapsed: Boolean, pendingReviews: { default: null }, documentAnomalies: { type: Object, default: () => ({}) }, documentBadgeTitle: { type: Function, required: true } })
const branch = ref(null)
function closeGroup(event) {
  const element = branch.value?.$el
  const title = element?.querySelector(':scope > .el-sub-menu__title')
  if (title?.getAttribute('aria-expanded') === 'true' || element?.classList.contains('is-opened')) title?.click()
  element?.focus()
}
const emit = defineEmits(['quick-add', 'outbound-problems'])
function hasBusinessBadge(item) { return (item.badge === 'domesticReviews' && props.pendingReviews > 0) || props.documentAnomalies[item.anomalyDomain]?.has_anomaly }
function activateItem(event) { if (!event.repeat && event.target === event.currentTarget) event.currentTarget.click() }
async function activateGroup(event) {
  if (event.repeat || event.target !== event.currentTarget) return
  event.currentTarget.querySelector(':scope > .el-sub-menu__title')?.click()
  if (props.collapsed) {
    await nextTick()
    ;[...document.querySelectorAll('[data-nav-group]')].find(item => item.dataset.navGroup === props.group.key && item.getClientRects().length)?.focus()
  }
}
</script>
<style scoped src="./navigationQuickTask.css"></style>

<style scoped>
.nav-group-icon { position: relative; overflow: visible; }
.nav-title { display: inline-block; max-width: 150px; overflow: hidden; text-overflow: ellipsis; vertical-align: middle; }
.external-item { text-decoration: none; }
.nav-review-badge { margin-right: 22px; line-height: 20px; }
.nav-document-label { position: relative; margin-right: 14px; }
.nav-document-anomaly { position: absolute; right: -16px; top: -8px; width: 16px; height: 16px; border: 0; padding: 0; display: grid; place-items: center; border-radius: 50%; background: var(--color-gold); color: var(--sidebar-bg-from); font-size: 10px; font-weight: 800; cursor: pointer; }
.nav-document-anomaly:focus-visible { outline: 2px solid var(--color-gold); outline-offset: 2px; }
</style>
