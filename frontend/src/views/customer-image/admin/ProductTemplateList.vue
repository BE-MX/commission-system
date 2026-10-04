<template>
  <div class="product-list">
    <div class="list-toolbar">
      <div>
        <strong>产品模板</strong>
        <span>只有已发布且素材完整的产品会出现在客户邀请中。</span>
      </div>
    </div>

    <section ref="panelRef" class="table-card">
      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton
          v-if="canAdmin"
          v-permission="'customer_image:admin'"
          variant="primary"
          left-icon="Plus"
          @click="openEditor()"
        >新建产品</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="load"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listResource.hasData.value" :paged="false" :error="listResource.errorMessage.value" :loading="loading" :has-data="true" @retry="load()" />
      <el-table v-loading="loading" :data="products" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640">
        <template #empty><ListPageStatus :paged="false" :error="listResource.errorMessage.value" :loading="loading" @retry="load()"><el-empty v-if="listResource.isEmpty.value" :image-size="96" description="暂无数据" /></ListPageStatus></template>
        <el-table-column :sortable="false" v-if="visibleKeys.includes('cover')" label="封面" min-width="86">
          <template #default="{ row }">
            <img v-if="productCoverUrls[row.id]" :src="productCoverUrls[row.id]" :alt="row.name" class="product-cover">
            <GlassButton v-else-if="productCoverErrors[row.id]" variant="link" :loading="productCoverLoading[row.id]" @click="state.retryProductCovers()">封面失败，重试</GlassButton>
            <span v-else class="cover-empty">{{ row.cover ? '加载中…' : '暂无' }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('name')" prop="name" label="产品" min-width="180" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('category')" prop="category" label="分类" min-width="120" show-overflow-tooltip />
        <el-table-column :sort-by="row => row.options?.length || 0" v-if="visibleKeys.includes('options')" label="参数" min-width="84">
          <template #default="{ row }">{{ row.options?.length || 0 }} 项</template>
        </el-table-column>
        <el-table-column prop="config_version" v-if="visibleKeys.includes('config-version')" label="配置版本" min-width="100">
          <template #default="{ row }">v{{ row.config_version }}</template>
        </el-table-column>
        <el-table-column prop="is_published" v-if="visibleKeys.includes('status')" label="状态" min-width="110">
          <template #default="{ row }">
            <StatusBadge :type="row.is_published ? 'success' : 'info'" effect="plain">
              {{ row.is_published ? '已发布' : '草稿' }}
            </StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="canAdmin" class-name="table-action-column" label="操作" min-width="250" fixed="right">
          <template #default="{ row }">
            <GlassButton left-icon="Edit" v-permission="'customer_image:admin'" variant="link" @click="openEditor(row)">编辑</GlassButton>
            <GlassButton left-icon="SwitchButton"
              v-permission="'customer_image:admin'"
              variant="link"
              :link-tone="row.is_published ? 'warning' : 'success'"
              @click="togglePublish(row)"
            >{{ row.is_published ? '取消发布' : '发布' }}</GlassButton>
            <GlassButton left-icon="Delete"
              v-permission="'customer_image:admin'"
              variant="link"
              link-tone="danger"
              @click="remove(row)"
            >删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <ProductTemplateEditor
      v-if="canAdmin"
      v-model="editorVisible"
      :product="editingProduct"
      :admin-state="state"
      @saved="handleSaved"
    />
  </div>
</template>

<script setup>import { msgWarning, msgSuccessText, confirmAction } from '@/utils/feedback'
import { onMounted, ref, watch } from 'vue'

import { listProductAssets } from '@/api/customerImage'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import ProductTemplateEditor from './ProductTemplateEditor.vue'
import { validateProductForPublish } from './composables/useCustomerImageAdmin'

const props = defineProps({
  state: { type: Object, required: true },
  canAdmin: { type: Boolean, default: false },
})

const { productCoverUrls, productCoverErrors, productCoverLoading, products } = props.state
const listResource = props.state.productsResource
const loading = listResource.loading
const editorVisible = ref(false)
const editingProduct = ref(null)

// 列配置数组：TableTools 列显隐的数据源（List Page Spec 第 9 节，操作列不进配置）
const columnDefs = [
  { key: 'cover', label: '封面' },
  { key: 'name', label: '产品' },
  { key: 'category', label: '分类' },
  { key: 'options', label: '参数' },
  { key: 'config-version', label: '配置版本' },
  { key: 'status', label: '状态' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('customer-image-products', columnDefs)

function load() { return props.state.loadProducts() }

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
      msgWarning(error)
      return
    }
  }
  try {
    await props.state.setProductPublished(product.id, !product.is_published)
    msgSuccessText(product.is_published ? '已取消发布' : '产品已发布')
  } catch { /* shared interceptor provides request feedback */ }
}

async function remove(product) {
  try {
    await confirmAction(`删除产品“${product.name}”？`, '删除产品', { type: 'warning' })
  } catch { return }
  try {
    await props.state.removeProduct(product.id)
    msgSuccessText('产品已删除')
  } catch { /* shared interceptor provides request feedback */ }
}

watch(() => props.state.scopeVersion.value, () => { editorVisible.value = false; editingProduct.value = null })
onMounted(load)
</script>

<style scoped>
.product-list { min-width: 0; }
.list-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 64px; }
.list-toolbar div { display: grid; gap: 3px; }
.list-toolbar span { color: var(--el-text-color-secondary); font-size: 13px; }
.product-cover { display: block; width: 54px; height: 54px; border-radius: 9px; object-fit: cover; }
.cover-empty { color: var(--el-text-color-placeholder); font-size: 12px; }
@media (max-width: 720px) { .list-toolbar { align-items: flex-start; flex-direction: column; padding-block: 12px; } }
</style>
