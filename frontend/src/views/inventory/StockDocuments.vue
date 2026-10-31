<template>
  <div ref="panelRef" class="table-card">
    <div class="action-bar">
      <GlassButton
        v-permission="'inventory:write'"
        variant="primary"
        left-icon="Plus"
        @click="editorOpen = true"
      >
        新建库存单据
      </GlassButton>
      <TableTools
        v-model:visible-keys="visibleKeys"
        v-model:density="density"
        :columns="columns"
        :fullscreen="isFullscreen"
        :loading="resource.loading.value"
        @refresh="load(offset)"
        @fullscreen="toggleFullscreen"
      />
    </div>
    <ListPageStatus
      :error="resource.errorMessage.value"
      :loading="resource.loading.value"
      :has-data="resource.hasData.value"
      :data-page="offset / 20 + 1"
      @retry="load(attemptedOffset)"
    />
    <el-table
      :data="resource.data.value"
      v-loading="resource.loading.value"
      border
      class="list-table"
      :class="densityClass"
      :max-height="isFullscreen ? undefined : 640"
     v-sticky-scrollbar>
      <el-table-column
        v-for="c in columns.filter(c => visibleKeys.includes(c.key))"
        :key="c.key"
        :label="c.label"
        min-width="130"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          {{ c.key === 'kind' ? kindLabels[row.kind] || row.kind : c.key === 'created_at' ? formatBeijingDateTime(row.created_at) : row[c.key] ?? '—' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="160" fixed="right" class-name="table-action-column">
        <template #default="{ row }">
          <GlassButton variant="link" left-icon="View" @click="showDetail(row.id)">详情</GlassButton>
          <GlassButton
            v-if="canReverse(row)"
            v-permission="'inventory:admin'"
            variant="link"
            link-tone="danger"
            left-icon="RefreshLeft"
            @click="openReversal(row)"
          >
            冲销
          </GlassButton>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty v-if="!resource.error.value" description="暂无库存单据" :image-size="96" />
      </template>
    </el-table>
    <div class="pager">
      <GlassButton
        :disabled="offset === 0 || resource.loading.value"
        left-icon="ArrowLeft"
        @click="load(offset - 20)"
      >
        上一批
      </GlassButton>
      <span>第 {{ offset / 20 + 1 }} 批，每批 20 条</span>
      <GlassButton
        :disabled="resource.data.value.length < 20 || resource.loading.value"
        right-icon="ArrowRight"
        @click="load(offset + 20)"
      >
        下一批
      </GlassButton>
    </div>
    <StockDocumentEditor v-model="editorOpen" @saved="load(0)" />
    <DetailDrawer v-model="detailOpen" title="库存单据详情" width="760px" :loading="detail.loading.value">
      <ListPageStatus
        :error="detail.errorMessage.value"
        :loading="detail.loading.value"
        :has-data="detail.hasData.value"
        @retry="detail.load()"
      />
      <template v-if="detail.data.value">
        <p>
          单据
          {{ detail.data.value.id }}
          ·
          {{ kindLabels[detail.data.value.kind] || detail.data.value.kind }}
          ·
          {{ formatBeijingDateTime(detail.data.value.created_at) }}
        </p>
        <p>原因：{{ detail.data.value.reason }}</p>
        <p>来源：{{ detail.data.value.source_type || '未填写' }} / {{ detail.data.value.source_id || '未填写' }}</p>
        <p v-if="detail.data.value.reversed_by_id">已由单据 {{ detail.data.value.reversed_by_id }} 冲销</p>
        <p v-if="detail.data.value.reversal_of_id">冲销原单据 {{ detail.data.value.reversal_of_id }}</p>
        <el-table :data="detail.data.value.movements" border class="list-table" v-sticky-scrollbar>
          <el-table-column label="仓库" min-width="120">
            <template #default="{ row }">
              {{ row.warehouse_name || warehouseName(row.warehouse_id) }}
            </template>
          </el-table-column>
          <el-table-column label="SKU" min-width="130">
            <template #default="{ row }">{{ row.sku_code || `SKU #${row.sku_id}` }}</template>
          </el-table-column>
          <el-table-column label="质量" min-width="110">
            <template #default="{ row }">
              <StatusBadge :type="qualityLabels[row.quality]?.type || 'info'">
                {{ qualityLabels[row.quality]?.label || row.quality }}
              </StatusBadge>
            </template>
          </el-table-column>
          <el-table-column prop="on_hand_delta" label="在手变动" min-width="100" />
          <el-table-column prop="reserved_delta" label="预占变动" min-width="100" />
          <el-table-column prop="on_hand_after" label="变动后在手" min-width="110" />
          <el-table-column prop="reserved_after" label="变动后预占" min-width="110" />
        </el-table>
      </template>
    </DetailDrawer>
    <el-dialog
      v-model="reversalOpen"
      title="冲销库存单据"
      width="480px"
      :close-on-click-modal="!reversing"
      :close-on-press-escape="!reversing"
      :show-close="!reversing"
    >
      <p>冲销单据 {{ reversalTarget?.id }}。库存不能变负，已被预占或业务占用的数量可能阻止冲销。</p>
      <el-form label-position="top" :disabled="reversing">
        <el-form-item label="冲销原因（必填）">
          <el-input v-model="reversalReason" type="textarea" maxlength="500" />
        </el-form-item>
      </el-form>
      <el-alert v-if="reversalError" :title="reversalError" type="error" :closable="false" />
      <template #footer>
        <div class="dialog-footer">
          <GlassButton :disabled="reversing" @click="reversalOpen = false">取消</GlassButton>
          <GlassButton variant="danger" :loading="reversing" @click="reverse">确认冲销</GlassButton>
        </div>
      </template>
    </el-dialog>
  </div>
</template>
<script setup>
import { onMounted, ref, watch } from 'vue'
import { getDocuments, getDocument, getWarehouses, reverseDocument } from '@/api/inventory'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import StockDocumentEditor from './components/StockDocumentEditor.vue'
import { kindLabels, qualityLabels, movementKinds } from './labels'
import { formatBeijingDateTime } from '@/utils/datetime'
import { msgSuccess, msgError, confirmDanger, isFeedbackCancelled } from '@/utils/feedback'
import { errorMessage } from '@/utils/errors'
const resource = useAsyncResource(async (params, { signal }) => (await getDocuments(params, { signal, suppressToast: true })).data, { initialData: [] })
const detail = useAsyncResource(async (id, { signal }) => (await getDocument(id, { signal, suppressToast: true })).data)
const warehouses = useAsyncResource(async (_, { signal }) => (await getWarehouses({ signal, suppressToast: true })).data, { initialData: [] })
const columns = [{ key: 'id', label: '单据号' }, { key: 'kind', label: '类型' }, { key: 'reason', label: '业务原因' }, { key: 'source_type', label: '来源类型' }, { key: 'source_id', label: '来源单号' }, { key: 'created_at', label: '创建时间' }, { key: 'reversed_by_id', label: '冲销单号' }]
const { panelRef, visibleKeys, density, densityClass, isFullscreen, toggleFullscreen } = useTableView('inventory-documents', columns)
const offset = ref(0), editorOpen = ref(false), detailOpen = ref(false), reversalOpen = ref(false), reversalTarget = ref(null), reversalReason = ref(''), reversalError = ref(''), reversing = ref(false)
let reversalKey = null
watch(reversalReason, () => { reversalKey = null; reversalError.value = '' }, { flush: 'sync' })
const canReverse = row => movementKinds.includes(row.kind) && !row.reversal_of_id && !row.reversed_by_id
const warehouseName = id => warehouses.data.value.find(w => w.id === id)?.name || `仓库 #${id}`
const attemptedOffset = ref(0)
async function load(next = 0) { attemptedOffset.value = next; if (await resource.load({ offset: next, limit: 20 })) offset.value = next }
function showDetail(id) { detailOpen.value = true; detail.load(id, { clear: true }) }
function openReversal(row) { reversalTarget.value = row; reversalReason.value = ''; reversalKey = null; reversalError.value = ''; reversalOpen.value = true }
async function reverse() {
  if (reversing.value) return
  if (!reversalReason.value.trim()) { msgError('请填写冲销原因'); return }
  reversing.value = true
  try { await confirmDanger('冲销库存单据', String(reversalTarget.value.id), '将生成反向库存流水，原单据保留。'); reversalKey ||= crypto.randomUUID(); await reverseDocument(reversalTarget.value.id, { idempotency_key: reversalKey, reason: reversalReason.value.trim() }); msgSuccess('库存冲销'); reversalOpen.value = false; await load(offset.value); if (detailOpen.value) await detail.load() }
  catch (error) { if (!isFeedbackCancelled(error)) { reversalError.value = errorMessage(error); msgError('冲销失败', error) } }
  finally { reversing.value = false }
}
onMounted(() => { load(); warehouses.load() })
</script>
