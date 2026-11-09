<template>
  <FilterBar label="客户总览筛选" :loading="loading" :pending="pending" @search="$emit('search')" @reset="$emit('reset')">
    <el-input v-model="form.keyword" aria-label="客户关键词" placeholder="店名 / 编码 / 联系人 / 电话 / 微信"
              clearable maxlength="100" prefix-icon="Search" class="filter-w-lg" />
    <el-select v-model="form.province" aria-label="省份" placeholder="全部省份" class="filter-w-sm" filterable clearable @change="changeProvince">
      <el-option label="地区未补齐" value="__missing__" />
      <el-option v-for="region in namedRegions" :key="region.province" :label="region.province" :value="region.province" />
    </el-select>
    <el-select v-model="form.city" aria-label="城市" placeholder="全部城市" class="filter-w-sm" :disabled="!form.province || form.province === '__missing__'" filterable clearable>
      <el-option v-for="city in cities" :key="city || '__missing__'" :label="city || '城市未补齐'" :value="city || '__missing__'" />
    </el-select>
    <el-select v-model="form.deal_status" aria-label="成交情况" class="filter-w-sm">
      <el-option label="全部成交情况" value="all" />
      <el-option v-for="(label, value) in DEAL_STATUS" :key="value" :label="label" :value="value" />
    </el-select>
    <template #advanced>
      <el-select v-model="form.assignee_user_id" aria-label="当前跟进人" placeholder="全部跟进人" class="filter-w-sm" filterable clearable>
        <el-option v-for="person in assignees" :key="person.id" :label="person.name" :value="person.id" />
      </el-select>
      <el-select v-model="form.collaboration_status" aria-label="协作状态" placeholder="全部协作状态" class="filter-w-sm" clearable>
        <el-option v-for="(label, value) in COLLABORATION_STATUS" :key="value" :label="label" :value="value" />
      </el-select>
      <el-date-picker v-model="form.date_from" type="date" value-format="YYYY-MM-DD" aria-label="最近联系开始日期" placeholder="最近联系开始日期" class="filter-w-sm" />
      <el-date-picker v-model="form.date_to" type="date" value-format="YYYY-MM-DD" aria-label="最近联系结束日期" placeholder="最近联系结束日期" class="filter-w-sm" />
      <el-select v-model="form.lifecycle_status" aria-label="生命周期" placeholder="全部生命周期" class="filter-w-sm" clearable>
        <el-option v-for="status in ['潜在', '活跃', '沉默', '流失']" :key="status" :label="status" :value="status" />
      </el-select>
      <el-checkbox v-model="form.never_contacted">从未联系</el-checkbox>
      <el-checkbox v-model="form.overdue">下次跟进已逾期</el-checkbox>
    </template>
  </FilterBar>
</template>

<script setup>
import { computed } from 'vue'
import FilterBar from '@/components/FilterBar.vue'
import { COLLABORATION_STATUS, DEAL_STATUS } from '../customerOverview'

const props = defineProps({
  form: { type: Object, required: true }, regions: { type: Array, required: true }, assignees: { type: Array, required: true },
  loading: Boolean, pending: Boolean,
})
defineEmits(['search', 'reset'])
const cities = computed(() => props.regions.find(region => region.province === props.form.province)?.cities || [])
const namedRegions = computed(() => props.regions.filter(region => region.province))
function changeProvince() {
  if (!cities.value.some(city => (city || '__missing__') === props.form.city)) props.form.city = ''
}
</script>
