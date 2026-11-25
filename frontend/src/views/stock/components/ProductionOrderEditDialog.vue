<template>
  <el-dialog
    v-model="visible"
    title="编辑生产订单"
    width="760px"
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
  >
    <ListPageStatus
      :loading="detail.loading.value"
      :error="detail.errorMessage.value"
      :paged="false"
      :has-data="Boolean(detail.data.value)"
      @retry="loadOrder"
    />
    <el-form v-if="detail.data.value" label-position="top" :model="form" :disabled="saving">
      <div class="order-fields">
        <el-form-item label="生产批次号">
          <el-input v-model="form.batch_no" maxlength="64" />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio :value="0">已提交</el-radio>
            <el-radio :value="1">已终止</el-radio>
            <el-radio :value="2">已完成</el-radio>
          </el-radio-group>
        </el-form-item>
      </div>
      <el-form-item label="备注">
        <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="500" show-word-limit />
      </el-form-item>
      <section v-if="detail.data.value.items_editable" aria-label="产品明细">
        <div class="item-heading">
          <h3>产品明细</h3>
          <GlassButton variant="secondary" left-icon="Plus" :disabled="saving" @click="addLine">添加产品</GlassButton>
        </div>
        <el-alert
          v-if="detail.data.value.has_linked_semifinished_order"
          title="该生产单已关联半成品采购单。修改产品明细后，请核对半成品需求。"
          type="warning"
          :closable="false"
          show-icon
        />
        <div v-for="line in lines" :key="line.key" class="item-row">
          <el-form-item label="产品型号" required>
            <ProductionOrderProductSelect
              v-if="line.editable && !line.receivedQty"
              v-model="line.product"
              :aria-label="line.productLabel ? '更换产品型号' : '选择新增产品型号'"
              :placeholder="line.productLabel || '搜索型号、名称或产品编号'"
            />
            <div v-else class="item-name">{{ line.productLabel }}</div>
          </el-form-item>
          <el-form-item label="下单数量" required>
            <el-input-number
              v-model="line.quantity"
              :min="Math.max(1, line.receivedQty)"
              :max="999999"
              :precision="0"
              controls-position="right"
              :disabled="!line.editable"
              aria-label="下单数量"
            />
          </el-form-item>
          <GlassButton
            v-if="line.id === null"
            class="remove-item"
            variant="link"
            link-tone="danger"
            left-icon="Delete"
            :disabled="saving"
            @click="lines = lines.filter(entry => entry !== line)"
          >移除</GlassButton>
        </div>
      </section>
    </el-form>
    <template #footer>
      <div class="dialog-footer">
        <el-button :disabled="saving" @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!detail.data.value" @click="save">保存</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import { getProductionOrderDetail, updateProductionOrder } from '@/api/stock'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { errorMessage } from '@/utils/errors'
import { msgError, msgSuccessText, msgWarning } from '@/utils/feedback'
import ProductionOrderProductSelect from './ProductionOrderProductSelect.vue'

const visible = defineModel({ type: Boolean, default: false })
const props = defineProps({ orderId: { type: Number, default: null } })
const emit = defineEmits(['saved'])
const form = reactive({ batch_no: '', status: 0, remark: '' })
const lines = ref([])
const saving = ref(false)
let newKey = 0

const detail = useAsyncResource(async (id, { signal }) => {
  const response = await getProductionOrderDetail(id, { signal, suppressToast: true })
  return response.data
})

async function loadOrder() {
  if (!await detail.load(props.orderId, { clear: true })) return
  const order = detail.data.value
  Object.assign(form, { batch_no: order.batch_no, remark: order.remark || '', status: order.status })
  lines.value = order.items.map(item => ({
    key: item.id,
    id: item.id,
    editable: item.status === 0,
    product: null,
    productLabel: [item.model, item.product_name].filter(Boolean).join(' · '),
    quantity: item.order_qty,
    originalQuantity: item.order_qty,
    receivedQty: item.received_qty,
  }))
}

watch([visible, () => props.orderId], ([opened]) => {
  if (opened) loadOrder()
  else detail.clear()
})

function addLine() {
  lines.value.push({
    key: 'new-' + ++newKey, id: null, editable: true,
    product: null, productLabel: '', quantity: 1, receivedQty: 0,
  })
}

async function save() {
  const order = detail.data.value
  if (saving.value || !order) return
  const payload = { item_updates: [], new_items: [] }
  if (form.batch_no !== order.batch_no) payload.batch_no = form.batch_no
  if (form.status !== order.status) payload.status = form.status
  if (form.remark !== (order.remark || '')) payload.remark = form.remark
  if (order.items_editable) {
    for (const line of lines.value) {
      if (line.id !== null && !line.product && line.quantity === line.originalQuantity) continue
      if (line.id === null && !line.product) return msgWarning('请选择新增产品的型号')
      if (!Number.isInteger(line.quantity) || line.quantity < Math.max(1, line.receivedQty) || line.quantity > 999999) {
        return msgWarning('请填写有效的下单数量')
      }
      const productId = line.product?.product_id_text
      if (line.id === null) payload.new_items.push({ product_id: productId, order_qty: line.quantity })
      else payload.item_updates.push({
        item_id: line.id, expected_order_qty: line.originalQuantity,
        order_qty: line.quantity, ...(productId ? { product_id: productId } : {}),
      })
    }
  }

  saving.value = true
  try {
    await updateProductionOrder(order.id, payload, { suppressToast: true })
    const itemsChanged = payload.item_updates.length || payload.new_items.length
    msgSuccessText(itemsChanged ? '已保存。已发出的生产单或工序卡请重新打印。' : '已更新')
    visible.value = false
    emit('saved', order.id)
  } catch (error) {
    msgError(errorMessage(error, '更新生产订单失败'), error)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.order-fields, .item-row {
  display: grid;
  gap: 12px;
}

.order-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }

.item-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.item-heading h3 { margin: 0; font-size: 15px; }

.item-row {
  grid-template-columns: minmax(0, 1fr) 128px auto;
  align-items: end;
  padding-top: 12px;
  border-bottom: 1px solid var(--border-color);
}

.item-row .el-form-item { min-width: 0; margin-bottom: 12px; }
.item-row .el-input-number { width: 100%; }
.item-name { overflow-wrap: anywhere; }
.remove-item { margin-bottom: 12px; }

@media (max-width: 600px) {
  .order-fields { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .item-row { grid-template-columns: minmax(0, 128px) auto; gap: 0 12px; }
  .item-row .el-form-item:first-child { grid-column: 1 / -1; }
  .remove-item { justify-self: start; }
}
</style>
