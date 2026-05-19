<template>
  <div class="asset-favorites-page">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <h2 class="page-title">
          <el-icon><Collection /></el-icon>
          我的收藏
        </h2>
      </div>
      <div class="toolbar-right">
        <el-button type="primary" @click="showCreateFolder = true">
          <el-icon><FolderAdd /></el-icon>
          新建收藏夹
        </el-button>
      </div>
    </div>

    <div class="favorites-layout">
      <!-- 左侧：收藏夹列表 -->
      <aside class="folder-sidebar">
        <div
          v-for="folder in folders"
          :key="folder.id"
          class="folder-item"
          :class="{ active: currentFolderId === folder.id }"
          @click="selectFolder(folder.id)"
        >
          <el-icon><Folder /></el-icon>
          <span class="folder-name" :title="folder.name">{{ folder.name }}</span>
          <el-dropdown trigger="click" @command="handleFolderCommand($event, folder)">
            <el-icon class="folder-more" @click.stop><MoreFilled /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="rename">重命名</el-dropdown-item>
                <el-dropdown-item command="share">分享</el-dropdown-item>
                <el-dropdown-item v-if="folder.share_token" command="revoke">取消分享</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <el-empty v-if="folders.length === 0" description="暂无收藏夹" />
      </aside>

      <!-- 右侧：素材列表 -->
      <div class="content-area">
        <div v-if="!currentFolderId" class="empty-select">
          <el-empty description="请选择一个收藏夹" />
        </div>
        <div v-else-if="loading" class="loading-wrap">
          <el-skeleton :rows="5" animated />
        </div>
        <div v-else-if="items.length === 0" class="empty-wrap">
          <el-empty description="该收藏夹暂无素材">
            <el-button type="primary" @click="$router.push('/asset/library')">
              去素材库逛逛
            </el-button>
          </el-empty>
        </div>
        <div v-else class="asset-grid">
          <div
            v-for="item in items"
            :key="item.id"
            class="asset-card"
            @click="openPreview(item.asset)"
          >
            <div class="card-thumb">
              <img
                v-if="item.asset?.file_type === 'image' && item.asset?.thumbnail_path"
                :src="getThumbUrl(item.asset.thumbnail_path)"
              />
              <div v-else-if="item.asset?.file_type === 'video'" class="type-icon video">
                <el-icon><VideoPlay /></el-icon>
              </div>
              <div v-else-if="item.asset?.file_type === 'document'" class="type-icon doc">
                <el-icon><Document /></el-icon>
              </div>
              <div v-else class="type-icon">
                <el-icon><Picture /></el-icon>
              </div>
            </div>
            <div class="card-info">
              <div class="card-name" :title="item.asset?.file_name">{{ item.asset?.file_name }}</div>
              <div class="card-meta">
                <span>{{ formatSize(item.asset?.file_size) }}</span>
              </div>
            </div>
            <div class="card-actions" @click.stop>
              <el-tooltip content="取消收藏">
                <el-button circle size="small" type="danger" plain @click="handleRemove(item)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </el-tooltip>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建收藏夹弹窗 -->
    <el-dialog v-model="showCreateFolder" title="新建收藏夹" width="360px">
      <el-input
        v-model="newFolderName"
        placeholder="收藏夹名称"
        maxlength="128"
        show-word-limit
        @keyup.enter="createFolder"
      />
      <template #footer>
        <el-button @click="showCreateFolder = false">取消</el-button>
        <el-button type="primary" :disabled="!newFolderName.trim()" @click="createFolder">
          创建
        </el-button>
      </template>
    </el-dialog>

    <!-- 重命名弹窗 -->
    <el-dialog v-model="showRenameFolder" title="重命名收藏夹" width="360px">
      <el-input
        v-model="renameFolderName"
        placeholder="收藏夹名称"
        maxlength="128"
        show-word-limit
        @keyup.enter="confirmRename"
      />
      <template #footer>
        <el-button @click="showRenameFolder = false">取消</el-button>
        <el-button type="primary" :disabled="!renameFolderName.trim()" @click="confirmRename">
          确认
        </el-button>
      </template>
    </el-dialog>

    <!-- 分享弹窗 -->
    <el-dialog v-model="showShareDialog" title="分享收藏夹" width="480px">
      <div v-if="shareUrl" class="share-content">
        <p>分享链接已生成，有效期 7 天：</p>
        <el-input v-model="shareUrl" readonly class="share-url">
          <template #append>
            <el-button @click="copyShareUrl">复制</el-button>
          </template>
        </el-input>
      </div>
      <template #footer>
        <el-button @click="showShareDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 预览弹窗 -->
    <el-dialog v-model="previewVisible" width="80%" :title="previewAsset?.file_name" destroy-on-close>
      <div class="preview-body">
        <div class="preview-media">
          <img
            v-if="previewAsset?.file_type === 'image'"
            :src="getFileUrl(previewAsset?.storage_path)"
            class="preview-img"
          />
          <video
            v-else-if="previewAsset?.file_type === 'video'"
            :src="getFileUrl(previewAsset?.storage_path)"
            controls
            class="preview-video"
          />
          <div v-else class="preview-doc">
            <el-icon size="64"><Document /></el-icon>
            <p>文档预览暂不支持，请下载后查看</p>
          </div>
        </div>
        <div class="preview-info">
          <h4>文件信息</h4>
          <p><label>文件名:</label> {{ previewAsset?.file_name }}</p>
          <p><label>类型:</label> {{ fileTypeLabel(previewAsset?.file_type) }}</p>
          <p><label>大小:</label> {{ formatSize(previewAsset?.file_size) }}</p>
          <p><label>下载次数:</label> {{ previewAsset?.download_count }}</p>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Collection, FolderAdd, Folder, MoreFilled,
  VideoPlay, Document, Picture, Delete, Share,
} from '@element-plus/icons-vue'
import {
  getFavoriteFolders, createFavoriteFolder, updateFavoriteFolder,
  deleteFavoriteFolder, getFavoriteItems, removeFavoriteItem,
  shareFolder, revokeShare,
} from '@/api/asset'

// ── 收藏夹 ──────────────────────────────────────────────
const folders = ref([])
const currentFolderId = ref(null)
const loading = ref(false)
const items = ref([])

async function loadFolders() {
  try {
    const res = await getFavoriteFolders()
    folders.value = res.data || []
    // 默认选中第一个
    if (folders.value.length > 0 && !currentFolderId.value) {
      selectFolder(folders.value[0].id)
    }
  } catch (e) {
    ElMessage.error('加载收藏夹失败')
  }
}

async function selectFolder(folderId) {
  currentFolderId.value = folderId
  loading.value = true
  try {
    const res = await getFavoriteItems(folderId)
    items.value = res.data || []
  } catch (e) {
    ElMessage.error('加载收藏内容失败')
    items.value = []
  } finally {
    loading.value = false
  }
}

// ── 新建收藏夹 ──────────────────────────────────────────
const showCreateFolder = ref(false)
const newFolderName = ref('')

async function createFolder() {
  const name = newFolderName.value.trim()
  if (!name) return
  try {
    await createFavoriteFolder({ name })
    ElMessage.success('创建成功')
    showCreateFolder.value = false
    newFolderName.value = ''
    await loadFolders()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '创建失败')
  }
}

// ── 重命名 ──────────────────────────────────────────────
const showRenameFolder = ref(false)
const renameFolderName = ref('')
const renamingFolder = ref(null)

function handleFolderCommand(command, folder) {
  if (command === 'rename') {
    renamingFolder.value = folder
    renameFolderName.value = folder.name
    showRenameFolder.value = true
  } else if (command === 'share') {
    handleShare(folder)
  } else if (command === 'revoke') {
    handleRevokeShare(folder)
  } else if (command === 'delete') {
    ElMessageBox.confirm(
      `确定删除收藏夹「${folder.name}」？收藏夹内的素材不会被删除。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    ).then(() => confirmDelete(folder.id))
  }
}

async function confirmRename() {
  const name = renameFolderName.value.trim()
  if (!name || !renamingFolder.value) return
  try {
    await updateFavoriteFolder(renamingFolder.value.id, { name })
    ElMessage.success('重命名成功')
    showRenameFolder.value = false
    renamingFolder.value = null
    renameFolderName.value = ''
    await loadFolders()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '重命名失败')
  }
}

async function confirmDelete(folderId) {
  try {
    await deleteFavoriteFolder(folderId)
    ElMessage.success('删除成功')
    if (currentFolderId.value === folderId) {
      currentFolderId.value = null
      items.value = []
    }
    await loadFolders()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '删除失败')
  }
}

// ── 分享 ────────────────────────────────────────────────
const showShareDialog = ref(false)
const shareUrl = ref('')

async function handleShare(folder) {
  try {
    const res = await shareFolder(folder.id)
    shareUrl.value = res.data?.share_url || ''
    showShareDialog.value = true
    await loadFolders()
  } catch (e) {
    ElMessage.error('生成分享链接失败')
  }
}

async function handleRevokeShare(folder) {
  try {
    await revokeShare(folder.id)
    ElMessage.success('已取消分享')
    await loadFolders()
  } catch (e) {
    ElMessage.error('取消分享失败')
  }
}

function copyShareUrl() {
  navigator.clipboard.writeText(shareUrl.value).then(() => {
    ElMessage.success('链接已复制')
  })
}

// ── 移除收藏 ────────────────────────────────────────────
async function handleRemove(item) {
  try {
    await ElMessageBox.confirm('确定取消收藏该素材？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await removeFavoriteItem(currentFolderId.value, item.id)
    ElMessage.success('已取消收藏')
    items.value = items.value.filter(i => i.id !== item.id)
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('操作失败')
    }
  }
}

// ── 预览 ────────────────────────────────────────────────
const previewVisible = ref(false)
const previewAsset = ref(null)

function openPreview(asset) {
  if (!asset) return
  previewAsset.value = asset
  previewVisible.value = true
}

// ── 工具函数 ────────────────────────────────────────────
function getThumbUrl(path) {
  if (!path) return ''
  return `/uploads/assets/${path}`
}

function getFileUrl(path) {
  if (!path) return ''
  return `/uploads/assets/${path}`
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024
    i++
  }
  return `${bytes.toFixed(1)} ${units[i]}`
}

function fileTypeLabel(type) {
  return { image: '图片', video: '视频', document: '文档' }[type] || type
}

onMounted(() => {
  loadFolders()
})
</script>

<style scoped>
.asset-favorites-page {
  padding: 20px 28px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  font-size: 17px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 布局 */
.favorites-layout {
  display: flex;
  gap: 20px;
  flex: 1;
  overflow: hidden;
}

/* 左侧收藏夹 */
.folder-sidebar {
  width: 240px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 12px;
  padding: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  overflow-y: auto;
}

.folder-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s;
  position: relative;
}

.folder-item:hover {
  background: #f5f5f5;
}

.folder-item.active {
  background: rgba(212, 148, 28, 0.08);
  color: #d4941c;
}

.folder-name {
  flex: 1;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folder-more {
  opacity: 0;
  transition: opacity 0.15s;
  padding: 4px;
  border-radius: 4px;
}

.folder-item:hover .folder-more {
  opacity: 1;
}

.folder-more:hover {
  background: #e8e8e8;
}

/* 右侧内容 */
.content-area {
  flex: 1;
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  overflow-y: auto;
}

.empty-select,
.empty-wrap,
.loading-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

/* 素材网格 */
.asset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
}

.asset-card {
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
  position: relative;
}

.asset-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

.card-thumb {
  aspect-ratio: 1;
  background: #f5f5f5;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  position: relative;
}

.card-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.type-icon {
  color: #ccc;
  font-size: 28px;
}

.type-icon.video {
  color: #e74c3c;
}

.type-icon.doc {
  color: #3498db;
}

.card-info {
  padding: 10px 12px;
}

.card-name {
  font-size: 13px;
  font-weight: 500;
  color: #1a1a2e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.card-meta {
  font-size: 11px;
  color: #999;
}

.card-actions {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 6px;
  opacity: 0;
  transition: opacity 0.15s;
}

.asset-card:hover .card-actions {
  opacity: 1;
}

/* 预览弹窗 */
.preview-body {
  display: flex;
  gap: 20px;
  min-height: 400px;
}

.preview-media {
  flex: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8f8f8;
  border-radius: 8px;
  overflow: hidden;
}

.preview-img {
  max-width: 100%;
  max-height: 500px;
  object-fit: contain;
}

.preview-video {
  max-width: 100%;
  max-height: 500px;
}

.preview-doc {
  text-align: center;
  color: #999;
}

.preview-info {
  flex: 1;
  min-width: 240px;
}

.preview-info h4 {
  margin: 0 0 12px;
  font-size: 15px;
}

.preview-info p {
  margin: 8px 0;
  font-size: 13px;
  color: #666;
}

.preview-info label {
  color: #999;
  display: inline-block;
  width: 70px;
}

/* 分享 */
.share-content p {
  margin-bottom: 12px;
  color: #666;
  font-size: 14px;
}

.share-url {
  margin-top: 8px;
}

.share-url :deep(.el-input__wrapper) {
  background: #f5f5f5;
}
</style>
