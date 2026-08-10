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
      <div
        v-for="library in libraries"
        :key="library.id"
        class="library-row"
        :class="{ active: library.id === selectedLibraryId }"
      >
        <button class="library-item" type="button" @click="$emit('select-library', library.id)">
          <span>{{ library.name }}</span>
          <el-tag size="small" effect="plain">{{ roleLabel(library.role) }}</el-tag>
        </button>
        <el-tooltip v-if="canDeleteLibrary && library.role === 'admin'" content="删除知识库">
          <button class="row-delete" type="button" :aria-label="`删除知识库 ${library.name}`" @click.stop="$emit('delete-library', library)">
            <el-icon><Delete /></el-icon>
          </button>
        </el-tooltip>
      </div>
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
            <el-tooltip v-if="canDeleteNode" :content="data.node_type === 'folder' ? '删除目录' : '删除文档'">
              <button class="row-delete" type="button" :aria-label="`删除${data.node_type === 'folder' ? '目录' : '文档'} ${data.title}`" @click.stop="$emit('delete-node', data)">
                <el-icon><Delete /></el-icon>
              </button>
            </el-tooltip>
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
  canDeleteLibrary: Boolean,
  canDeleteNode: Boolean,
})

defineEmits(['select-library', 'select-document', 'create-library', 'create-node', 'delete-library', 'delete-node'])

const labels = { viewer: '只读', editor: '编辑', reviewer: '审核', admin: '管理' }
const roleLabel = role => labels[role] || role
</script>

<style scoped>
.knowledge-sidebar { display: flex; min-height: 0; overflow-y: auto; flex-direction: column; border-right: 1px solid var(--border-color); background: var(--surface-card, #fff); }
.sidebar-header { display: flex; align-items: center; justify-content: space-between; padding: 20px; border-bottom: 1px solid var(--border-color); }
.sidebar-header h2 { margin: 4px 0 0; color: var(--text-primary); font-size: 18px; }
.eyebrow { color: var(--color-primary); font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.library-list { display: grid; gap: 6px; padding: 12px; }
.library-row { display: flex; align-items: center; gap: 4px; border: 1px solid transparent; border-radius: var(--radius-md, 8px); }
.library-row.active { border-color: var(--color-primary); background: var(--color-primary-light); }
.library-item { display: flex; min-width: 0; flex: 1; align-items: center; justify-content: space-between; padding: 10px 12px; border: 0; border-radius: inherit; color: var(--text-secondary); background: transparent; cursor: pointer; text-align: left; }
.library-row.active .library-item { color: var(--text-primary); }
.tree-section { display: flex; flex: 1; min-height: 0; flex-direction: column; padding: 8px 12px 16px; }
.tree-heading { display: flex; align-items: center; justify-content: space-between; padding: 10px 8px; color: var(--text-muted-blue); font-size: 12px; font-weight: 700; letter-spacing: .06em; }
.tree-actions { display: flex; gap: 4px; }
.tree-actions button { display: grid; width: 28px; height: 28px; place-items: center; border: 0; border-radius: 6px; color: var(--text-secondary); background: transparent; cursor: pointer; }
.tree-actions button:focus-visible, .library-item:focus-visible, .row-delete:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.tree-node { display: flex; width: 100%; min-width: 0; align-items: center; gap: 7px; }
.tree-node > span:nth-child(2) { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-delete { display: grid; width: 28px; height: 28px; flex: 0 0 auto; place-items: center; border: 0; border-radius: 6px; color: var(--color-danger); background: transparent; cursor: pointer; }
.status-dot { width: 6px; height: 6px; margin-left: auto; border-radius: 50%; background: var(--text-muted); }
.status-dot.pending { background: var(--color-primary); }
.status-dot.published { background: var(--color-success); }
@media (hover: hover) and (pointer: fine) {
  .row-delete { opacity: 0; }
  .library-row:hover .row-delete, .tree-node:hover .row-delete, .row-delete:focus-visible { opacity: 1; }
  .library-item:hover, .tree-actions button:hover { background: var(--color-primary-light); }
  .row-delete:hover { background: var(--color-danger-bg); }
}
</style>
