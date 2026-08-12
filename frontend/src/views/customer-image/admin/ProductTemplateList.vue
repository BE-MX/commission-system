<template>
  <div class="product-list">
    <div class="list-toolbar">
      <div>
        <strong>产品模板</strong>
        <span>只有已发布且素材完整的产品会出现在客户邀请中。</span>
      </div>
      <GlassButton
        v-if="canAdmin"
        v-permission="'customer_image:admin'"
        variant="primary"
        left-icon="Plus"
        @click="openEditor()"
      >新建产品</GlassButton>
    </div>

    <el-table v-loading="loading" :data="products" empty-text="暂无可查看的产品模板" border class="list-table">
      <el-table-column label="封面" min-width="86">
        <template #default="{ row }">
          <img v-if="productCoverUrls[row.id]" :src="productCoverUrls[row.id]" :alt="row.name" class="product-cover">
          <span v-else class="cover-empty">暂无</span>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="产品" min-width="180" show-overflow-tooltip />
      <el-table-column prop="category" label="分类" min-width="120" show-overflow-tooltip />
      <el-table-column label="参数" min-width="84">
        <template #default="{ row }">{{ row.options?.length || 0 }} 项</template>
      </el-table-column>
      <el-table-column label="配置版本" min-width="100">
        <template #default="{ row }">v{{ row.config_version }}</template>
      </el-table-column>
      <el-table-column label="状态" min-width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_published ? 'success' : 'info'" effect="plain">
            {{ row.is_published ? '已发布' : '草稿' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="canAdmin" label="操作" min-width="250" fixed="right">
        <template #default="{ row }">
          <GlassButton v-permission="'customer_image:admin'" variant="link" @click="openEditor(row)">编辑</GlassButton>
          <GlassButton
            v-permission="'customer_image:admin'"
            variant="link"
            :link-tone="row.is_published ? '' : 'success'"
            @click="togglePublish(row)"
          >{{ row.is_published ? '取消发布' : '发布' }}</GlassButton>
          <GlassButton
            v-permission="'customer_image:admin'"
            variant="link"
            link-tone="danger"
            @click="remove(row)"
          >删除</GlassButton>
        </template>
      </el-table-column>
    </el-table>

    <ProductTemplateEditor
      v-if="canAdmin"
      v-model="editorVisible"
      :product="editingProduct"
      :admin-state="state"
      @saved="handleSaved"
    />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listProductAssets } from '@/api/customerImage'
import ProductTemplateEditor from './ProductTemplateEditor.vue'
import { validateProductForPublish } from './composables/useCustomerImageAdmin'

const props = defineProps({
  state: { type: Object, required: true },
  canAdmin: { type: Boolean, default: false },
})

const { productCoverUrls, products } = props.state
const loading = ref(false)
const editorVisible = ref(false)
const editingProduct = ref(null)

async function load() {
  loading.value = true
  try { await props.state.loadProducts() } finally { loading.value = false }
}

function openEditor(product = null) {
  editingProduct.value = product
  editorVisible.value = true
}

function handleSaved(saved) { editingProduct.value = saved }

async function togglePublish(product) {
  if (!product.is_published) {
    const response = await listProductAssets(product.id)
    const error = validateProductForPublish(product, response.data || [])
    if (error) {
      ElMessage.warning(error)
      return
    }
  }
  try {
    await props.state.setProductPublished(product.id, !product.is_published)
    ElMessage.success(product.is_published ? '已取消发布' : '产品已发布')
  } catch { /* shared interceptor provides request feedback */ }
}

async function remove(product) {
  try {
    await ElMessageBox.confirm(`删除产品“${product.name}”？`, '删除产品', { type: 'warning' })
  } catch { return }
  try {
    await props.state.removeProduct(product.id)
    ElMessage.success('产品已删除')
  } catch { /* shared interceptor provides request feedback */ }
}

onMounted(load)
</script>

<style scoped>
.product-list { min-width: 0; }
.list-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 64px; }
.list-toolbar div { display: grid; gap: 3px; }
.list-toolbar span { color: var(--el-text-color-secondary); font-size: 13px; }
.product-cover { display: block; width: 54px; height: 54px; border-radius: 9px; object-fit: cover; }
.cover-empty { color: var(--el-text-color-placeholder); font-size: 12px; }
:deep(.glass-button:not(.glass-button--link)) { min-height: 44px; }
@media (max-width: 720px) { .list-toolbar { align-items: flex-start; flex-direction: column; padding-block: 12px; } }
</style>
