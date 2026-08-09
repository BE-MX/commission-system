<template>
  <aside class="knowledge-sidebar">
    <header class="sidebar-header">
      <div>
        <span class="eyebrow">知识空间</span>
        <h2>企业知识库</h2>
      </div>
      <GlassButton v-if="canCreateLibrary" variant="ghost" left-icon="Plus" @click="$emit('create-library')">新建</GlassButton>
    </header>

    <div v-if="libraries.length" class="library-list" aria-label="知识库列表">
      <button
        v-for="library in libraries"
        :key="library.id"
        class="library-item"
        :class="{ active: library.id === selectedLibraryId }"
        type="button"
        @click="$emit('select-library', library.id)"
      >
        <span>{{ library.name }}</span>
        <el-tag size="small" effect="plain">{{ roleLabel(library.role) }}</el-tag>
      </button>
    </div>
    <el-empty v-else description="还没有可访问的知识库" :image-size="72" />

    <div v-if="selectedLibraryId" class="tree-section">
      <div class="tree-heading">
        <span>目录</span>
        <div v-if="canWrite" class="tree-actions">
          <el-tooltip content="新建目录"><button type="button" @click="$emit('create-node', 'folder')"><el-icon><FolderAdd /></el-icon></button></el-tooltip>
          <el-tooltip content="新建文档"><button type="button" @click="$emit('create-node', 'document')"><el-icon><DocumentAdd /></el-icon></button></el-tooltip>
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
            <span>{{ data.title }}</span>
            <span v-if="data.node_type === 'document'" class="status-dot" :class="data.status" :title="data.status" />
          </span>
        </template>
      </el-tree>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  libraries: { type: Array, default: () => [] },
  selectedLibraryId: { type: Number, default: null },
  tree: { type: Array, default: () => [] },
  canWrite: Boolean,
  canCreateLibrary: Boolean,
})

defineEmits(['select-library', 'select-document', 'create-library', 'create-node'])

const labels = { viewer: '只读', editor: '编辑', reviewer: '审核', admin: '管理' }
const roleLabel = role => labels[role] || role
</script>

<style scoped>
.knowledge-sidebar { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid var(--border-color); background: var(--surface-card, #fff); }
.sidebar-header { display: flex; align-items: center; justify-content: space-between; padding: 20px; border-bottom: 1px solid var(--border-color); }
.sidebar-header h2 { margin: 4px 0 0; color: var(--text-primary); font-size: 18px; }
.eyebrow { color: var(--color-primary); font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.library-list { display: grid; gap: 6px; padding: 12px; }
.library-item { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 10px 12px; border: 1px solid transparent; border-radius: var(--radius-md, 8px); color: var(--text-secondary); background: transparent; cursor: pointer; text-align: left; }
.library-item.active { border-color: var(--color-primary); color: var(--text-primary); background: var(--color-primary-light); }
.tree-section { display: flex; flex: 1; min-height: 0; flex-direction: column; padding: 8px 12px 16px; }
.tree-heading { display: flex; align-items: center; justify-content: space-between; padding: 10px 8px; color: var(--text-muted-blue); font-size: 12px; font-weight: 700; letter-spacing: .06em; }
.tree-actions { display: flex; gap: 4px; }
.tree-actions button { display: grid; width: 28px; height: 28px; place-items: center; border: 0; border-radius: 6px; color: var(--text-secondary); background: transparent; cursor: pointer; }
.tree-actions button:focus-visible, .library-item:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.tree-node { display: flex; align-items: center; gap: 7px; min-width: 0; }
.status-dot { width: 6px; height: 6px; margin-left: auto; border-radius: 50%; background: var(--text-muted); }
.status-dot.pending { background: var(--color-primary); }
.status-dot.published { background: var(--color-success); }
@media (hover: hover) and (pointer: fine) { .library-item:hover, .tree-actions button:hover { background: var(--color-primary-light); } }
</style>
