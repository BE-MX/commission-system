<script setup>
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { useListPage } from '@/composables/useListPage'
import { portalAdminApi } from '@/api/portal'
const props = defineProps({ modelValue: { type: Array, required: true }, disabled: Boolean, title: { type: String, default: '初始商品授权' } })
const emit = defineEmits(['update:modelValue', 'denied'])
const error = ref(''), errorSummary = ref(null)
let controller, sequence = 0, disposed = false, errorSequence = 0
async function showError(value) {
  const current = ++errorSequence
  error.value = value
  await nextTick()
  if (!disposed && current === errorSequence && error.value === value) errorSummary.value?.$el?.focus()
}
const { list, total, page, pageSize, loading, searchForm, fetchList, handleSearch, handlePageChange, handleSizeChange } = useListPage(async params => {
  const current = ++sequence
  controller?.abort(); controller = new AbortController(); list.value = []; total.value = 0; error.value = ''
  try {
    const result = await portalAdminApi.onboardingCatalog(params, controller.signal)
    return !disposed && current === sequence ? result : { items: [], total: 0 }
  } catch (e) { if (!disposed && current === sequence) { if ([401, 403, 404].includes(e?.response?.status)) emit('denied', e.response.status); void showError(e?.response?.data?.message || '商品选项读取失败。') }; return { items: [], total: 0 } }
}, { searchForm: { keyword: '' } })
function selected(id) { return props.modelValue.some(item => item.id === id) }
function toggle(item, checked) {
  if (props.disabled) return
  if (checked && !selected(item.id)) {
    if (props.modelValue.length >= 5000) { void showError('最多选择 5000 个商品规格。'); return }
    emit('update:modelValue', [...props.modelValue, { ...item }])
  } else if (!checked) emit('update:modelValue', props.modelValue.filter(row => row.id !== item.id))
}
onBeforeUnmount(() => { disposed = true; sequence++; errorSequence++; controller?.abort() })
</script>

<template>
  <section class="catalog-picker" :aria-busy="loading || undefined">
    <h3>{{ title }} · 已选 {{ modelValue.length }} 项</h3>
    <p>仅选择已发布的标准规格。客户不会自动获得整个目录，已下架的历史授权只能保留或移除。</p>
    <div class="picker-search"><el-input v-model="searchForm.keyword" :disabled="disabled" aria-label="搜索可授权商品" maxlength="100" placeholder="标准型号或颜色" @keyup.enter="handleSearch" /><GlassButton :disabled="disabled || loading" @click="handleSearch">搜索商品</GlassButton><GlassButton :disabled="disabled || loading" @click="fetchList">刷新商品</GlassButton></div>
    <p v-if="loading" role="status">正在读取可授权商品…</p>
    <el-alert v-if="error" ref="errorSummary" tabindex="-1" :title="error" type="error" :closable="false" />
    <el-table :scrollbar-tabindex="0" v-loading="loading" :data="list" border class="list-table" v-sticky-scrollbar><template #empty><el-empty :image-size="72" description="没有匹配的已发布商品，请先完成站点商品配置" /></template>
      <el-table-column label="授权" min-width="80"><template #default="{ row }"><el-checkbox :model-value="selected(row.id)" :disabled="disabled" :aria-label="`授权 ${row.model_name} ${row.color_name} ${row.id}`" @change="value => toggle(row, value)" /></template></el-table-column>
      <el-table-column prop="model_name" label="标准型号" min-width="150" /><el-table-column prop="color_name" label="标准颜色" min-width="130" />
      <el-table-column label="规格" min-width="200"><template #default="{ row }">长度 {{ row.length || '未标注' }} · 重量 {{ row.weight || '未标注' }} · {{ row.sale_unit }}</template></el-table-column>
    </el-table>
    <el-pagination :disabled="disabled" :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    <details v-if="modelValue.length"><summary>查看已选规格（{{ modelValue.length }}）</summary><div class="selected-items"><el-tag v-for="item in modelValue" :key="item.id"><span class="selected-label">{{ item.model_name }} / {{ item.color_name }} · {{ item.length }} · {{ item.weight }} · {{ item.sale_unit }}{{ item.status && item.status !== 'published' ? ' · 已下架' : '' }}</span><button type="button" class="selected-remove" :disabled="disabled" :aria-label="`移除授权规格 ${item.model_name} ${item.color_name} ${item.id}`" @click="toggle(item, false)"><span aria-hidden="true">×</span></button></el-tag></div></details>
  </section>
</template>

<style scoped>
.picker-search { display: flex; gap: 8px; margin: 12px 0; flex-wrap: wrap; }
.picker-search .el-input { flex: 1; min-width: 160px; }
.el-alert { margin-bottom: 12px; }
.el-alert:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.el-pagination { padding: 12px 0; overflow-x: auto; }
.selected-items { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.el-tag { height: auto; max-width: 100%; white-space: normal; padding: 6px 10px; }
:deep(.selected-items .el-tag__content) { display: flex; align-items: flex-start; gap: 8px; min-width: 0; white-space: normal; overflow-wrap: anywhere; }
.selected-label { min-width: 0; overflow-wrap: anywhere; }
.selected-remove { flex-shrink: 0; padding: 2px 6px; border: 1px solid var(--border-color); border-radius: 4px; background: transparent; color: var(--text-secondary); cursor: pointer; }
.selected-remove:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.selected-remove:disabled { cursor: default; opacity: 0.5; }
:deep(.list-table .cell) { white-space: normal !important; overflow-wrap: anywhere; word-break: normal; }
p { color: var(--text-secondary); }
</style>
