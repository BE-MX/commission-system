<template>
  <div class="sku-picker">
    <el-select
      :model-value="modelValue"
      filterable
      remote
      clearable
      :remote-method="search"
      :loading="resource.loading.value"
      :disabled="disabled"
      :placeholder="placeholder"
      @update:model-value="choose"
      @visible-change="open"
    >
      <el-option v-for="sku in options" :key="sku.id" :value="sku.id" :label="sku.label" />
      <template #footer>
        <GlassButton
          v-if="resource.hasMore.value"
          variant="link"
          left-icon="MoreFilled"
          :loading="resource.loading.value"
          @click="resource.load({ keyword })"
        >
          加载更多产品
        </GlassButton>
        <span v-else>已加载全部匹配产品</span>
      </template>
    </el-select>
    <ListPageStatus
      :error="resource.errorMessage.value"
      :loading="false"
      :has-data="resource.hasData.value"
      @retry="resource.load({ keyword })"
    />
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { getProducts } from '@/api/catalog'
import { useCursorResource } from '@/composables/useCursorResource'
const props = defineProps({ modelValue: Number, disabled: Boolean, activeOnly: { type: Boolean, default: true }, placeholder: { type: String, default: '搜索产品名称 / 产品编码，选择 SKU' }, selectedLabel: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue', 'select'])
const keyword = ref(''), selected = ref(null)
const resource = useCursorResource(async (scope, cursor, { signal }) => {
  const data = (await getProducts({ keyword: scope.keyword, active: props.activeOnly ? true : undefined, page: cursor, page_size: 100 }, { signal, suppressToast: true, showLoading: false })).data
  return { items: data.items, nextCursor: cursor + 1, hasMore: cursor * 100 < data.total }
}, { initialCursor: 1 })
const options = computed(() => {
  const entries = resource.items.value.flatMap(p => p.skus.filter(s => !props.activeOnly || s.active).map(s => ({ id: s.id, label: `${p.display_name} · ${s.code} · ${[s.color, s.size, s.curl].filter(Boolean).join(' / ')}${!p.active || !s.active ? '（停用）' : ''}` })))
  const kept = selected.value?.id === props.modelValue ? selected.value : props.modelValue && props.selectedLabel ? { id: props.modelValue, label: props.selectedLabel } : null
  if (kept && !entries.some(s => s.id === kept.id)) entries.unshift(kept)
  return entries
})
watch(() => props.modelValue, id => { selected.value = options.value.find(s => s.id === id) || null })
function choose(id) { selected.value = options.value.find(s => s.id === id) || null; emit('update:modelValue', id || null); emit('select', selected.value) }
function search(value) { keyword.value = value; resource.clear(); resource.load({ keyword: value }) }
function open(visible) { if (visible && !resource.hasLoaded.value) search(keyword.value) }
</script>
<style scoped>.sku-picker { min-width: 220px; width: 100%; } .sku-picker .el-select { width: 100%; }</style>
