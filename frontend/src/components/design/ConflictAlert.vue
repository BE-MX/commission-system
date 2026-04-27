<template>
  <div class="conflict-alert-wrapper" v-if="conflictResult">
    <!-- Unavailable dates: hard block -->
    <el-alert
      v-if="conflictResult.unavailable_dates && conflictResult.unavailable_dates.length > 0"
      type="error"
      show-icon
      :closable="false"
      class="conflict-alert-item"
    >
      <template #title>以下日期为不可用日期</template>
      <template #default>
        <div class="conflict-date-list">
          <el-tag
            v-for="d in conflictResult.unavailable_dates"
            :key="d"
            type="danger"
            size="small"
            effect="plain"
          >{{ d }}</el-tag>
        </div>
      </template>
    </el-alert>

    <!-- Overloaded dates: warning, will need supervisor review -->
    <el-alert
      v-if="conflictResult.overloaded_dates && conflictResult.overloaded_dates.length > 0"
      type="warning"
      show-icon
      :closable="false"
      class="conflict-alert-item"
    >
      <template #title>以下日期资源已满，提交后将转主管审核</template>
      <template #default>
        <div class="conflict-date-list">
          <span
            v-for="item in conflictResult.overloaded_dates"
            :key="item.date || item"
            class="overload-item"
          >
            {{ item.date || item }}
            <span v-if="item.active_count != null" class="overload-detail">
              ({{ item.active_count }}/{{ item.max_capacity }})
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
      <template #title>日期可用，提交后直接进入设计部确认</template>
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
  const hasUnavailable = r.unavailable_dates && r.unavailable_dates.length > 0
  const hasOverloaded = r.overloaded_dates && r.overloaded_dates.length > 0
  return !r.has_conflict && !hasUnavailable && !hasOverloaded
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
  color: #606266;
}
.overload-detail {
  color: #E6A23C;
  font-weight: 600;
}
</style>
