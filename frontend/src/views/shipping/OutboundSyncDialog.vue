<template>
  <el-dialog :model-value="visible" title="同步最新订单资料" width="760px" append-to-body
    :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy"
    @update:model-value="$emit('update:visible', $event)">
    <template v-if="preview">
      <p>出库单：{{ row?.outbound_no }} · 订单发票：{{ preview.invoice_no }}</p>
      <el-alert v-if="preview.recover" :title="preview.message" type="warning" :closable="false" show-icon />
      <template v-else>
        <el-alert v-if="preview.requires_recheck" :title="preview.inspection_status === 'submitted'
          ? '验货单已提交。请先在验货单列表撤回，再重新预览并同步；原照片保留为旧版本证据。'
          : '本单已有验货照片。确认同步后，受影响照片保留为旧版本证据，仓库须补拍变更明细并重新提交。'"
          type="warning" :closable="false" show-icon />
        <el-alert title="同步发制品及配件的增删、规格、数量、价格和备注。同步后请重新打印旧纸单。" type="info" :closable="false" show-icon />
        <div v-if="preview.serial_changed" class="sync-remark"><strong>出库单号</strong><p>当前：{{ preview.serial_before }}</p><p>同步后：{{ preview.serial_after }}</p></div>
        <el-table v-if="preview.changes?.length" :data="preview.changes" border class="list-table sync-changes" max-height="360">
          <el-table-column prop="action" label="操作" min-width="68" />
          <el-table-column label="当前出库明细" min-width="240">
            <template #default="{ row: change }">
              <template v-if="change.before">{{ change.before.name }}<br>{{ change.before.quantity }} {{ change.before.unit }} · 单价 {{ change.before.price }}</template>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="同步后" min-width="240">
            <template #default="{ row: change }">
              <template v-if="change.after">{{ change.after.name }}<br>{{ change.after.quantity }} {{ change.after.unit }} · 单价 {{ change.after.price }}</template>
              <span v-else>删除该明细</span>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="preview.remark_before !== preview.remark_after" class="sync-remark">
          <strong>出库备注</strong>
          <p>当前：{{ preview.remark_before || '无' }}</p>
          <p>同步后：{{ preview.remark_after || '清空备注' }}</p>
        </div>
        <p v-if="!preview.changed">小满出库单已与最新订单一致，点击下方按钮刷新方舟打印资料。</p>
      </template>
    </template>
    <template #footer>
      <GlassButton :disabled="busy" @click="$emit('update:visible', false)">取消</GlassButton>
      <GlassButton variant="primary" :loading="busy" :disabled="preview?.requires_recheck && preview?.inspection_status === 'submitted'" @click="$emit('apply')">
        {{ busy ? '正在核对同步结果…' : preview?.recover ? '重新核对结果' : preview?.requires_recheck ? '同步并重验' : preview?.changed ? '确认同步' : '刷新打印资料' }}
      </GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import GlassButton from '@/components/GlassButton.vue'
defineProps({ visible: Boolean, busy: Boolean, preview: Object, row: Object })
defineEmits(['update:visible', 'apply'])
</script>

<style scoped>
.sync-changes { margin-top: 16px; }
.sync-remark { margin-top: 16px; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
