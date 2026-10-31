<template>
  <section class="table-card import-panel">
    <h3>选择已核验清单</h3>
    <p class="import-help">支持目录归档、完整订单、资金、历史发货、生产、库存与原领料责任，也支持旧路线责任结清。结清由系统核实原账零余额、履约和全部相关责任已收尾；缺少真实账据时不能放行。</p>
    <div class="action-bar">
      <AppUpload v-if="!command.locked.value" :upload-fn="command.readFile" accept=".json,application/json" :max-size-mb="4" :limit="1" :show-list="false">
        <GlassButton left-icon="FolderOpened">选择核验文件</GlassButton>
      </AppUpload>
      <GlassButton v-else disabled :loading="command.pending.value">{{ command.uncertain.value || command.waiting.value ? '请先核对当前请求结果' : '处理中' }}</GlassButton>
      <span class="file-name">{{ command.fileName.value || '尚未选择文件' }}</span>
      <GlassButton :disabled="command.locked.value || !command.manifest.value" @click="command.clear()">清空</GlassButton>
    </div>
    <el-descriptions v-if="command.manifest.value" :column="1" border>
      <el-descriptions-item label="清单类型">{{ importKinds[command.kind.value] }}</el-descriptions-item>
      <el-descriptions-item label="请求 / 批次身份">{{ command.manifest.value.request_key || command.manifest.value.batch_key || '缺少请求身份' }}</el-descriptions-item>
      <el-descriptions-item v-if="command.kind.value !== 'legacy_settlement'" label="来源 / 账号">{{ command.manifest.value.source }} / {{ command.manifest.value.tenant }}</el-descriptions-item>
      <el-descriptions-item v-if="command.kind.value !== 'legacy_settlement'" label="切换业务日">{{ command.manifest.value.cutover_date }}</el-descriptions-item>
      <el-descriptions-item label="核验依据">{{ command.manifest.value.review_reference }}</el-descriptions-item>
    </el-descriptions>
    <el-alert v-if="command.failure.value" class="import-feedback" :title="command.failure.value" type="error" :closable="false" show-icon />
    <el-alert v-if="command.uncertain.value" class="import-feedback" title="请求结果未确认。当前清单与批次身份已保留，请重试同一请求核对结果后再换文件。" type="warning" :closable="false" show-icon />
    <div class="action-bar">
      <GlassButton :loading="command.pending.value" :disabled="command.locked.value || !command.manifest.value" left-icon="View" @click="command.preview()">预览差异</GlassButton>
      <GlassButton v-permission="'commerce_migration:admin'" variant="primary" left-icon="Check" :loading="command.pending.value" :disabled="!command.canApply.value" @click="apply">
        {{ command.waiting.value ? '核对当前承接请求' : command.uncertain.value ? '重试当前承接请求' : command.kind.value === 'legacy_settlement' ? '核验并结清原责任' : '承接此清单' }}
      </GlassButton>
    </div>
    <template v-if="command.report.value">
      <el-alert class="import-feedback" :title="command.report.value.can_apply ? '核验通过，可承接此清单' : `存在${command.report.value.conflicts.length}项差异，请修正核验清单后重新预览`" :type="command.report.value.can_apply ? 'success' : 'warning'" :closable="false" show-icon />
      <el-table v-if="command.report.value.conflicts.length" :data="command.report.value.conflicts" border class="list-table import-feedback" v-sticky-scrollbar>
        <el-table-column label="记录位置" min-width="130"><template #default="{ row }">{{ sectionLabel(row.section) }}{{ row.record_index == null ? '' : ` 第${row.record_index + 1}条` }}</template></el-table-column>
        <el-table-column prop="message" label="需要核对" min-width="280" />
      </el-table>
    </template>
    <template v-if="command.result.value">
      <el-alert v-if="command.waiting.value" class="import-feedback" :title="`原责任已冻结，等待核对（任务 ${command.result.value.handover_preparation_id}）。尚未完成承接，请核对原请求。${command.result.value.message || ''}`" type="warning" :closable="false" show-icon />
      <el-alert v-else class="import-feedback" :title="command.kind.value === 'legacy_settlement' ? '旧路线责任已由系统核验结清，原账与证据保留。' : '此批次已承接。历史责任请在已承接记录中核对；完整订单和生产须放行后才能继续办理。'" type="success" :closable="false" show-icon />
      <div class="action-bar"><GlassButton left-icon="Download" @click="downloadResult">下载承接结果</GlassButton></div>
      <el-table :data="resultRows" border class="list-table import-feedback" v-sticky-scrollbar>
        <el-table-column prop="kind" label="责任类型" min-width="150" />
        <el-table-column prop="record_id" label="来源记录" min-width="110" />
        <el-table-column prop="target" label="本地关联" min-width="210" />
      </el-table>
    </template>
  </section>
</template>
<script setup>
import { computed, onActivated, onDeactivated } from 'vue'
import AppUpload from '@/components/AppUpload.vue'
import { previewMigration, applyMigration } from '@/api/commerceMigration'
import { useMigrationImport } from './useMigrationImport'
import { importKinds } from './labels'
import { downloadBlob } from '@/utils/download'
import { msgSuccess } from '@/utils/feedback'
const emit = defineEmits(['applied'])
const command = useMigrationImport({ preview: previewMigration, apply: applyMigration })
let generation = 0
onActivated(() => { generation++ })
onDeactivated(() => { generation++ })
const sectionLabel = value => ({ batch: '批次', catalog: '目录', archives: '归档', stocks: '成品库存', materials: '半成品',
  orders: '订单', payments: '付款', productions: '生产', receivables: '应收', allocations: '领料', resolutions: '原未决物料处置' }[value] || value || '整份清单')
const resultRows = computed(() => Object.entries(command.result.value || {}).flatMap(([section, rows]) => Array.isArray(rows) ? rows.map(row => ({
  kind: sectionLabel(section), record_id: row.record_id,
  target: [row.invoice_id && `订单 ${row.invoice_id}`, row.sku_id && `SKU ${row.sku_id}`, row.batch_id && `付款 ${row.batch_id}`,
    row.production_order_id && `生产 ${row.production_order_id}`, row.order_id && `生产 ${row.order_id}`,
    row.allocation_id && `领料 ${row.allocation_id}`].filter(Boolean).join(' / ') || '已保存核验依据',
})) : []))
async function apply() { const current=generation; if (await command.apply() && current===generation) { msgSuccess(command.kind.value === 'legacy_settlement' ? '原责任核验结清' : '承接清单'); emit('applied') } }
function downloadResult() {
  downloadBlob({ data: new Blob([JSON.stringify(command.result.value, null, 2)], { type: 'application/json' }) }, `${command.manifest.value.request_key || command.manifest.value.batch_key}.json`)
}
</script>
<style scoped>
.import-panel { margin-bottom: var(--space-lg, 24px); }
.import-panel h3 { margin-top: 0; }
.import-help { color: var(--text-secondary); line-height: 1.7; }
.file-name { overflow-wrap: anywhere; min-width: 0; color: var(--text-secondary); }
.import-feedback { margin-top: var(--space-md, 16px); }
</style>
