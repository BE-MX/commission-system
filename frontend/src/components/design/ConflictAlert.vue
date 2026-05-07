<template>
  <div class="conflict-alert-wrapper" v-if="conflictResult">
    <!-- Conflicting unavailable slots: actual overlap with unavailable records -->
    <el-alert
      v-if="conflictResult.conflicting_unavailable_slots && conflictResult.conflicting_unavailable_slots.length > 0"
      type="error"
      show-icon
      :closable="false"
      class="conflict-alert-item"
    >
      <template #title>所选时段包含不可用日期，将转主管审核</template>
      <template #default>
        <div class="conflict-date-list">
          <el-tag
            v-for="(d, idx) in conflictResult.conflicting_unavailable_slots"
            :key="idx"
            type="danger"
            size="small"
            effect="plain"
          >{{ d.date }}{{ d.period === 'am' ? ' 上午' : d.period === 'pm' ? ' 下午' : '' }}</el-tag>
        </div>
      </template>
    </el-alert>

    <!-- Overloaded dates: capacity exceeded, will need supervisor review -->
    <el-alert
      v-if="conflictResult.overloaded_dates && conflictResult.overloaded_dates.length > 0"
      type="warning"
      show-icon
      :closable="false"
      class="conflict-alert-item"
    >
      <template #title>以下时段资源已满，将转主管审核</template>
      <template #default>
        <div class="conflict-date-list">
          <span
            v-for="item in conflictResult.overloaded_dates"
            :key="item.date + item.period"
            class="overload-item"
          >
            {{ item.date }}{{ item.period === 'am' ? ' 上午' : item.period === 'pm' ? ' 下午' : '' }}
            <span v-if="item.current_tasks != null" class="overload-detail">
              ({{ item.current_tasks }}/{{ item.capacity }})
            </span>
          </span>
        </div>
      </template>
    </el-alert>

    <!-- No conflict: all clear -->
    <el-alert
      v-if="noConflict"
      type="success"
      show-icon
      :closable="false"
      class="conflict-alert-item"
    >
      <template #title>日期可用，提交后直接进入设计部排期</template>
    </el-alert>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  conflictResult: {
    type: Object,
    default: null,
  },
})

const noConflict = computed(() => {
  if (!props.conflictResult) return false
  const r = props.conflictResult
  const hasConflictingUnavailable = r.conflicting_unavailable_slots && r.conflicting_unavailable_slots.length > 0
  const hasOverloaded = r.overloaded_dates && r.overloaded_dates.length > 0
  return !r.has_conflict && !hasConflictingUnavailable && !hasOverloaded
})
</script>

<style scoped>
.conflict-alert-wrapper {
  margin-bottom: 18px;
}
.conflict-alert-item {
  margin-bottom: 8px;
}
.conflict-alert-item:last-child {
  margin-bottom: 0;
}
.conflict-date-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
.overload-item {
  font-size: 13px;
  color: var(--text-secondary);
}
.overload-detail {
  color: var(--color-primary);
  font-weight: 600;
}
</style>
