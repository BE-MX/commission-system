<template>
  <el-select
    ref="selectRef"
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
    popper-class="production-product-select"
    @visible-change="closeMenu"
  >
    <el-option
      v-for="option in options"
      :key="option.product_id_text"
      :value="option"
      :label="productLabel(option)"
    >
      <div class="option">
        <span class="option-main">
          <strong>{{ nameOf(option).color || option.name }}</strong>
          <span v-if="nameOf(option).length">{{ nameOf(option).length }} 寸</span>
          <span v-if="nameOf(option).weight">{{ nameOf(option).weight }}</span>
        </span>
        <span class="option-sub">{{ [nameOf(option).color ? nameOf(option).series : '', option.model, option.product_no].filter(Boolean).join(' · ') }}</span>
      </div>
    </el-option>
  </el-select>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { getProducts } from '@/api/production'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { parseProductName } from '@/utils/productName'

const selected = defineModel({ type: Object, default: null })
const props = defineProps({ ariaLabel: String, placeholder: String, autofocus: Boolean })
const selectRef = ref(null)

onMounted(() => {
  if (props.autofocus) nextTick(() => selectRef.value?.focus())
})

const products = useAsyncResource(async (keyword, { signal }) => {
  const response = await getProducts({ keyword, page_size: 30 }, { signal, showLoading: false, suppressToast: true })
  return response.data.items
}, { initialData: [] })

const options = computed(() => {
  const list = products.data.value
  if (!selected.value || list.some(option => option.product_id_text === selected.value.product_id_text)) return list
  return [selected.value, ...list]
})

const parsedNames = computed(() => new Map(options.value.map(option => [option.product_id_text, parseProductName(option.name)])))

function nameOf(option) {
  return parsedNames.value.get(option.product_id_text) || parseProductName(option.name)
}

function productLabel(product) {
  const parts = [product.model, product.name, product.product_no].filter(Boolean)
  return [...new Set(parts)].join(' · ')
}

// 展开时 el-select 会自行以空关键词调用 remote-method，这里不再重复搜索；
// 也不清空旧结果，否则下拉会因「无数据」收起再展开，循环触发搜索。
function search(keyword) {
  products.load(keyword.trim())
}

function closeMenu(visible) {
  if (!visible) products.cancel()
}
</script>

<style scoped>
.el-select { width: 100%; }
.option { display: grid; gap: 2px; padding: 6px 0; line-height: 1.35; }
.option-main { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; color: var(--text-primary); }
.option-main strong { font-size: 14px; font-weight: 600; }
.option-main span { color: var(--text-secondary); font-size: 12px; }
.option-sub { overflow: hidden; color: var(--text-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
</style>

<style>
.production-product-select .el-select-dropdown__item { height: auto; }
</style>
