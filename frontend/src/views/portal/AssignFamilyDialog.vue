<script setup>
import { ref } from 'vue'
import { portalAdminApi } from '@/api/portal'
import { msgSuccessText } from '@/utils/feedback'
import { assignBody, gradeLabels } from './familyConfiguration.mjs'
const props = defineProps({ items: { type: Array, required: true }, families: { type: Array, required: true } })
const emit = defineEmits(['close', 'changed'])
const form = ref({ family_code: '', grade: 'super', clear: false, reason: '' }), saving = ref(false), error = ref('')
const units = [...new Set(props.items.map(item => item.sale_unit))]
async function save() {
  if (saving.value) return
  let body
  try { body = assignBody({ ...form.value, item_ids: props.items.map(item => item.id) }) } catch (e) { error.value = e.message; return }
  saving.value = true; error.value = ''
  try {
    const result = await portalAdminApi.assignCatalogFamily(body)
    msgSuccessText(`已处理 ${result.assigned} 个商品，影响 ${result.affected_customers} 个客户`); emit('changed'); emit('close')
  } catch (e) { error.value = e?.response?.data?.message || '归类失败，请刷新后重试。' }
  finally { saving.value = false }
}
</script>

<template>
  <el-dialog :model-value="true" :title="`归入产品族（${items.length} 个商品）`" width="640px" class="portal-assign-dialog" :close-on-click-modal="false" @update:model-value="v => { if (!v && !saving) emit('close') }">
    <el-alert title="商品会继承产品族的起订量、步长和无货阈值；销售单位必须与产品族一致，否则整批不生效。" type="info" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <p class="units">所选商品销售单位：{{ units.join('、') }}</p>
    <el-form label-position="top" :disabled="saving">
      <el-form-item><el-checkbox v-model="form.clear">移出产品族（保留商品当前规则）</el-checkbox></el-form-item>
      <template v-if="!form.clear">
        <el-form-item label="产品族"><el-select v-model="form.family_code" placeholder="选择产品族" aria-label="产品族"><el-option v-for="family in families" :key="family.code" :label="`${family.display_name}（${family.sale_unit}）`" :value="family.code" /></el-select></el-form-item>
        <el-form-item label="工艺档"><el-radio-group v-model="form.grade"><el-radio v-for="(label, grade) in gradeLabels" :key="grade" :value="grade">{{ label }}</el-radio></el-radio-group></el-form-item>
      </template>
      <el-form-item label="操作原因"><el-input v-model="form.reason" maxlength="500" /></el-form-item>
    </el-form>
    <template #footer><GlassButton :disabled="saving" @click="emit('close')">取消</GlassButton><GlassButton v-permission="'portal_site:admin'" variant="primary" :disabled="saving" @click="save">确认</GlassButton></template>
  </el-dialog>
</template>

<style scoped>.el-alert { margin-bottom: 12px; } .units { color: var(--text-secondary); } .el-select { width: 100%; } .el-radio-group { display: flex; flex-wrap: wrap; }</style>
<style>.portal-assign-dialog { max-width: calc(100vw - 24px); }</style>
