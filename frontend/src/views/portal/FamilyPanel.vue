<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Edit, MagicStick, Refresh } from '@element-plus/icons-vue'
import { portalAdminApi } from '@/api/portal'
import { isFeedbackCancelled, msgSuccessText, promptAction } from '@/utils/feedback'
import { statusDictionary } from '@/utils/status'
import { familyBody, gradeLabels, packHint } from './familyConfiguration.mjs'
const ENABLED_STATE = statusDictionary([['enabled', '启用', 'success'], ['disabled', '停用', 'info']])
const emit = defineEmits(['changed'])
const families = ref([]), loading = ref(false), error = ref(''), editing = ref(null), form = ref(null), saving = ref(false)
let controller
const message = e => e?.response?.data?.message || e?.message || '产品族操作失败，请刷新后重试。'
async function load() {
  controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''
  try { families.value = (await portalAdminApi.catalogFamilies(controller.signal)).items }
  catch (e) { if (e?.name !== 'CanceledError') error.value = message(e) }
  finally { loading.value = false }
}
async function seed() {
  try {
    const { value } = await promptAction('将创建缺失的默认产品族（已存在的不会被覆盖）。请填写操作原因：', '初始化产品族', { inputValidator: v => !!v?.trim() || '请填写原因' })
    const result = await portalAdminApi.seedCatalogFamilies(value.trim())
    families.value = result.items
    msgSuccessText(result.created.length ? `已创建 ${result.created.length} 个产品族` : '默认产品族均已存在')
  } catch (e) { if (!isFeedbackCancelled(e)) error.value = message(e) }
}
function edit(row) {
  editing.value = row
  form.value = { display_name: row.display_name, unit_weight_grams: row.unit_weight_grams, min_qty: row.min_qty, step_qty: row.step_qty,
    out_of_stock_below: row.out_of_stock_below, allowed_grades: [...row.allowed_grades], sort_order: row.sort_order, status: row.status, reason: '' }
}
async function save() {
  if (saving.value) return
  let body
  try { body = familyBody(form.value) } catch (e) { error.value = e.message; return }
  saving.value = true; error.value = ''
  try {
    const result = await portalAdminApi.updateCatalogFamily(editing.value.code, body, editing.value.row_version)
    msgSuccessText(`已保存；同步 ${result.updated_items} 个商品，影响 ${result.affected_customers} 个客户`)
    editing.value = null; emit('changed'); await load()
  } catch (e) { error.value = message(e) }
  finally { saving.value = false }
}
const total = (row, key) => Object.values(row.item_counts).reduce((sum, entry) => sum + entry[key], 0)
onMounted(load)
onBeforeUnmount(() => controller?.abort())
defineExpose({ load })
</script>

<template>
  <div class="tab-body">
    <div class="action-bar">
      <GlassButton v-permission="'portal_site:admin'" variant="primary" :left-icon="MagicStick" @click="seed">初始化默认产品族</GlassButton>
      <span class="action-hint">产品族决定客户目录分组、起订量/步长和无货阈值；归入产品族的商品自动继承这些规则。</span>
      <GlassButton variant="ghost" :left-icon="Refresh" :loading="loading" class="refresh" @click="load">刷新</GlassButton>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="panel-alert" />
    <el-table v-loading="loading" :data="families" border class="list-table" v-sticky-scrollbar><template #empty><el-empty v-if="!loading" :image-size="96" description="暂无产品族；点击「初始化默认产品族」创建默认产品族" /></template>
      <el-table-column prop="display_name" label="产品族" min-width="180" max-width="280" show-overflow-tooltip />
      <el-table-column label="起订 / 步长" min-width="180" max-width="280" :sort-by="row => row.min_qty"><template #default="{ row }">{{ row.min_qty }} / {{ row.step_qty }} {{ row.sale_unit }}<span class="cell-hint">{{ packHint(row) }}</span></template></el-table-column>
      <el-table-column label="无货阈值" min-width="110" max-width="160" :sort-by="row => Number(row.out_of_stock_below)"><template #default="{ row }">&lt; {{ +row.out_of_stock_below }} {{ row.sale_unit }}</template></el-table-column>
      <el-table-column label="展示工艺档" min-width="180" max-width="280" :sort-by="row => row.allowed_grades.length" show-overflow-tooltip><template #default="{ row }">{{ row.allowed_grades.map(g => gradeLabels[g]).join('、') }}</template></el-table-column>
      <el-table-column label="商品（已发布/全部）" min-width="150" max-width="200" :sort-by="row => total(row, 'published')"><template #default="{ row }">{{ total(row, 'published') }} / {{ total(row, 'total') }}</template></el-table-column>
      <el-table-column prop="status" label="状态" min-width="100" max-width="140"><template #default="{ row }"><StatusBadge :value="row.status" :dictionary="ENABLED_STATE" effect="plain" /></template></el-table-column>
      <el-table-column label="操作" min-width="100" max-width="140" fixed="right" class-name="table-action-column" :sortable="false"><template #default="{ row }"><GlassButton v-permission="'portal_site:admin'" variant="link" :left-icon="Edit" @click="edit(row)">编辑</GlassButton></template></el-table-column>
    </el-table>
    <el-dialog v-if="editing" :model-value="true" :title="`编辑产品族 · ${editing.display_name}`" width="640px" class="portal-family-dialog" :close-on-click-modal="false" @update:model-value="v => { if (!v && !saving) editing = null }">
      <el-alert title="保存后，该产品族下所有商品的起订量、步长和无货阈值会同步更新，相关客户的未提交报价将失效。" type="info" :closable="false" />
      <el-form label-position="top" :disabled="saving" class="dialog-form">
        <el-form-item label="客户可见名称"><el-input v-model="form.display_name" maxlength="128" /></el-form-item>
        <div class="grid">
          <el-form-item :label="`单位克重（g / ${editing.sale_unit}）`"><el-input v-model="form.unit_weight_grams" /></el-form-item>
          <el-form-item :label="`无货阈值（${editing.sale_unit}）`"><el-input v-model="form.out_of_stock_below" /></el-form-item>
          <el-form-item label="起订量"><el-input-number v-model="form.min_qty" :min="1" :max="10000" /></el-form-item>
          <el-form-item label="步长"><el-input-number v-model="form.step_qty" :min="1" :max="10000" /></el-form-item>
          <el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="0" :max="9999" /></el-form-item>
          <el-form-item label="状态"><el-radio-group v-model="form.status"><el-radio value="enabled">启用</el-radio><el-radio value="disabled">停用</el-radio></el-radio-group></el-form-item>
        </div>
        <el-form-item label="向客户展示的工艺档"><el-checkbox-group v-model="form.allowed_grades"><el-checkbox v-for="(label, grade) in gradeLabels" :key="grade" :value="grade">{{ label }}</el-checkbox></el-checkbox-group></el-form-item>
        <el-form-item label="操作原因" required><el-input v-model="form.reason" maxlength="500" /></el-form-item>
      </el-form>
      <template #footer><div class="dialog-footer"><GlassButton variant="ghost" :disabled="saving" @click="editing = null">取消</GlassButton><GlassButton v-permission="'portal_site:admin'" variant="primary" :loading="saving" @click="save">保存</GlassButton></div></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.action-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 14px; border-bottom: 1px solid var(--border-color); background: rgba(255, 255, 255, 0.28); }
.action-hint { flex: 1; min-width: 220px; color: var(--text-secondary); font-size: 13px; }
.refresh { margin-left: auto; }
.panel-alert { margin: 12px 14px 0; width: auto; }
.cell-hint { display: block; color: var(--text-secondary); font-size: 12px; }
.dialog-form { margin-top: 14px; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
@media (max-width: 600px) { .grid { grid-template-columns: 1fr; } }
</style>
<style>.portal-family-dialog { max-width: calc(100vw - 24px); }</style>
