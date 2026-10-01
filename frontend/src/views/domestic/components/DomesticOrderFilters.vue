<template>
  <FilterBar label="内销订单筛选" :loading="loading" :pending="pending" :advanced-count="advancedTags.length" @search="$emit('search')" @reset="resetFilters">
    <el-input v-model="form.keyword" placeholder="系统单号 / 客户订单号" aria-label="订单编号" clearable class="filter-w-md" />
    <el-input v-model="form.customer_name" placeholder="客户店名，支持模糊查询" aria-label="客户店名" maxlength="200" clearable class="filter-w-md" />
    <el-select v-model="form.owner_user_id" placeholder="全部销售" aria-label="归属销售" filterable clearable class="filter-w-sm">
      <el-option v-for="item in options.owners || []" :key="item.value" :label="item.label" :value="item.value" />
    </el-select>
    <el-select v-model="form.status" placeholder="全部状态" aria-label="订单状态" clearable class="filter-w-sm">
      <el-option v-for="s in ORDER_STATUS" :key="s.value" :label="s.label" :value="s.value" />
    </el-select>
    <template #advanced>
      <el-date-picker v-model="form.dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="下单开始日期" end-placeholder="结束日期" range-separator="至" class="filter-w-lg" />
      <template v-if="form.order_kind !== 'production'">
        <el-select v-for="field in BUSINESS_FILTERS" :key="field.key" v-model="form[field.key]" :placeholder="`全部${field.label.slice(2)}`" :aria-label="field.label" clearable filterable class="filter-w-sm">
          <el-option v-for="option in options[field.options] || []" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </template>
    </template>
    <template v-if="advancedTags.length" #summary>
      <div class="order-active-filters" aria-label="当前查询的高级条件">
        <span class="order-filter-caption">当前查询</span>
        <StatusBadge v-for="tag in advancedTags" :key="tag.key" closable effect="plain" @close="removeAdvanced(tag.key)">{{ tag.label }}</StatusBadge>
      </div>
    </template>
  </FilterBar>
</template>

<script setup>
import FilterBar from '@/components/FilterBar.vue'
import { ORDER_STATUS } from '@/api/domestic'
import { BUSINESS_FILTERS, useDomesticOrderFilters } from '../composables/useDomesticOrderFilters'

const props = defineProps({
  form: { type: Object, required: true },
  appliedForm: { type: Object, required: true },
  options: { type: Object, required: true },
  loading: Boolean,
  pending: Boolean,
})
const emit = defineEmits(['search'])
const { advancedTags, removeAdvanced, resetFilters } = useDomesticOrderFilters(
  props.form, () => props.options, () => emit('search'), () => props.appliedForm,
)
defineExpose({ resetFilters })
</script>

<style scoped>
.order-active-filters { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.order-filter-caption { font-size: 12px; color: var(--text-secondary); }
</style>
