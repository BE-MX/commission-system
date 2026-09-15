<template>
  <div class="order-search">
    <div class="order-search-heading">
      <span class="order-search-title">订单查询</span>
      <div class="order-create-actions">
        <GlassButton v-permission="'domestic:write'" variant="primary" left-icon="Plus" @click="$emit('create', 'business')">业务下单</GlassButton>
        <GlassButton v-permission="'domestic:write'" variant="secondary" left-icon="Plus" @click="$emit('create', 'production')">生产下单</GlassButton>
      </div>
    </div>
    <el-form class="order-search-form" label-position="top" @submit.prevent="$emit('search')">
      <el-form-item label="订单号">
        <el-input v-model="form.keyword" placeholder="系统单号 / 客户订单号" clearable @clear="$emit('search')" />
      </el-form-item>
      <el-form-item label="客户名称">
        <el-input v-model="form.customer_name" placeholder="输入客户店名，支持模糊查询" maxlength="200" clearable @clear="$emit('search')" />
      </el-form-item>
      <el-form-item label="订单状态">
        <el-select v-model="form.status" placeholder="全部状态" clearable @change="$emit('search')">
          <el-option v-for="s in ORDER_STATUS" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <div class="order-search-actions">
        <GlassButton native-type="submit" variant="primary" left-icon="Search" :loading="loading">查询</GlassButton>
        <GlassButton variant="secondary" left-icon="Filter" @click="openAdvanced">高级查询{{ advancedTags.length ? `（${advancedTags.length}）` : '' }}</GlassButton>
        <GlassButton variant="ghost" @click="resetFilters">重置</GlassButton>
      </div>
    </el-form>
    <div v-if="advancedTags.length" class="order-active-filters" aria-label="已应用的高级查询条件">
      <span class="order-filter-caption">已选条件</span>
      <el-tag v-for="tag in advancedTags" :key="tag.key" closable effect="plain" @close="removeAdvanced(tag.key)">{{ tag.label }}</el-tag>
    </div>

    <el-dialog v-model="advancedVisible" title="高级查询" width="640px" append-to-body class="order-filter-dialog">
      <p class="order-filter-description">条件可组合使用，点击“应用查询”后生效。</p>
      <el-form label-position="top" @submit.prevent="applyAdvanced">
        <el-form-item label="下单日期">
          <el-date-picker v-model="draft.dateRange" type="daterange" value-format="YYYY-MM-DD"
            start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" style="width: 100%" />
        </el-form-item>
        <div v-if="form.order_kind !== 'production'" class="order-advanced-grid">
          <el-form-item v-for="field in BUSINESS_FILTERS" :key="field.key" :label="field.label">
            <el-select v-model="draft[field.key]" :placeholder="`全部${field.label.slice(2)}`" clearable filterable>
              <el-option v-for="option in options[field.options] || []" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <div class="order-filter-footer">
          <GlassButton variant="ghost" @click="clearDraft">清空高级条件</GlassButton>
          <div>
            <GlassButton variant="ghost" @click="advancedVisible = false">取消</GlassButton>
            <GlassButton variant="primary" left-icon="Search" @click="applyAdvanced">应用查询</GlassButton>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import GlassButton from '@/components/GlassButton.vue'
import { ORDER_STATUS } from '@/api/domestic'
import { BUSINESS_FILTERS, useDomesticOrderFilters } from '../composables/useDomesticOrderFilters'

const props = defineProps({
  form: { type: Object, required: true },
  options: { type: Object, required: true },
  loading: Boolean,
})
const emit = defineEmits(['search', 'create'])
const { advancedVisible, draft, advancedTags, openAdvanced, clearDraft, applyAdvanced, removeAdvanced, resetFilters } =
  useDomesticOrderFilters(props.form, () => props.options, () => emit('search'))
</script>

<style scoped>
.order-search { position: relative; z-index: 1; padding: 14px 16px; margin-bottom: 12px; border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight); }
.order-search-heading, .order-create-actions, .order-search-actions, .order-filter-footer { display: flex; align-items: center; gap: 8px; }
.order-search-heading { justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.order-search-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.order-search-form { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr) 140px auto; align-items: end; gap: 12px; }
.order-search-form :deep(.el-form-item) { margin-bottom: 0; min-width: 0; }
.order-search-form :deep(.el-form-item__label) { margin-bottom: 6px; line-height: 20px; }
.order-search-form :deep(.el-input__wrapper), .order-search-form :deep(.el-select__wrapper) { height: 36px; min-height: 36px; box-sizing: border-box; }
.order-search-actions { min-height: 36px; flex-wrap: wrap; }
.order-active-filters { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-color); }
.order-filter-caption, .order-filter-description { font-size: 12px; color: var(--text-secondary); }
.order-active-filters :deep(.el-tag) { max-width: 100%; height: auto; min-height: 24px; white-space: normal; }
.order-active-filters :deep(.el-tag__content) { overflow-wrap: anywhere; }
.order-filter-description { margin: 0 0 16px; }
.order-advanced-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.order-filter-dialog :deep(.el-select) { width: 100%; }
.order-filter-footer { justify-content: space-between; flex-wrap: wrap; }
.order-filter-footer > div { display: flex; gap: 8px; }
@media (max-width: 1100px) {
  .order-search-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 600px) {
  .order-search-form, .order-advanced-grid { grid-template-columns: minmax(0, 1fr); }
  .order-search-heading { align-items: flex-start; flex-direction: column; }
  .order-create-actions { flex-wrap: wrap; }
}
</style>
