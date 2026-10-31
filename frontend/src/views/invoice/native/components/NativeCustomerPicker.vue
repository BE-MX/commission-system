<template>
  <div class="native-customer-picker">
    <el-select :model-value="modelValue" filterable remote clearable :remote-method="search"
      :loading="resource.loading.value" :disabled="disabled" placeholder="搜索客户名称 / 客户编号"
      @visible-change="onOpen" @update:model-value="choose">
      <el-option v-for="customer in options" :key="customer.id" :value="customer.id"
        :label="`${customer.display_name}${customer.customer_code ? ` · ${customer.customer_code}` : ''}`" />
      <template #footer>
        <GlassButton v-if="resource.hasMore.value" variant="link" left-icon="MoreFilled" :loading="resource.loading.value" @click="resource.load({ keyword })">加载更多客户</GlassButton>
        <span v-else>已加载全部匹配客户</span>
      </template>
    </el-select>
    <ListPageStatus :error="resource.errorMessage.value" :has-data="resource.hasData.value" :paged="false" @retry="resource.load({ keyword })" />
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useCursorResource } from '@/composables/useCursorResource'
import { getInvoiceCustomerOptions } from '@/api/nativeInvoice'
import { getFinanceCustomerOptions } from '@/api/nativeFinance'
const props = defineProps({ modelValue: Number, disabled: Boolean, mode: { type: String, default: 'invoice' }, selectedName: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue', 'select'])
const keyword = ref(''), selected = ref(null)
const resource = useCursorResource(async (scope, page, { signal }) => {
  const response = await (props.mode === 'finance' ? getFinanceCustomerOptions : getInvoiceCustomerOptions)(
    { keyword: scope.keyword, page, page_size: 50 }, { signal, suppressToast: true, showLoading: false })
  return { items: response.data.items, nextCursor: page + 1, hasMore: page * 50 < response.data.total }
}, { initialCursor: 1 })
const options = computed(() => {
  const rows = [...resource.items.value]
  const kept = selected.value?.id === props.modelValue ? selected.value : props.modelValue && props.selectedName ? { id: props.modelValue, display_name: props.selectedName } : null
  if (kept && !rows.some(row => row.id === kept.id)) rows.unshift(kept)
  return rows
})
function choose(id) {
  selected.value = options.value.find(row => row.id === id) || null
  emit('update:modelValue', id || null)
  emit('select', selected.value)
}
function search(value) { keyword.value = value; resource.clear(); resource.load({ keyword: value }) }
function onOpen(visible) { if (visible && !resource.hasLoaded.value) search(keyword.value) }
watch(() => props.mode, () => { resource.clear(); selected.value = null })
</script>
<style scoped>.native-customer-picker, .native-customer-picker .el-select { width: 100%; min-width: 0; }</style>
