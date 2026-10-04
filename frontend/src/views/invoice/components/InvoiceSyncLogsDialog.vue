<template>
  <el-dialog v-model="visible" :title="title" width="760px">
    <el-table v-loading="loading" :data="rows" border class="list-table" max-height="420" v-sticky-scrollbar>
      <el-table-column prop="created_at" label="时间" min-width="150" max-width="170" show-overflow-tooltip>
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="action" label="动作" min-width="96" max-width="110">
        <template #default="{ row }">{{ actionText(row.action) }}</template>
      </el-table-column>
      <el-table-column prop="success" label="结果" min-width="100" max-width="130">
        <template #default="{ row }">
          <StatusBadge :type="row.success ? 'success' : 'danger'" effect="plain">
            {{ row.success ? '成功' : '失败' }}
          </StatusBadge>
        </template>
      </el-table-column>
      <el-table-column :sort-by="row => (row.error_message || (row.success ? 'OKKI 已受理' : '-'))" label="信息" min-width="240" show-overflow-tooltip>
        <template #default="{ row }">{{ row.error_message || (row.success ? 'OKKI 已受理' : '-') }}</template>
      </el-table-column>
    </el-table>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: Boolean,
  title: { type: String, default: '' },
  loading: Boolean,
  rows: { type: Array, default: () => [] },
  formatDateTime: { type: Function, required: true },
  actionText: { type: Function, required: true },
})
const emit = defineEmits(['update:modelValue'])
const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})
</script>
