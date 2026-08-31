<template>
  <el-dialog
    :model-value="modelValue" title="异常跳过记录" width="760px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert
      type="warning" :closable="false" show-icon
      title="这里只显示主管人工跳过；自动分流和可选工序放行不在此处撤销。"
    />
    <el-table :data="audits" v-loading="loading" border class="list-table audit-table">
      <el-table-column prop="process_name" label="工序" min-width="100" show-overflow-tooltip />
      <el-table-column prop="skipped_qty" label="数量" min-width="70" />
      <el-table-column label="单件" min-width="130" show-overflow-tooltip>
        <template #default="{ row: audit }">{{ audit.unit_codes?.join('、') || '-' }}</template>
      </el-table-column>
      <el-table-column label="原因" min-width="160" show-overflow-tooltip>
        <template #default="{ row: audit }">{{ audit.reason }}</template>
      </el-table-column>
      <el-table-column label="操作人" min-width="90" show-overflow-tooltip>
        <template #default="{ row: audit }">{{ audit.operator_name }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="时间" min-width="150" show-overflow-tooltip />
      <el-table-column label="状态" min-width="80">
        <template #default="{ row: audit }">
          <el-tag v-if="audit.revoked" size="small" type="info" effect="plain">已撤销</el-tag>
          <el-tag v-else size="small" type="warning" effect="plain">有效</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="90">
        <template #default="{ row: audit }">
          <GlassButton
            v-if="!audit.revoked" v-permission="'domestic:admin'"
            variant="link" link-tone="danger" left-icon="RefreshLeft"
            :loading="revokingId === audit.skip_log_id" @click="emit('revoke', audit)"
          >撤销</GlassButton>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && audits.length === 0" description="暂无人工异常跳过记录" />
    <template #footer>
      <GlassButton variant="ghost" @click="emit('refresh')">刷新</GlassButton>
      <GlassButton variant="secondary" @click="emit('update:modelValue', false)">关闭</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import GlassButton from '@/components/GlassButton.vue'

defineProps({
  modelValue: { type: Boolean, default: false },
  audits: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  revokingId: { type: Number, default: null },
})

const emit = defineEmits(['update:modelValue', 'refresh', 'revoke'])
</script>

<style scoped>
.audit-table { margin-top: 12px; }
</style>
