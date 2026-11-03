<template>
  <main class="navigation-management" v-loading="loading">
    <header class="navigation-heading"><div><span class="navigation-eyebrow">WORKSPACE SETTINGS</span><h1>导航管理</h1><p>统一维护导航名称、图标与分类，调整后先预览，再发布。</p></div></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false"><el-button text @click="load">重新加载</el-button></el-alert>
    <el-alert v-if="conflict" title="共享草稿或注册目录已更新，本地编辑已保留。重新载入前请保存本地修改内容。" type="warning" :closable="false"><el-button text @click="reload">重新载入</el-button></el-alert>
    <el-alert v-if="blocked" title="编辑权限已撤销，当前输入仍保留。" type="warning" :closable="false"/>
    <div class="navigation-action-bar"><div class="navigation-status"><span class="navigation-status-dot"/><strong>当前版本 V{{ baseVersion }}</strong><span>{{ dirty ? '有未保存修改' : changes.length ? '草稿已保存 · 尚未发布' : '与当前版本一致' }}</span></div><div class="navigation-actions"><el-button @click="historyOpen = true">版本记录</el-button><el-button v-permission="'navigation:write'" :disabled="unavailable" @click="restoreDefaultIcons">恢复默认图标</el-button><el-button v-permission="'navigation:write'" :disabled="!dirty || unavailable || errors.length > 0" :loading="busy" @click="save">保存草稿</el-button><el-button v-permission="'navigation:admin'" type="primary" :disabled="!changes.length || unavailable || errors.length > 0" :loading="busy" @click="preparePublish">预览并发布 ↗</el-button></div></div>
    <div class="navigation-workspace">
      <section class="navigation-panel navigation-structure" aria-label="导航结构"><header><h2>导航结构 <small>{{ nodes.length }}</small></h2><el-button v-permission="'navigation:write'" text :disabled="unavailable" aria-label="新增一级分类" @click="addGroup('')">＋ 新增</el-button></header>
        <div class="navigation-tree-tools"><el-input v-model="query" clearable placeholder="搜索名称、原名或路径" aria-label="搜索导航" :prefix-icon="iconSet.Search"/><el-radio-group v-model="filter" size="small"><el-radio-button value="all">全部</el-radio-button><el-radio-button value="hidden">已隐藏 {{ nodes.filter(n => !n.visible).length }}</el-radio-button></el-radio-group></div>
        <el-tree ref="treeRef" :data="tree" node-key="id" :props="{ label: 'label', children: 'children' }" default-expand-all highlight-current :current-node-key="selectedId" :expand-on-click-node="false" :draggable="!filtered && !unavailable && canWrite" :allow-drop="allowDrop" @node-click="node => selectedId = node.id" @node-drop="drop">
          <template #default="{ data }"><div class="navigation-tree-row" :class="{ 'is-hidden': !data.visible }" :title="data.label" tabindex="0" @keydown.alt.up.prevent="selectedId = data.id; !filtered && canWrite && !unavailable && move(-1)" @keydown.alt.down.prevent="selectedId = data.id; !filtered && canWrite && !unavailable && move(1)"><span class="navigation-drag" aria-hidden="true">⠿</span><el-icon><component :is="iconSet[data.icon] || iconSet.Document"/></el-icon><span class="navigation-tree-label">{{ data.label }}</span><el-icon v-if="data.protected"><Lock/></el-icon><small v-if="!data.visible">隐藏</small></div></template>
        </el-tree><el-empty v-if="!tree.length && !loading" description="没有匹配结果"><el-button @click="query = ''; filter = 'all'">清空筛选</el-button></el-empty>
        <footer>拖动调整同级顺序 · Alt + ↑ / ↓ 排序</footer>
      </section>
      <section class="navigation-panel navigation-editor" aria-label="导航属性"><header><h2>导航属性</h2><span v-if="!canWrite">只读</span></header><NavigationProperties :node="selected" :nodes="nodes" :icons="icons" :errors="errors" :disabled="!canWrite || unavailable" :filtered="filtered" @move="move" @add="addGroup" @remove="removeSelected"/></section>
      <aside class="navigation-panel navigation-preview" aria-label="本人权限实时预览"><header><h2>实时预览</h2><el-button text aria-label="切换折叠预览" @click="compact = !compact"><el-icon><Fold/></el-icon></el-button></header><div class="navigation-preview-mode">本人实际权限 · 当前草稿</div><div class="navigation-preview-sidebar" :class="{ compact }"><div class="navigation-preview-brand">{{ compact ? 'L' : 'LeShine · ARK' }}</div><NavigationPreviewBranch :items="previewItems" :compact="compact" :selected-id="selectedId"/><div v-if="!previewItems.length" class="navigation-preview-empty">当前权限下没有可见入口</div></div><p class="navigation-preview-note">业务提醒由原业务系统提供；此处不模拟待审与异常数量。空分类会自动隐藏。</p></aside>
    </div>
    <el-dialog v-model="publishOpen" title="确认发布导航" width="760px" class="navigation-dialog"><p>当前版本 V{{ baseVersion }} → 新版本。发布后将更新所有主站用户的导航。</p><el-alert v-if="emptyGroups.length" :title="`${emptyGroups.length} 个空分类不会显示在员工侧栏`" type="info" :closable="false"/><el-alert v-if="hiddenChanges.length" :title="`本次隐藏 ${hiddenChanges.length} 个节点，后代入口也将随分类隐藏。原访问权限保留。`" type="warning" :closable="false"/><el-table border class="list-table" v-sticky-scrollbar :data="changes" max-height="380"><el-table-column prop="label" label="导航" min-width="120"/><el-table-column prop="field" label="变更" min-width="100"/><el-table-column label="发布前" min-width="120"><template #default="{ row }">{{ diffValue(row, 'before') }}</template></el-table-column><el-table-column label="发布后" min-width="120"><template #default="{ row }">{{ diffValue(row, 'after') }}</template></el-table-column></el-table><template #footer><el-button @click="publishOpen = false">继续编辑</el-button><el-button v-permission="'navigation:admin'" type="primary" :disabled="unavailable" :loading="busy" @click="publish">确认发布</el-button></template></el-dialog>
    <el-dialog v-model="historyOpen" title="版本记录" width="760px" class="navigation-dialog"><p>恢复会生成新草稿，检查并发布后才对员工生效。</p><el-table border class="list-table" v-sticky-scrollbar :data="versions" max-height="420"><el-table-column label="版本" min-width="90"><template #default="{ row }">V{{ row.version }}</template></el-table-column><el-table-column label="发布时间（北京时间）" min-width="170"><template #default="{ row }">{{ row.version === 0 ? '当前构建默认' : formatBeijingDateTime(row.created_at) }}</template></el-table-column><el-table-column label="发布人" min-width="100"><template #default="{ row }">{{ row.created_by ?? '系统' }}</template></el-table-column><el-table-column prop="description" label="说明" min-width="180"/><el-table-column label="操作" min-width="140"><template #default="{ row }"><el-button v-permission="'navigation:write'" text :disabled="unavailable" @click="restore(row)">恢复为草稿</el-button></template></el-table-column></el-table></el-dialog>
  </main>
</template>
<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import * as iconSet from '@element-plus/icons-vue'
import { Fold, Lock } from '@element-plus/icons-vue'
import { formatBeijingDateTime } from '@/utils/datetime'
import { useAuthStore } from '@/stores/auth'
import { NAV_ENTRIES, MENU_GROUPS } from '@/config/navigation'
import { accessibleNavigationSections } from '@/views/layout/navigationSearch'
import { useCommercePhase } from '@/views/layout/useCommercePhase'
import { confirmAction, isFeedbackCancelled, msgError } from '@/utils/feedback'
import NavigationProperties from './NavigationProperties.vue'
import NavigationPreviewBranch from './NavigationPreviewBranch.vue'
import { childrenOf, reorderNode } from './navigationEditor'
import { useNavigationEditor } from './useNavigationEditor'
import './navigation-management.css'
defineOptions({ name: 'NavigationManagement' })
const { nodes, icons, versions, selectedId, selected, loading, busy, blocked, error, conflict, baseVersion, dirty, errors, changes, emptyGroups, historyOpen, publishOpen, load, save, preparePublish, publish, addGroup, removeSelected, move, restore, restoreDefaultIcons } = useNavigationEditor()
const query = ref(''), filter = ref('all'), compact = ref(false), treeRef = ref()
const auth = useAuthStore(), commercePhase = useCommercePhase()
const canWrite = computed(() => auth.hasPermission('navigation:write'))
const unavailable = computed(() => busy.value || loading.value || blocked.value || conflict.value)
const filtered = computed(() => !!query.value.trim() || filter.value !== 'all')
const tree = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  function branch(parent = '', ancestors = new Set()) {
    return childrenOf(nodes.value, parent).filter(node => !ancestors.has(node.id)).map(node => ({ ...node, children: branch(node.id, new Set([...ancestors, node.id])) })).filter(node => !filtered.value || node.children.length || (!keyword || `${node.label} ${node.path || ''} ${node.originalLabel || ''}`.toLowerCase().includes(keyword)) && (filter.value !== 'hidden' || node.visible === false))
  }
  return branch()
})
const previewItems = computed(() => {
  const sections = accessibleNavigationSections(NAV_ENTRIES, MENU_GROUPS, auth, { commercePhase: commercePhase.value }, nodes.value, iconSet)
  const decorate = items => items.map(item => ({ ...item, id: item.key || item.name, badge: item.textBadge, items: item.items ? decorate(item.items) : undefined }))
  return decorate([...sections.topLevelItems, ...sections.groups])
})
const hiddenChanges = computed(() => changes.value.filter(item => item.field === '显示' && item.after === 'false'))
watch(selectedId, async id => { await nextTick(); treeRef.value?.setCurrentKey(id); document.querySelector(`[data-navigation-preview="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' }) })
function diffValue(row, side) {
  const value = row[side]
  if (row.field === '归属分类') return !value || value === '—' ? '主导航' : nodes.value.find(node => node.id === value)?.label || value
  if (['显示', '同步标题'].includes(row.field)) return value === 'true' ? '开启' : '关闭'
  return ({ text: '名称右侧', icon: '图标右上角', gold: '品牌金', blue: '信息蓝', neutral: '中性灰' })[value] || value || '—'
}
function allowDrop(source, target, type) { return type !== 'inner' && source.data.parent === target.data.parent && !filtered.value && !unavailable.value }
function drop(source, target, type) {
  if (!allowDrop(source, target, type)) return
  if (type === 'before') reorderNode(nodes.value, source.data.id, target.data.id)
  else {
    const siblings = childrenOf(nodes.value, source.data.parent), sourceItem = nodes.value.find(n => n.id === source.data.id), targetItem = nodes.value.find(n => n.id === target.data.id)
    siblings.splice(siblings.indexOf(sourceItem), 1); siblings.splice(siblings.indexOf(targetItem) + 1, 0, sourceItem); siblings.forEach((n, i) => { n.order = i })
  }
}
async function reload() {
  try { if (dirty.value) await confirmAction('重新载入会替换本地未保存修改。确定继续？', '重新载入', { confirmButtonText: '重新载入', cancelButtonText: '保留编辑' }); await load() }
  catch (e) { if (!isFeedbackCancelled(e)) msgError('加载失败', e) }
}
</script>
