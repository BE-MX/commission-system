<template>
  <div class="native-order-picker">
    <el-select :model-value="modelValue" filterable remote clearable :remote-method="search"
      :disabled="disabled" :loading="resource.loading.value" placeholder="搜索本地订单号 / 客户名称"
      @visible-change="onOpen" @update:model-value="choose">
      <el-option v-for="row in options" :key="row.id" :value="row.id" :label="`${row.invoice_no} · ${row.customer_name} · ${row.currency}`" />
      <template #footer><GlassButton v-if="resource.hasMore.value" variant="link" left-icon="MoreFilled" :loading="resource.loading.value" @click="resource.load(scope())">加载更多订单</GlassButton><span v-else>已加载全部匹配订单</span></template>
    </el-select>
    <ListPageStatus :error="resource.errorMessage.value" :has-data="resource.hasData.value" :paged="false" @retry="resource.load(scope())" />
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { getFinanceOrderOptions } from '@/api/nativeFinance'
import { useCursorResource } from '@/composables/useCursorResource'
const props = defineProps({ modelValue: Number, customerId: Number, currency: String, disabled: Boolean, initialOption: Object })
const emit = defineEmits(['update:modelValue', 'select'])
const keyword = ref(''), selected = ref(null)
const scope = () => ({ keyword: keyword.value, customer_id: props.customerId || undefined, currency: props.currency || undefined })
const resource = useCursorResource(async (params, page, { signal }) => {
  const { data } = await getFinanceOrderOptions({ ...params, page, page_size: 20 }, { signal, suppressToast: true, showLoading: false })
  return { items: data.items, nextCursor: page + 1, hasMore: page * 20 < data.total }
}, { initialCursor: 1 })
const options = computed(() => {
  const rows = [...resource.items.value]
  const kept = selected.value?.id === props.modelValue ? selected.value : props.initialOption?.id === props.modelValue ? props.initialOption : null
  if (kept && !rows.some(row => row.id === kept.id)) rows.unshift(kept)
  return rows
})
function choose(id) { selected.value = options.value.find(row => row.id === id) || null; emit('update:modelValue', id || null); emit('select', selected.value) }
function search(value) { keyword.value = value; resource.clear(); resource.load(scope()) }
function onOpen(visible) { if (visible && !resource.hasLoaded.value) search(keyword.value) }
watch(() => [props.customerId, props.currency], () => { resource.clear(); selected.value = null; emit('update:modelValue', null); emit('select', null) })
</script>
<style scoped>.native-order-picker, .native-order-picker .el-select { width: 100%; min-width: 0; }</style>
