<template>
  <aside class="knowledge-sidebar" :class="{ collapsed }">
    <div v-if="!collapsed" class="search-box">
      <el-input
        ref="searchInput"
        :model-value="searchQuery"
        clearable
        placeholder="搜索已发布知识"
        aria-label="搜索已发布知识"
        @update:model-value="$emit('update:search-query', $event)"
        @keyup.enter="$emit('search')"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <button class="search-submit" type="button" aria-label="搜索已发布知识" @click="$emit('search')">
        <el-icon><Search /></el-icon>
      </button>
    </div>

    <header v-if="!collapsed" class="sidebar-header">
      <div class="sidebar-title">
        <span class="eyebrow">知识空间</span>
        <h2>企业知识库</h2>
      </div>
      <div class="sidebar-actions">
        <button v-if="canCreateLibrary" class="sidebar-action" type="button" @click="$emit('create-library')">
          <el-icon><Plus /></el-icon><span>新建知识库</span>
        </button>
        <button v-if="canReview" class="sidebar-action" type="button" @click="$emit('open-approvals')">
          <el-icon><Stamp /></el-icon><span>审批队列</span>
        </button>
      </div>
    </header>

    <div v-else class="collapsed-actions" aria-label="知识库快捷操作">
      <el-tooltip content="搜索已发布知识" placement="right">
        <button class="compact-action" type="button" aria-label="搜索已发布知识" @click="expandForSearch">
          <el-icon><Search /></el-icon>
        </button>
      </el-tooltip>
      <el-tooltip v-if="canCreateLibrary" content="新建知识库" placement="right">
        <button class="compact-action" type="button" aria-label="新建知识库" @click="$emit('create-library')">
          <el-icon><Plus /></el-icon>
        </button>
      </el-tooltip>
      <el-tooltip v-if="canReview" content="审批队列" placement="right">
        <button class="compact-action" type="button" aria-label="审批队列" @click="$emit('open-approvals')">
          <el-icon><Stamp /></el-icon>
        </button>
      </el-tooltip>
    </div>

    <div class="sidebar-body" :class="{ 'has-tree': selectedLibraryId && !collapsed }">
      <div v-if="libraries.length && !collapsed" class="library-list" aria-label="知识库列表">
        <div
          v-for="library in libraries"
          :key="library.id"
          class="library-row"
          :class="{ active: library.id === selectedLibraryId }"
        >
          <button
            class="library-item"
            type="button"
            :aria-pressed="library.id === selectedLibraryId"
            @click="$emit('select-library', library.id)"
          >
            <el-tooltip :content="categoryMeta(library).label" placement="top">
              <span
                class="category-icon"
                :class="categoryMeta(library).tone"
                role="img"
                :aria-label="categoryMeta(library).label"
              ><el-icon><Collection /></el-icon></span>
            </el-tooltip>
            <OverflowTooltip :text="library.name" :focusable="false" />
          </button>
          <el-tooltip v-if="canManageMembers && library.role === 'admin'" content="成员权限" placement="top">
            <button
              class="row-action member-action"
              type="button"
              :aria-label="`管理知识库 ${library.name} 的成员权限`"
              @click.stop="$emit('open-members', library)"
            ><el-icon><User /></el-icon></button>
          </el-tooltip>
          <el-tag class="role-tag" size="small" effect="plain">{{ roleLabel(library.role) }}</el-tag>
          <el-tooltip v-if="canDeleteLibrary && library.role === 'admin'" content="删除知识库" placement="top">
            <button class="row-delete" type="button" :aria-label="`删除知识库 ${library.name}`" @click.stop="$emit('delete-library', library)">
              <el-icon><Delete /></el-icon>
            </button>
          </el-tooltip>
        </div>
      </div>
      <el-empty v-else-if="!libraries.length && !collapsed" description="还没有可访问的知识库" :image-size="72" />

      <div v-if="libraries.length && collapsed" class="collapsed-libraries" aria-label="知识库列表">
        <el-tooltip
          v-for="library in libraries"
          :key="library.id"
          :content="`${categoryMeta(library).label} · ${library.name}`"
          placement="right"
        >
          <button
            class="compact-action library-compact"
            :class="{ active: library.id === selectedLibraryId }"
            type="button"
            :aria-label="`${categoryMeta(library).label}知识库 ${library.name}`"
            :aria-pressed="library.id === selectedLibraryId"
            @click="$emit('select-library', library.id)"
          >
            <span class="category-icon" :class="categoryMeta(library).tone" aria-hidden="true">
              <el-icon><Collection /></el-icon>
            </span>
          </button>
        </el-tooltip>
      </div>

      <div v-if="selectedLibraryId && !collapsed" class="tree-section">
        <div class="tree-heading">
          <span>目录</span>
          <div v-if="canWrite" class="tree-actions">
            <el-tooltip content="新建目录">
              <button class="create-node create-folder" type="button" aria-label="新建目录" @click="$emit('create-node', 'folder')">
                <el-icon><FolderAdd /></el-icon>
              </button>
            </el-tooltip>
            <el-tooltip content="新建文档">
              <button class="create-node create-document" type="button" aria-label="新建文档" @click="$emit('create-node', 'document')">
                <el-icon><DocumentAdd /></el-icon>
              </button>
            </el-tooltip>
          </div>
        </div>
        <el-tree
          :data="tree"
          node-key="id"
          default-expand-all
          highlight-current
          :expand-on-click-node="false"
          @node-click="node => node.node_type === 'document' && $emit('select-document', node.id)"
        >
          <template #default="{ data }">
            <span class="tree-node">
              <el-icon><Folder v-if="data.node_type === 'folder'" /><Document v-else /></el-icon>
              <OverflowTooltip :text="data.title" :focusable="false" />
              <span v-if="data.node_type === 'document'" class="status-dot" :class="data.status" :title="statusLabel(data.status)" />
              <el-tooltip v-if="canDeleteNode" :content="data.node_type === 'folder' ? '删除目录' : '删除文档'">
                <button class="row-delete" type="button" :aria-label="`删除${data.node_type === 'folder' ? '目录' : '文档'} ${data.title}`" @click.stop="$emit('delete-node', data)">
                  <el-icon><Delete /></el-icon>
                </button>
              </el-tooltip>
            </span>
          </template>
        </el-tree>
      </div>
    </div>

    <div class="collapse-footer">
      <el-tooltip :content="collapsed ? '展开侧栏' : '收起侧栏'" :placement="collapsed ? 'right' : 'top'">
        <button
          class="collapse-toggle"
          type="button"
          :aria-label="collapsed ? '展开知识库侧栏' : '收起知识库侧栏'"
          :aria-expanded="!collapsed"
          @click="$emit('toggle-collapse')"
        >
          <el-icon><Expand v-if="collapsed" /><Fold v-else /></el-icon>
          <span v-if="!collapsed">收起侧栏</span>
        </button>
      </el-tooltip>
    </div>
  </aside>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { LIBRARY_CATEGORIES } from '../knowledgeUi.js'
import OverflowTooltip from './OverflowTooltip.vue'

const props = defineProps({
  libraries: { type: Array, default: () => [] },
  selectedLibraryId: { type: Number, default: null },
  tree: { type: Array, default: () => [] },
  searchQuery: { type: String, default: '' },
  collapsed: Boolean,
  canWrite: Boolean,
  canCreateLibrary: Boolean,
  canReview: Boolean,
  canManageMembers: Boolean,
  canDeleteLibrary: Boolean,
  canDeleteNode: Boolean,
})

const emit = defineEmits([
  'update:search-query',
  'search',
  'toggle-collapse',
  'select-library',
  'select-document',
  'create-library',
  'create-node',
  'open-approvals',
  'open-members',
  'delete-library',
  'delete-node',
])

const searchInput = ref(null)
const focusSearchAfterExpand = ref(false)
const labels = { viewer: '只读', editor: '编辑', reviewer: '审核', admin: '管理' }
const roleLabel = role => labels[role] || role
const categoryMeta = library => LIBRARY_CATEGORIES[library.category]
const statusLabels = { draft: '草稿', pending: '审批中', published: '已发布' }
const statusLabel = status => statusLabels[status] || status

function expandForSearch() {
  if (!props.collapsed) return nextTick(() => searchInput.value?.focus())
  focusSearchAfterExpand.value = true
  emit('toggle-collapse')
}

watch(() => props.collapsed, collapsed => {
  if (collapsed || !focusSearchAfterExpand.value) return
  focusSearchAfterExpand.value = false
  nextTick(() => searchInput.value?.focus())
})
</script>

<style scoped>
.knowledge-sidebar { display: flex; min-width: 0; min-height: 0; flex-direction: column; overflow: hidden; border-right: 1px solid var(--border-color); background: var(--surface-card, var(--card-bg)); }
.knowledge-sidebar.collapsed { align-items: center; }
.search-box { display: grid; grid-template-columns: minmax(0, 1fr) 36px; gap: 8px; padding: 12px; border-bottom: 1px solid var(--border-color); }
.search-submit, .sidebar-action, .compact-action, .row-action, .row-delete, .create-node, .collapse-toggle, .library-item { border: 0; cursor: pointer; }
.search-submit, .sidebar-action, .collapsed-actions .compact-action, .row-action, .row-delete, .create-node { transition: transform 120ms cubic-bezier(.23, 1, .32, 1), color 120ms ease, background-color 120ms ease, opacity 120ms ease; }
.library-item, .library-compact, .collapse-toggle { transition: color 120ms ease, background-color 120ms ease, opacity 120ms ease; }
.search-submit, .compact-action, .row-action, .row-delete, .create-node { display: grid; place-items: center; }
.search-submit { width: 36px; height: 32px; border-radius: 8px; color: var(--card-bg); background: var(--color-primary); }
.sidebar-header { display: grid; gap: 12px; padding: 14px 12px 12px; border-bottom: 1px solid var(--border-color); }
.sidebar-title { min-width: 0; }
.sidebar-header h2 { margin: 3px 0 0; color: var(--text-primary); font-size: 17px; }
.eyebrow { color: var(--color-primary); font-size: 11px; font-weight: 700; letter-spacing: .08em; }
.sidebar-actions { display: flex; gap: 6px; }
.sidebar-action { display: inline-flex; min-width: 0; height: 32px; flex: 1; align-items: center; justify-content: center; gap: 5px; padding: 0 8px; border: 1px solid var(--border-color); border-radius: 8px; color: var(--text-secondary); background: var(--surface-card, var(--card-bg)); font-size: 12px; white-space: nowrap; }
.sidebar-body { display: flex; width: 100%; flex: 1; min-height: 0; flex-direction: column; overflow: hidden; }
.collapsed-actions, .collapsed-libraries { display: grid; justify-items: center; gap: 6px; width: 100%; padding: 10px 0; }
.collapsed-actions { border-bottom: 1px solid var(--border-color); }
.collapsed-libraries { min-height: 0; flex: 1; align-content: start; overflow-y: auto; }
.compact-action { width: 38px; height: 38px; border-radius: 9px; color: var(--text-secondary); background: transparent; }
.library-list { display: grid; min-height: 0; flex: 1; align-content: start; gap: 6px; padding: 12px; overflow-y: auto; }
.sidebar-body.has-tree .library-list { max-height: 38%; flex: 0 1 auto; }
.library-row { display: grid; min-width: 0; grid-template-columns: minmax(0, 1fr) auto auto auto; align-items: center; gap: 3px; border: 1px solid transparent; border-radius: var(--radius-md, 8px); }
.library-row.active { border-color: var(--color-primary); background: var(--color-primary-light); }
.library-item { display: grid; min-width: 0; grid-template-columns: 30px minmax(0, 1fr); align-items: center; gap: 7px; padding: 7px 5px 7px 7px; border-radius: inherit; color: var(--text-secondary); background: transparent; text-align: left; }
.library-row.active .library-item { color: var(--text-primary); }
.category-icon { display: grid; width: 28px; height: 28px; flex: 0 0 auto; place-items: center; border-radius: 7px; }
.category-icon.company { color: var(--color-primary); background: var(--color-primary-light); }
.category-icon.department { color: var(--color-info-text); background: var(--color-info-bg); }
.category-icon.personal { color: var(--color-success-text); background: var(--color-success-bg); }
.library-compact.active { box-shadow: inset 0 0 0 1px var(--color-primary); background: var(--color-primary-light); }
.role-tag { flex: 0 0 auto; }
.row-action, .row-delete, .create-node { width: 28px; height: 28px; flex: 0 0 auto; border-radius: 6px; background: transparent; }
.member-action { color: var(--color-primary); }
.row-delete { color: var(--color-danger); }
.tree-section { display: flex; flex: 1; min-height: 0; flex-direction: column; overflow: hidden; padding: 8px 12px 10px; }
.tree-heading { display: flex; align-items: center; justify-content: space-between; padding: 10px 8px; color: var(--text-muted-blue); font-size: 12px; font-weight: 700; letter-spacing: .06em; }
.tree-actions { display: flex; gap: 4px; }
.create-folder { color: var(--card-bg); background: var(--color-info-text); }
.create-document { color: var(--card-bg); background: var(--color-primary); }
.create-folder :deep(svg), .create-document :deep(svg) { fill: currentColor; }
.tree-section :deep(.el-tree) { flex: 1; min-height: 0; overflow-y: auto; }
.tree-node { display: grid; width: 100%; min-width: 0; grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: center; gap: 7px; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-muted); }
.status-dot.pending { background: var(--color-primary); }
.status-dot.published { background: var(--color-success); }
.collapse-footer { width: 100%; flex: 0 0 auto; padding: 8px; border-top: 1px solid var(--border-color); }
.collapse-toggle { display: flex; width: 100%; height: 34px; align-items: center; justify-content: center; gap: 7px; border-radius: 8px; color: var(--text-secondary); background: transparent; font-size: 12px; }
.search-submit:focus-visible, .sidebar-action:focus-visible, .compact-action:focus-visible, .row-action:focus-visible, .row-delete:focus-visible, .create-node:focus-visible, .collapse-toggle:focus-visible, .library-item:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
@media (hover: hover) and (pointer: fine) {
  .search-submit:active:not(:focus-visible), .sidebar-action:active:not(:focus-visible), .collapsed-actions .compact-action:active:not(:focus-visible), .row-action:active:not(:focus-visible), .row-delete:active:not(:focus-visible), .create-node:active:not(:focus-visible) { transform: scale(.97); }
  .row-delete { opacity: 0; }
  .library-row:hover .row-delete, .tree-node:hover .row-delete, .row-delete:focus-visible { opacity: 1; }
  .sidebar-action:hover, .compact-action:hover, .library-item:hover, .collapse-toggle:hover { color: var(--text-primary); background: var(--color-primary-light); }
  .member-action:hover { background: var(--color-primary-light); }
  .row-delete:hover { background: var(--color-danger-bg); }
  .create-folder:hover { color: var(--card-bg); background: var(--color-info-text); opacity: .88; }
  .create-document:hover { color: var(--card-bg); background: var(--color-primary-hover); }
  .search-submit:hover { background: var(--color-primary-hover); }
}
@media (prefers-reduced-motion: reduce) {
  .search-submit, .sidebar-action, .compact-action, .row-action, .row-delete, .create-node, .collapse-toggle, .library-item { transition-property: color, background-color, opacity; }
  .search-submit:active:not(:focus-visible), .sidebar-action:active:not(:focus-visible), .collapsed-actions .compact-action:active:not(:focus-visible), .row-action:active:not(:focus-visible), .row-delete:active:not(:focus-visible), .create-node:active:not(:focus-visible) { transform: none; }
}
</style>
