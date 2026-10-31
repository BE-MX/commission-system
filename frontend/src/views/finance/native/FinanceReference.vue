<template>
  <div>
    <div class="page-header"><h2>本地财务基础资料</h2><p>维护币种、收款账户和关账截止日。已登记的付款保留当时的汇率快照。</p></div>
    <div class="table-card">
      <div class="action-bar"><GlassButton left-icon="Refresh" :loading="resource.loading.value" @click="resource.load()">刷新资料</GlassButton><GlassButton v-permission="'receipt:admin'" :disabled="!resource.data.value || !!resource.error.value || resource.loading.value" left-icon="Lock" @click="closeOpen = true">关账</GlassButton><span>当前关账截止日：{{ resource.data.value?.closed_through ? formatBeijingDate(resource.data.value.closed_through) : '尚未关账' }}</span></div>
      <ListPageStatus :error="resource.errorMessage.value" :loading="resource.loading.value" :has-data="resource.hasData.value" :paged="false" @retry="resource.load()" />
      <h3>币种与汇率</h3><div class="action-bar"><GlassButton v-permission="'receipt:admin'" variant="primary" left-icon="Plus" @click="edit('currency')">新增币种</GlassButton></div>
      <el-table :data="resource.data.value?.currencies || []" border class="list-table" v-sticky-scrollbar><el-table-column prop="code" label="币种代码" min-width="100"/><el-table-column prop="name" label="名称" min-width="140"/><el-table-column prop="rate_to_cny" label="1 单位折人民币" min-width="150"/><el-table-column label="状态" min-width="100"><template #default="{ row }">{{ row.active ? '启用' : '停用' }}</template></el-table-column><el-table-column label="操作" min-width="100" class-name="table-action-column"><template #default="{ row }"><GlassButton v-permission="'receipt:admin'" variant="link" left-icon="Edit" :disabled="!!resource.error.value || resource.loading.value" @click="edit('currency', row)">编辑</GlassButton></template></el-table-column></el-table>
      <h3>收款账户</h3><div class="action-bar"><GlassButton v-permission="'receipt:admin'" variant="primary" left-icon="Plus" @click="edit('account')">新增账户</GlassButton></div>
      <el-table :data="resource.data.value?.accounts || []" border class="list-table" v-sticky-scrollbar><el-table-column prop="code" label="账户代码" min-width="140"/><el-table-column prop="name" label="账户名称" min-width="180"/><el-table-column prop="currency" label="币种" min-width="90"/><el-table-column label="状态" min-width="100"><template #default="{ row }">{{ row.active ? '启用' : '停用' }}</template></el-table-column><el-table-column label="操作" min-width="100" class-name="table-action-column"><template #default="{ row }"><GlassButton v-permission="'receipt:admin'" variant="link" left-icon="Edit" :disabled="!!resource.error.value || resource.loading.value" @click="edit('account', row)">编辑</GlassButton></template></el-table-column></el-table>
    </div>
    <el-dialog v-model="editorOpen" :title="`${existing ? '编辑' : '新增'}${kind === 'currency' ? '币种' : '收款账户'}`" width="480px" :show-close="!command.pending.value" :close-on-click-modal="!command.pending.value" :close-on-press-escape="!command.pending.value">
      <el-form label-position="top" :disabled="command.pending.value"><el-form-item label="代码（保存后不可修改）"><el-input v-model="form.code" :disabled="existing" :maxlength="kind === 'currency' ? 16 : 64" /></el-form-item><el-form-item label="名称"><el-input v-model="form.name" :maxlength="kind === 'currency' ? 64 : 128" /></el-form-item><el-form-item v-if="kind === 'currency'" label="1 单位折人民币（最多 8 位小数）"><el-input v-model="form.rate_to_cny" inputmode="decimal" /></el-form-item><el-form-item v-else label="账户币种"><el-select v-model="form.currency"><el-option v-for="row in resource.data.value?.currencies || []" :key="row.code" :value="row.code" :label="`${row.code} · ${row.name}`" /></el-select></el-form-item><el-form-item label="启用"><el-switch v-model="form.active" /></el-form-item></el-form>
      <el-alert v-if="command.failure.value" type="error" :title="command.failure.value" :closable="false" show-icon />
      <template #footer><div class="dialog-footer"><GlassButton :disabled="command.pending.value" @click="editorOpen = false">返回</GlassButton><GlassButton v-permission="'receipt:admin'" variant="primary" :loading="command.pending.value" @click="save">保存</GlassButton></div></template>
    </el-dialog>
    <FinanceActionDialog v-model="closeOpen" operation="close" :target="{ version: resource.data.value?.book_version, label: '本地财务账簿' }" @saved="resource.load()" />
  </div>
</template>
<script setup>
import { onDeactivated, ref, watch } from 'vue'
import { getFinanceReference, writeCurrency, writeBankAccount } from '@/api/nativeFinance'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { formatBeijingDate } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import { useNativeCommand } from './useNativeCommand'
import { requireAmount } from './decimal'
import FinanceActionDialog from './components/FinanceActionDialog.vue'
const resource = useAsyncResource(async (_, { signal }) => (await getFinanceReference({ signal, suppressToast: true })).data)
const command = useNativeCommand(), editorOpen = ref(false), closeOpen = ref(false), kind = ref('currency'), existing = ref(false), form = ref({})
onDeactivated(() => { editorOpen.value = false; closeOpen.value = false })
watch(form, command.reset, { deep: true, flush: 'sync' })
function edit(type, row) { kind.value = type; existing.value = !!row; form.value = row ? { ...row } : { code: '', name: '', currency: '', rate_to_cny: '', active: true }; command.reset(); editorOpen.value = true }
async function save() {
  const result = await command.run({ payload: () => {
    const row = form.value
    if (!row.code.trim() || !row.name.trim()) throw new Error('请填写代码和名称')
    const body = { code: row.code.trim(), name: row.name.trim(), active: row.active }
    if (kind.value === 'currency') { if (!/^[A-Z]{3}$/.test(body.code)) throw new Error('币种代码应为 3 位大写字母'); body.rate_to_cny = requireAmount(row.rate_to_cny, '汇率', { precision: 8, maxIntegerDigits: 10, allowZero: false }) }
    else { if (!row.currency) throw new Error('请选择账户币种'); body.currency = row.currency }
    return body
  }, send: body => (kind.value === 'currency' ? writeCurrency : writeBankAccount)(body) })
  if (result.ok) { msgSuccess('保存财务资料'); editorOpen.value = false; await resource.load() }
}
resource.load()
</script>
<style scoped>h3 { margin: var(--space-5) 0 var(--space-3); }</style>
