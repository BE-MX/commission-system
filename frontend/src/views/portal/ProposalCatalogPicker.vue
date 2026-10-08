<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { useListPage } from '@/composables/useListPage'
import { portalAdminApi } from '@/api/portal'
const props = defineProps({ requestId: { type: String, required: true }, version: { type: Number, required: true }, selected: { type: Array, required: true }, disabled: Boolean })
const emit = defineEmits(['add', 'denied']), error = ref('')
let sequence = 0, controller, disposed = false
const { list, total, page, pageSize, loading, searchForm, fetchList, handleSearch, handlePageChange, handleSizeChange } = useListPage(async params => {
  const current = ++sequence
  controller?.abort(); controller = new AbortController(); list.value = []; total.value = 0; error.value = ''
  try {
    const result = await portalAdminApi.proposalCatalog(props.requestId, params, controller.signal)
    if (disposed || current !== sequence) return { items: [], total: 0 }
    if (result.request_id !== props.requestId || result.row_version !== props.version) throw new Error('请求版本已变化，请刷新处理窗口后重新选品。')
    return result
  } catch (e) {
    if (!disposed && current === sequence) {
      error.value = e?.response?.data?.message || e.message || '商品目录读取失败。'
      if ([401, 403, 404].includes(e?.response?.status)) emit('denied')
    }
    return { items: [], total: 0 }
  }
}, { searchForm: { keyword: '' } })
function isSelected(id) { return props.selected.some(line => line.item_id === id) }
function add(row) { if (!props.disabled && !isSelected(row.item_id) && props.selected.length < 100) emit('add', row) }
onBeforeUnmount(() => { disposed = true; sequence++; controller?.abort() })
</script>

<template>
  <section class="proposal-catalog-picker">
    <p>仅显示该客户当前获准购买的商品。选择后可调整数量，价格和库存以完整提案预览及发送时核验为准。</p>
    <div class="picker-search"><el-input v-model="searchForm.keyword" :disabled="disabled" aria-label="搜索客户授权商品" maxlength="100" placeholder="客户型号、颜色、货号或标准 SKU" @keyup.enter="handleSearch" /><GlassButton :disabled="disabled || loading" @click="handleSearch">搜索授权商品</GlassButton><GlassButton :disabled="disabled || loading" @click="fetchList">刷新目录</GlassButton></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <p v-if="loading" role="status">正在读取客户授权商品…</p>
    <el-table :aria-busy="loading || undefined" v-loading="loading" :data="list" border class="list-table" v-sticky-scrollbar><template #empty><el-empty :image-size="72" description="该客户没有匹配的可选商品" /></template>
      <el-table-column label="客户型号 / 颜色" min-width="190"><template #default="{ row }">{{ row.display_snapshot.model_name }} / {{ row.display_snapshot.color_name }}<br>{{ row.display_snapshot.customer_sku || '未设客户货号' }}</template></el-table-column>
      <el-table-column label="标准规格" min-width="200"><template #default="{ row }">{{ row.standard.model }} / {{ row.standard.color }} · {{ row.display_snapshot.length }} · {{ row.display_snapshot.weight }}<br>SKU {{ row.sku_id }} · 起订 {{ row.min_order_qty }} · 步长 {{ row.step_qty }} {{ row.sale_unit }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" min-width="95" class-name="table-action-column"><template #default="{ row }"><GlassButton variant="link" :disabled="disabled || isSelected(row.item_id) || selected.length >= 100" :aria-label="`添加商品 ${row.display_snapshot.model_name} ${row.display_snapshot.color_name}`" @click="add(row)">{{ isSelected(row.item_id) ? '已添加' : '添加' }}</GlassButton></template></el-table-column>
    </el-table>
    <el-pagination :disabled="disabled" :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
  </section>
</template>

<style scoped>
.picker-search { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
.picker-search .el-input { flex: 1; min-width: 160px; }
.el-pagination { padding: 12px 0; overflow-x: auto; }
.el-alert { margin: 12px 0; }
p { color: var(--text-secondary); line-height: 1.6; }
</style>
