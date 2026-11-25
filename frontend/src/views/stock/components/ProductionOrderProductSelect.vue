<template>
  <el-select
    v-model="selected"
    filterable
    remote
    clearable
    :reserve-keyword="false"
    :remote-method="search"
    :loading="products.loading.value"
    :placeholder="placeholder"
    :aria-label="ariaLabel"
    :no-data-text="products.error.value ? products.errorMessage.value : '未找到可用产品'"
    value-key="product_id_text"
    @visible-change="open"
  >
    <el-option
      v-for="option in options"
      :key="option.product_id_text"
      :value="option"
      :label="productLabel(option)"
    />
  </el-select>
</template>

<script setup>
import { computed } from 'vue'
import { getProducts } from '@/api/production'
import { useAsyncResource } from '@/composables/useAsyncResource'

const selected = defineModel({ type: Object, default: null })
defineProps({ ariaLabel: String, placeholder: String })

const products = useAsyncResource(async (keyword, { signal }) => {
  const response = await getProducts({ keyword, page_size: 30 }, { signal, showLoading: false, suppressToast: true })
  return response.data.items
}, { initialData: [] })

const options = computed(() => {
  const list = products.data.value
  if (!selected.value || list.some(option => option.product_id_text === selected.value.product_id_text)) return list
  return [selected.value, ...list]
})

function productLabel(product) {
  const parts = [product.model, product.name, product.product_no].filter(Boolean)
  return [...new Set(parts)].join(' · ')
}

function search(keyword) {
  products.load(keyword.trim(), { clear: true })
}

function open(visible) {
  if (visible) search('')
  else products.cancel()
}
</script>

<style scoped>
.el-select { width: 100%; }
</style>
