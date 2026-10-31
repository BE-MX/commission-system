<template>
  <el-dialog
    :model-value="modelValue"
    title="新建库存单据"
    width="760px"
    :close-on-click-modal="!saving"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" label-position="top" :disabled="saving || reading">
      <el-form-item label="业务类型">
        <el-select v-model="form.kind" @change="clearVersions">
          <el-option label="收货" value="receipt" />
          <el-option label="调拨" value="transfer" />
          <el-option v-permission="'inventory:admin'" label="期初（管理员）" value="opening" />
          <el-option v-permission="'inventory:admin'" label="调整（管理员）" value="adjustment" />
          <el-option v-permission="'inventory:admin'" label="盘点（管理员）" value="count" />
        </el-select>
      </el-form-item>
      <el-form-item
        label="业务原因"
        prop="reason"
        :rules="[{ required: true, whitespace: true, message: '请填写业务原因' }]"
      >
        <el-input v-model="form.reason" type="textarea" maxlength="500" show-word-limit />
      </el-form-item>
      <div class="field-grid">
        <el-form-item label="来源类型（选填）">
          <el-input v-model="form.source_type" maxlength="32" placeholder="例如采购收货" />
        </el-form-item>
        <el-form-item label="来源单号（选填）">
          <el-input v-model="form.source_id" maxlength="64" />
        </el-form-item>
      </div>
      <p v-if="form.kind === 'count'">实盘数将与读取时的库存版本核对。库存变化会阻止提交，请重新读取后核实实盘数。</p>
      <p v-if="form.kind === 'adjustment'">正数增加在手库存，负数减少在手库存；不能减少已预占数量。</p>
      <fieldset v-for="(line, index) in form.lines" :key="line.key" class="stock-line">
        <legend>第 {{ index + 1 }} 行</legend>
        <div class="field-grid">
          <el-form-item label="仓库">
            <el-select
              v-model="line.warehouse_id"
              filterable
              placeholder="选择仓库"
              @change="line.expected_version = null"
            >
              <el-option v-for="w in activeWarehouses" :key="w.id" :label="w.name" :value="w.id" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="form.kind === 'transfer'" label="目标仓库">
            <el-select v-model="line.destination_warehouse_id" filterable placeholder="选择不同目标仓库">
              <el-option
                v-for="w in activeWarehouses.filter(w => w.id !== line.warehouse_id)"
                :key="w.id"
                :label="w.name"
                :value="w.id"
              />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="产品 / SKU">
          <SkuPicker
            v-model="line.sku_id"
            :disabled="saving || reading"
            @update:model-value="line.expected_version = null"
          />
        </el-form-item>
        <div class="field-grid">
          <el-form-item label="质量状态">
            <el-select v-model="line.quality" @change="line.expected_version = null">
              <el-option v-for="(q, key) in qualityLabels" :key="key" :value="key" :label="q.label" />
            </el-select>
          </el-form-item>
          <el-form-item :label="form.kind === 'count' ? '实盘数量（件）' : '数量（件）'">
            <el-input-number
              v-model="line.quantity"
              :precision="0"
              :min="form.kind === 'adjustment' ? -2147483647 : form.kind === 'count' ? 0 : 1"
              :max="2147483647"
            />
          </el-form-item>
        </div>
        <p v-if="form.kind === 'count'">
          {{ line.expected_version === null ? '尚未读取当前库存' : `已读取：在手 ${line.observed ?? 0} 件，版本 ${line.expected_version}` }}
        </p>
        <GlassButton
          v-if="form.lines.length > 1"
          variant="link"
          link-tone="danger"
          left-icon="Delete"
          :disabled="saving || reading"
          @click="form.lines.splice(index, 1)"
        >
          移除此行
        </GlassButton>
      </fieldset>
    </el-form>
    <ListPageStatus
      :error="warehouses.errorMessage.value"
      :has-data="warehouses.hasData.value"
      @retry="warehouses.load()"
    />
    <div class="action-bar">
      <GlassButton
        left-icon="Plus"
        :disabled="saving || reading || form.lines.length >= 200"
        @click="form.lines.push(newLine())"
      >
        新增明细
      </GlassButton>
      <GlassButton
        v-if="form.kind === 'count'"
        left-icon="Refresh"
        :loading="reading"
        :disabled="saving"
        @click="readVersions"
      >
        读取盘点库存
      </GlassButton>
    </div>
    <el-alert v-if="failure" :title="failure" type="error" :closable="false" show-icon />
    <template #footer>
      <div class="dialog-footer">
        <GlassButton :disabled="saving || reading" @click="$emit('update:modelValue', false)">取消</GlassButton>
        <GlassButton
          v-permission="'inventory:write'"
          variant="primary"
          :loading="saving"
          :disabled="reading"
          @click="save"
        >
          确认过账
        </GlassButton>
      </div>
    </template>
  </el-dialog>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { getWarehouses, getBalances, postDocument } from '@/api/inventory'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { msgSuccess, msgError } from '@/utils/feedback'
import { errorMessage } from '@/utils/errors'
import SkuPicker from './SkuPicker.vue'
import { qualityLabels } from '../labels'
const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue', 'saved'])
let lineId = 0
const newLine = () => ({ key: ++lineId, warehouse_id: null, sku_id: null, quality: 'sellable', quantity: 1, destination_warehouse_id: null, expected_version: null })
const form = ref({ kind: 'receipt', reason: '', source_type: '', source_id: '', lines: [newLine()] })
const saving = ref(false), reading = ref(false), failure = ref(''), formRef = ref()
let requestKey = null
const warehouses = useAsyncResource(async (_, { signal }) => (await getWarehouses({ signal, suppressToast: true })).data, { initialData: [] })
const activeWarehouses = computed(() => warehouses.data.value.filter(w => w.active))
watch(form, () => { requestKey = null; failure.value = '' }, { deep: true, flush: 'sync' })
watch(() => props.modelValue, visible => { if (visible) { form.value = { kind: 'receipt', reason: '', source_type: '', source_id: '', lines: [newLine()] }; warehouses.load() } })
function clearVersions() { form.value.lines.forEach(l => { l.expected_version = null }) }
function validateLines() {
  const seen = new Set()
  for (const line of form.value.lines) {
    if (!line.warehouse_id || !line.sku_id) throw new Error('每行必须选择仓库及 SKU')
    const key = `${line.warehouse_id}:${line.sku_id}:${line.quality}`
    if (seen.has(key)) throw new Error('同一仓库、SKU、质量状态不能重复填写')
    seen.add(key)
    if (!Number.isInteger(line.quantity)) throw new Error('数量必须为整数')
    if (form.value.kind === 'count' ? line.quantity < 0 : form.value.kind === 'adjustment' ? !line.quantity : line.quantity <= 0) throw new Error('请填写有效数量')
    if (form.value.kind === 'transfer' && (!line.destination_warehouse_id || line.destination_warehouse_id === line.warehouse_id)) throw new Error('调拨必须选择不同的目标仓库')
  }
}
async function readVersions() {
  if (reading.value || saving.value) return
  try { validateLines() } catch (error) { msgError(error.message); return }
  reading.value = true
  const snapshot = JSON.stringify(form.value.lines.map(l => [l.key, l.warehouse_id, l.sku_id, l.quality]))
  try {
    const values = await Promise.all(form.value.lines.map(async line => {
      const rows = (await getBalances({ warehouse_id: line.warehouse_id, sku_id: line.sku_id, limit: 200 })).data
      const bucket = rows.find(r => r.quality === line.quality)
      return { key: line.key, expected_version: bucket?.version ?? 0, observed: bucket?.on_hand ?? 0 }
    }))
    if (snapshot !== JSON.stringify(form.value.lines.map(l => [l.key, l.warehouse_id, l.sku_id, l.quality]))) { msgError('明细已修改，请重新读取库存'); return }
    values.forEach(value => Object.assign(form.value.lines.find(l => l.key === value.key), value))
    msgSuccess('读取库存')
  } catch (error) { msgError('读取库存失败，请重试', error) } finally { reading.value = false }
}
async function save() {
  if (saving.value || reading.value) return
  saving.value = true
  if (!await formRef.value.validate().catch(() => false)) { saving.value = false; return }
  try { validateLines(); if (form.value.kind === 'count' && form.value.lines.some(l => l.expected_version === null)) throw new Error('请先读取每行盘点库存') } catch (error) { saving.value = false; msgError(error.message); return }
  saving.value = true; failure.value = ''
  requestKey ||= crypto.randomUUID()
  const body = { idempotency_key: requestKey, kind: form.value.kind, reason: form.value.reason.trim(), source_type: form.value.source_type || null, source_id: form.value.source_id || null, lines: form.value.lines.map(l => ({ warehouse_id: l.warehouse_id, sku_id: l.sku_id, quality: l.quality, quantity: l.quantity, destination_warehouse_id: form.value.kind === 'transfer' ? l.destination_warehouse_id : null, expected_version: form.value.kind === 'count' ? l.expected_version : null })) }
  try { await postDocument(body); msgSuccess('库存过账'); emit('update:modelValue', false); emit('saved') }
  catch (error) { failure.value = `${errorMessage(error)}。未修改内容时重试会沿用同一请求，避免重复过账。`; msgError('库存过账失败', error) }
  finally { saving.value = false }
}
</script>
<style scoped>.field-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; } .stock-line { border: 1px solid var(--border-color); border-radius: 8px; padding: 16px; margin-bottom: 16px; } .stock-line legend { color: var(--text-secondary); } .field-grid .el-select { width: 100%; }</style>
