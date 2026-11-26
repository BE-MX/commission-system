<template>
  <el-dialog
    v-model="visible"
    class="po-edit-dialog"
    :title="detail.data.value ? `编辑生产订单 · ${detail.data.value.order_no}` : '编辑生产订单'"
    width="760px"
    top="4vh"
    :fullscreen="isNarrow"
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    :before-close="confirmClose"
  >
    <ListPageStatus
      :loading="detail.loading.value"
      :error="detail.errorMessage.value"
      :paged="false"
      :has-data="Boolean(detail.data.value)"
      @retry="loadOrder"
    />
    <el-form v-if="detail.data.value" label-position="top" :model="form" :disabled="saving" class="po-edit">
      <div class="order-fields">
        <el-form-item label="生产批次号">
          <el-input v-model="form.batch_no" maxlength="64" />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio-button :value="0">已提交</el-radio-button>
            <el-radio-button :value="1">已终止</el-radio-button>
            <el-radio-button :value="2">已完成</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注" class="remark-field">
          <el-input v-model="form.remark" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" maxlength="500" />
        </el-form-item>
      </div>

      <section class="items" aria-label="产品明细">
        <div class="items-toolbar">
          <div class="items-title">
            <h3>产品明细</h3>
            <span class="items-summary">{{ lines.length }} 款 · 共 {{ totalQty }} 件</span>
            <span v-if="changedCount" class="changed-badge">已修改 {{ changedCount }} 款</span>
          </div>
          <div class="items-actions">
            <el-input
              v-model="keyword"
              class="items-search"
              clearable
              placeholder="搜索颜色、长度、系列"
              aria-label="搜索产品明细"
              prefix-icon="Search"
            />
            <el-checkbox v-if="changedCount" v-model="onlyChanged">只看已修改</el-checkbox>
            <GlassButton v-if="itemsEditable" variant="secondary" left-icon="Plus" :disabled="saving" @click="addLine">添加产品</GlassButton>
          </div>
        </div>
        <p v-if="!itemsEditable" class="items-note">当前订单状态下产品明细只能查看，不能修改。</p>
        <el-alert
          v-else-if="detail.data.value.has_linked_semifinished_order"
          title="该生产单已关联半成品采购单。修改产品明细后，请核对半成品需求。"
          type="warning"
          :closable="false"
          show-icon
        />

        <div class="items-table" role="table" aria-label="产品明细列表" tabindex="0">
          <div class="items-head" role="row">
            <span role="columnheader">颜色</span>
            <span role="columnheader">长度(寸)</span>
            <span role="columnheader">克重</span>
            <span role="columnheader" class="num">已入库</span>
            <span role="columnheader">下单数量</span>
            <span role="columnheader" class="sr-only">操作</span>
          </div>
          <div v-if="!groups.length" class="items-empty" role="row"><span role="cell">没有符合条件的产品</span></div>
          <div v-for="group in groups" :key="group.key" class="item-group" role="rowgroup">
            <div class="group-head" role="row">
              <span class="group-series" role="rowheader">{{ group.series }}</span>
              <span v-if="group.model" class="group-model" role="cell">{{ group.model }}</span>
              <span class="group-count" role="cell">{{ group.lines.length }} 款</span>
            </div>
            <div
              v-for="line in group.lines"
              :key="line.key"
              class="item-row"
              :class="{ 'is-changed': isChanged(line), 'is-deleted': line.deleted, 'is-locked': !canChangeQty(line) }"
              role="row"
            >
              <div v-if="line.picking" class="item-picker" role="cell" aria-colspan="3">
                <ProductionOrderProductSelect
                  v-model="line.product"
                  :aria-label="line.id === null ? '选择新增产品型号' : '更换产品型号'"
                  :placeholder="line.originalName ? `把 ${line.originalName.color || line.originalName.raw} 换成…（搜索型号、名称或编号）` : '搜索型号、名称或产品编号'"
                  autofocus
                  @update:model-value="value => { if (value) line.picking = false }"
                />
              </div>
              <template v-else>
                <div class="item-color" role="cell" :title="currentName(line).raw">
                  <strong>{{ currentName(line).color || currentName(line).raw }}</strong>
                  <span v-if="line.deleted" class="item-deleted-tag">待删除</span>
                  <span v-else-if="line.product && line.originalName" class="item-was">原 {{ line.originalName.color || line.originalName.raw }}</span>
                </div>
                <span class="item-spec" role="cell"><span class="cell-label">长度</span>{{ currentName(line).length || '—' }}</span>
                <span class="item-spec" role="cell"><span class="cell-label">克重</span>{{ currentName(line).weight || '—' }}</span>
              </template>
              <span class="item-received num" role="cell"><span class="cell-label">已入库</span>{{ line.receivedQty || '—' }}</span>
              <div class="item-qty" role="cell">
                <el-input-number
                  v-model="line.quantity"
                  size="small"
                  :min="Math.max(1, line.receivedQty)"
                  :max="999999"
                  :precision="0"
                  controls-position="right"
                  :disabled="!canChangeQty(line) || line.deleted"
                  :aria-label="`${lineName(line)} 下单数量`"
                />
                <span v-if="line.id !== null && !line.deleted && line.quantity !== line.originalQuantity" class="item-was">原 {{ line.originalQuantity }}</span>
              </div>
              <div class="item-ops" role="cell">
                <span v-if="!line.editable" class="item-locked">{{ ITEM_STATUS_LABELS[line.status] || '不可修改' }}</span>
                <template v-else-if="line.picking">
                  <GlassButton v-if="line.id !== null" variant="link" :disabled="saving" :aria-label="`取消更换 ${lineName(line)}`" @click="line.picking = false">取消</GlassButton>
                </template>
                <template v-else-if="!line.deleted">
                  <GlassButton v-if="canChangeProduct(line)" variant="link" :disabled="saving" :aria-label="`更换 ${lineName(line)}`" @click="line.picking = true">更换</GlassButton>
                  <GlassButton
                    v-if="line.id !== null && canChangeProduct(line) && !isChanged(line)"
                    v-permission="'production:admin'"
                    variant="link"
                    link-tone="danger"
                    :disabled="saving"
                    :aria-label="`删除 ${lineName(line)}`"
                    @click="line.deleted = true"
                  >删除</GlassButton>
                </template>
                <GlassButton v-if="line.id !== null && isChanged(line)" variant="link" :disabled="saving" :aria-label="`撤销 ${lineName(line)} 的修改`" @click="revertLine(line)">撤销</GlassButton>
                <GlassButton v-if="line.id === null" variant="link" link-tone="danger" :disabled="saving" @click="removeLine(line)">移除</GlassButton>
              </div>
            </div>
          </div>
        </div>
      </section>
    </el-form>
    <template #footer>
      <div class="dialog-footer">
        <span class="footer-summary">{{ changeSummary }}</span>
        <el-button :disabled="saving" @click="confirmClose(() => { visible = false })">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!detail.data.value" @click="save">保存</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import { getProductionOrderDetail, updateProductionOrder } from '@/api/stock'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { errorMessage } from '@/utils/errors'
import { confirmAction, msgError, msgSuccessText, msgWarning } from '@/utils/feedback'
import { parseProductName } from '@/utils/productName'
import { buildEditPayload, isLineChanged as isChanged, payloadChangesItems } from '../composables/productionOrderEditPayload'
import ProductionOrderProductSelect from './ProductionOrderProductSelect.vue'

const visible = defineModel({ type: Boolean, default: false })
const props = defineProps({ orderId: { type: Number, default: null } })
const emit = defineEmits(['saved'])
const form = reactive({ batch_no: '', status: 0, remark: '' })
const lines = ref([])
const saving = ref(false)
const keyword = ref('')
const onlyChanged = ref(false)
let newKey = 0
const ITEM_STATUS_LABELS = { 1: '已终止', 2: '已完成' }

const narrowQuery = typeof window !== 'undefined' ? window.matchMedia('(max-width: 640px)') : null
const isNarrow = ref(Boolean(narrowQuery?.matches))
const syncNarrow = event => { isNarrow.value = event.matches }
narrowQuery?.addEventListener('change', syncNarrow)
onBeforeUnmount(() => narrowQuery?.removeEventListener('change', syncNarrow))

const detail = useAsyncResource(async (id, { signal }) => {
  const response = await getProductionOrderDetail(id, { signal, suppressToast: true })
  return response.data
})

const itemsEditable = computed(() => Boolean(detail.data.value?.items_editable))
const totalQty = computed(() => lines.value.reduce((sum, line) => sum + (line.deleted ? 0 : Number(line.quantity) || 0), 0))
const changedCount = computed(() => (itemsEditable.value ? lines.value.filter(isChanged).length : 0))
const formChanged = computed(() => {
  const order = detail.data.value
  return Boolean(order) && (form.batch_no !== order.batch_no || form.status !== order.status || form.remark !== (order.remark || ''))
})
const changeSummary = computed(() => {
  const added = lines.value.filter(line => line.id === null).length
  const deleted = lines.value.filter(line => line.deleted).length
  const edited = changedCount.value - added - deleted
  const parts = []
  if (edited) parts.push(`修改 ${edited} 款`)
  if (added) parts.push(`新增 ${added} 款`)
  if (deleted) parts.push(`删除 ${deleted} 款`)
  if (formChanged.value) parts.push('订单信息有改动')
  return parts.length ? `待保存：${parts.join('，')}` : ''
})

const groups = computed(() => {
  const term = keyword.value.trim().toLowerCase()
  const map = new Map()
  for (const line of lines.value) {
    // 新增行始终可见，避免选型号的输入框被搜索或筛选藏起来
    if (line.id !== null && onlyChanged.value && !isChanged(line)) continue
    if (line.id !== null && term && !searchText(line).includes(term)) continue
    const key = line.id === null ? 'new' : `${line.groupSeries}|${line.groupModel}`
    if (!map.has(key)) {
      map.set(key, line.id === null
        ? { key, series: '新增产品', model: '', lines: [] }
        : { key, series: line.groupSeries, model: line.groupModel, lines: [] })
    }
    map.get(key).lines.push(line)
  }
  const list = [...map.values()]
  const added = list.findIndex(group => group.key === 'new')
  if (added > 0) list.unshift(...list.splice(added, 1))
  return list
})

function currentName(line) {
  return line.product ? parseProductName(line.product.name) : (line.originalName || parseProductName(''))
}

function lineName(line) {
  const name = currentName(line)
  return [name.color || name.raw, name.length && `${name.length} 寸`, name.weight].filter(Boolean).join(' ')
}

function searchText(line) {
  return [line.originalName?.raw, currentName(line).raw, line.groupModel, line.product?.model, line.product?.product_no]
    .filter(Boolean).join(' ').toLowerCase()
}

function canChangeQty(line) {
  return itemsEditable.value && line.editable
}

function canChangeProduct(line) {
  return canChangeQty(line) && !line.receivedQty
}

async function loadOrder() {
  keyword.value = ''
  onlyChanged.value = false
  if (!await detail.load(props.orderId, { clear: true })) return
  const order = detail.data.value
  Object.assign(form, { batch_no: order.batch_no, remark: order.remark || '', status: order.status })
  lines.value = order.items.map(item => {
    const originalName = parseProductName(item.product_name)
    return {
      key: item.id,
      id: item.id,
      status: item.status,
      editable: item.status === 0,
      deleted: false,
      product: null,
      picking: false,
      originalName,
      groupSeries: originalName.color ? originalName.series : '其他产品',
      groupModel: item.model || '',
      quantity: item.order_qty,
      originalQuantity: item.order_qty,
      receivedQty: item.received_qty,
    }
  })
}

watch(changedCount, count => { if (!count) onlyChanged.value = false })

watch([visible, () => props.orderId], ([opened]) => {
  if (opened) loadOrder()
  else detail.clear()
})

function addLine() {
  keyword.value = ''
  onlyChanged.value = false
  lines.value.unshift({
    key: 'new-' + ++newKey, id: null, status: 0, editable: true, deleted: false, product: null, picking: true,
    originalName: null, groupSeries: '', groupModel: '', quantity: 1, originalQuantity: 1, receivedQty: 0,
  })
}

function removeLine(line) {
  lines.value = lines.value.filter(entry => entry !== line)
}

function revertLine(line) {
  line.deleted = false
  line.product = null
  line.picking = false
  line.quantity = line.originalQuantity
}

async function confirmClose(done) {
  if (saving.value) return
  if (changedCount.value || formChanged.value) {
    try {
      await confirmAction('有未保存的修改，关闭后将丢失。', '放弃修改？', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning' })
    } catch {
      return
    }
  }
  done()
}

async function save() {
  const order = detail.data.value
  if (saving.value || !order) return
  const { payload, error } = buildEditPayload(order, form, lines.value)
  if (error) return showInvalid(error)

  saving.value = true
  try {
    await updateProductionOrder(order.id, payload, { suppressToast: true })
    msgSuccessText(payloadChangesItems(payload) ? '已保存。已发出的生产单或工序卡请重新打印。' : '已更新')
    visible.value = false
    emit('saved', order.id)
  } catch (error) {
    msgError(errorMessage(error, '更新生产订单失败'), error)
  } finally {
    saving.value = false
  }
}

function showInvalid(message) {
  keyword.value = ''
  onlyChanged.value = false
  msgWarning(message)
}
</script>

<style scoped src="./ProductionOrderEditDialog.css"></style>

<style>
.po-edit-dialog .el-dialog__body { padding-top: 8px; }
@media (max-width: 640px) {
  .po-edit-dialog.is-fullscreen .el-dialog__body { padding: 8px 16px; }
  /* 全屏时只滚动内容区，保存按钮常驻底部，不必滑过几百行明细 */
  .po-edit-dialog.is-fullscreen { display: flex; flex-direction: column; overflow: hidden; }
  .po-edit-dialog.is-fullscreen .el-dialog__body { flex: 1; min-height: 0; overflow-y: auto; }
  .po-edit-dialog.is-fullscreen .el-dialog__footer { border-top: 1px solid var(--border-color); }
}
</style>
