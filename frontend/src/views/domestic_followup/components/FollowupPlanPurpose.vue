<template>
  <el-form-item label="计划用途" required>
    <el-select v-model="form.plan_purpose" class="full" placeholder="请选择用途">
      <el-option label="开发" value="development" />
      <el-option label="维护" value="maintenance" />
      <el-option label="其他" value="other" />
    </el-select>
  </el-form-item>
  <el-form-item v-if="assignees.length" label="计划承办人">
    <el-select v-model="form.plan_assignee_user_id" class="full" clearable
               :placeholder="form.plan_purpose === 'development' ? '默认当前跟进人' : '默认本人'">
      <el-option v-for="person in assignees" :key="person.user_id" :value="person.user_id"
                 :label="`${person.name || `人员 #${person.user_id}`} · ${person.primary ? '当前跟进人' : '协作人'}`" />
    </el-select>
  </el-form-item>
</template>

<script setup>
defineProps({ form: { type: Object, required: true }, assignees: { type: Array, default: () => [] } })
</script>

<style scoped>
.full { width: 100%; }
</style>
