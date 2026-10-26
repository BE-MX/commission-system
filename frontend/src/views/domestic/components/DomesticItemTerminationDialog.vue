<template>
  <el-dialog v-model="dialog.visible" title="终止明细" width="480px" style="max-width: calc(100vw - 24px)"
    :close-on-click-modal="!submitting" :close-on-press-escape="!submitting" :show-close="!submitting">
    <el-form label-position="top">
      <el-form-item label="产品">{{ dialog.item?.line_code }} · {{ dialog.item?.product_name }}</el-form-item>
      <el-form-item label="终止数量" required>
        <el-input-number v-model="dialog.qty" :min="1" :max="dialog.maxQty" :precision="0" :disabled="submitting" aria-label="终止数量" />
        <span class="quantity-limit">最多 {{ dialog.maxQty }} 件</span>
      </el-form-item>
      <el-form-item label="终止原因" required>
        <el-input v-model="dialog.reason" type="textarea" :rows="3" maxlength="500" show-word-limit :disabled="submitting" />
      </el-form-item>
      <p>仅终止所选数量，剩余产品继续履约；已扣款按终止数量退回客户余额，已有报工记录保留。</p>
    </el-form>
    <template #footer>
      <GlassButton variant="ghost" :disabled="submitting" @click="dialog.visible = false">取消</GlassButton>
      <GlassButton variant="danger" :loading="submitting" @click="$emit('confirm')">确认终止</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import GlassButton from '@/components/GlassButton.vue'
defineProps({ dialog: { type: Object, required: true }, submitting: Boolean })
defineEmits(['confirm'])
</script>

<style scoped>
.quantity-limit { margin-left: 12px; color: var(--text-secondary); }
p { color: var(--text-secondary); line-height: 1.6; }
</style>
