<template>
  <div class="table-actions">
    <GlassButton v-if="canReadRecord(row)" variant="link" left-icon="View" @click="$emit('detail', row)">详情</GlassButton>
    <template v-if="row.link && canReadRecord(row)">
      <GlassButton variant="link" left-icon="User" @click="$emit('customer', row)">关联客户</GlassButton>
      <GlassButton v-permission="'client_desk:write'" variant="link" left-icon="Close" link-tone="danger" :disabled="disabled" @click="$emit('unlink', row)">撤销</GlassButton>
    </template>
    <GlassButton v-else v-permission="'client_desk:write'" variant="link" left-icon="Connection" :disabled="disabled" @click="$emit('link', row)">匹配客户</GlassButton>
  </div>
</template>

<script setup>
import { canReadRecord } from './feedState'
defineProps({ row: { type: Object, required: true }, disabled: Boolean })
defineEmits(['detail', 'customer', 'unlink', 'link'])
</script>
