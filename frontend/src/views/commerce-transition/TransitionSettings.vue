<template>
  <div>
    <div class="page-header"><h2>交易试点配置</h2></div>
    <ListPageStatus :error="status.errorMessage.value" :loading="status.loading.value" :has-data="status.hasData.value" :paged="false" @retry="refresh" />
    <ResponsiveDescriptions v-if="status.data.value" :column="3" border><el-descriptions-item label="平台阶段">{{ phaseLabels[status.data.value.phase] }}</el-descriptions-item><el-descriptions-item label="配置版本">{{ status.data.value.version }}</el-descriptions-item><el-descriptions-item label="新增独立订单">{{ status.data.value.capabilities?.local_new_orders ? '可按范围办理' : '未放行' }}</el-descriptions-item></ResponsiveDescriptions>
    <el-alert v-for="blocker in status.data.value?.readiness?.blockers || []" :key="blocker" :title="blocker" type="warning" :closable="false" />
    <div class="table-card">
      <div class="action-bar"><GlassButton v-if="canEdit" left-icon="Setting" :disabled="command.pending.value" @click="openEdit">{{ tab === 'bank-identities' ? '核对旧款流水' : '登记核验' }}</GlassButton><GlassButton left-icon="Refresh" @click="refresh">刷新读回</GlassButton></div>
      <el-tabs v-model="tab" @tab-change="changeTab"><el-tab-pane v-for="entry in tabs" :key="entry.key" :label="entry.label" :name="entry.key" :disabled="command.pending.value" /></el-tabs>
      <el-alert v-if="tab === 'bank-identities'" title="这里只核对旧款与真实银行流水的对应关系，不增加本金。完整批次须整体核对；核对仍受后端权限和金额检查。" type="info" :closable="false" />
      <el-alert v-if="tab === 'bank-identities' && unmapped.length" :title="`尚有 ${unmapped.length} 笔旧款 / 完整批次待核对`" type="warning" :closable="false" />
      <ListPageStatus :error="errorMessage" :loading="loading" :has-data="hasData" :paged="false" @retry="fetchList" />
      <el-table :data="list" v-loading="loading" border class="list-table" v-sticky-scrollbar><el-table-column v-for="field in columns" :key="field.key" :prop="field.key" :label="field.label" min-width="145" show-overflow-tooltip /><el-table-column class-name="table-action-column" label="操作" min-width="80"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="selected = row; detailOpen = true">依据</GlassButton></template></el-table-column></el-table>
    </div>
    <DetailDrawer v-model="detailOpen" title="核验依据" width="640px"><pre>{{ display(selected) }}</pre></DetailDrawer>
    <el-dialog v-model="editOpen" :title="editTab === 'bank-identities' ? '核对旧款真实银行流水' : '登记试点核验'" width="640px" :show-close="!command.pending.value" :close-on-click-modal="!command.pending.value">
      <ListPageStatus :error="choices.errorMessage.value" :loading="choices.loading.value" :has-data="choices.hasData.value" :paged="false" @retry="choices.load()" />
      <el-form label-position="top" :disabled="command.pending.value || choices.loading.value">
        <template v-if="editTab === 'bank-identities'">
          <el-form-item label="原旧款 / 完整批次"><el-select v-model="form.source" filterable><el-option v-for="source in unmapped" :key="source" :value="source" :label="sourceLabel(source)" /></el-select></el-form-item>
          <el-form-item label="已核验账户域"><el-select v-model="form.domain_id" filterable><el-option v-for="domain in choices.data.value?.domains || []" :key="domain.id" :value="domain.id" :label="`${domain.subject_key} / ${domain.account_key} / ${domain.channel}`" /></el-select></el-form-item>
          <el-form-item label="真实银行流水号"><el-input v-model="form.transaction_id" maxlength="128" /></el-form-item>
          <el-form-item label="银行对账依据"><el-input v-model="form.statement_reference" type="textarea" maxlength="500" show-word-limit /></el-form-item>
        </template>
        <el-form-item v-for="field in editFields" :key="field.key" :label="field.label">
          <el-select v-if="field.type === 'accounts'" v-model="form[field.key]" multiple filterable><el-option v-for="account in choices.data.value?.accounts || []" :key="account.id" :value="account.id" :label="`${account.name} / ${account.currency}（ID ${account.id}，${account.code}${account.active ? '' : '，停用'}）`" /></el-select>
          <el-select v-else-if="field.options" v-model="form[field.key]" :clearable="field.optional"><el-option v-for="option in field.options" :key="option.value" :value="option.value" :label="option.label" /></el-select>
          <el-switch v-else-if="field.type === 'boolean'" v-model="form[field.key]" />
          <el-input-number v-else-if="field.type === 'number'" v-model="form[field.key]" :min="1" :precision="0" />
          <el-input v-else v-model="form[field.key]" maxlength="128" />
        </el-form-item>
        <el-form-item v-if="editTab !== 'bank-identities'" label="核验记录 / 事实依据"><el-input v-model="evidence" type="textarea" maxlength="3000" /></el-form-item>
        <el-alert v-if="editTab === 'bank-domains'" title="请选择同一真实银行账户的全部 ID 别名。账户名称或编码修改不会改变物理域归属。" type="info" :closable="false" />
      </el-form>
      <el-alert v-if="command.failure.value" :title="command.failure.value" type="error" :closable="false" />
      <template #footer><GlassButton :disabled="command.pending.value" @click="editOpen = false">返回</GlassButton><GlassButton v-if="canEdit" variant="primary" :loading="command.pending.value" :disabled="choices.loading.value || !!choices.error.value" @click="save">保存核验</GlassButton></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { computed, onActivated, onDeactivated, ref } from 'vue'
import { getTransitionStatus, getTransitionResource, saveTransitionResource } from '@/api/commerceTransition'
import { getFinanceReference } from '@/api/nativeFinance'
import { useAuthStore } from '@/stores/auth'
import { bankDomainAccounts, legacyBankReconciliationPayload } from './transitionBank'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useNativeCommand } from '@/views/finance/native/useNativeCommand'
import { msgSuccess, confirmAction } from '@/utils/feedback'
import DetailDrawer from '@/components/DetailDrawer.vue'
const tab = ref('policy'), appliedTab = ref('policy'), editTab = ref('policy'), unmapped = ref([])
const auth = useAuthStore()
const canEdit = computed(() => auth.hasPermission('commerce_transition:admin') && (tab.value !== 'bank-identities' || auth.hasPermission('receipt:admin')))
const status = useAsyncResource(async (_, { signal }) => (await getTransitionStatus({ signal, suppressToast: true })).data)
const state = useListPage(async (_, { signal, isCurrent }) => {
  const resource = appliedTab.value
  const data = resource === 'policy' ? status.data.value ? [status.data.value] : [] : (await getTransitionResource(resource, { signal, suppressToast: true })).data
  const items = resource === 'bank-identities' ? data.items : resource === 'bank-domains'
    ? data.map(row=>({...row,bank_account_ids:row.evidence?.bank_account_ids || []})) : data
  if (isCurrent()) unmapped.value = resource === 'bank-identities' ? data.unmapped_legacy_money || [] : []
  return { items, total: items.length }
}, { immediate: false })
const choices = useAsyncResource(async (_, { signal }) => editTab.value === 'bank-domains'
  ? { accounts: (await getFinanceReference({ signal, suppressToast: true })).data.accounts }
  : editTab.value === 'bank-identities' ? { domains: (await getTransitionResource('bank-domains', { signal, suppressToast: true })).data } : {})
const { list, loading, errorMessage, hasData, fetchList } = state
const phaseLabels = { legacy_only: '仅小满流程', transition: '双路线过渡', local_only: '仅方舟独立' }
const routes = [{value:'legacy',label:'小满流程'},{value:'local',label:'方舟独立'}]
const tabs = [{key:'policy',label:'平台阶段'},{key:'writers',label:'交易 writer'},{key:'resources',label:'排他实物范围'},{key:'bank-domains',label:'收款账户域'},{key:'bank-identities',label:'旧款流水核对'}]
const fields = {
 policy: [{key:'phase',label:'平台阶段',options:Object.entries(phaseLabels).map(([value,label])=>({value,label}))},{key:'min_writer_version',label:'最小 writer 协议版本',type:'number'}],
 writers: [{key:'writer_key',label:'Writer 标识'},{key:'protocol_version',label:'协议版本',type:'number'},{key:'state',label:'核验状态',options:[{value:'unknown',label:'待核验'},{value:'compatible',label:'已兼容'},{value:'revoked',label:'已撤权'}]}],
 resources: [{key:'route',label:'独占路线',options:routes},{key:'resource_kind',label:'责任类型',options:[{value:'sku',label:'成品 SKU'},{value:'material',label:'物料'},{value:'production',label:'生产责任'}]},{key:'resource_key',label:'实物身份标识'},{key:'warehouse_key',label:'真实仓库 / 库存桶'},{key:'checkpoint',label:'一致盘点检查点'},{key:'old_responsibilities_cleared',label:'已核清并冻结旧在途责任',type:'boolean'},{key:'writers_enforced',label:'全部 writer 已落实排他约束',type:'boolean'}],
 'bank-domains': [{key:'subject_key',label:'收款主体标识'},{key:'account_key',label:'收款账户标识'},{key:'channel',label:'渠道'},{key:'bank_account_ids',label:'同一真实账户的银行账户 ID 别名',type:'accounts'},{key:'exclusive_route',label:'排他路线',options:routes,optional:true},{key:'legacy_identity_complete',label:'整个账户域旧款身份已核清',type:'boolean'},{key:'enforced',label:'新增登记及旧入口已强制受控',type:'boolean'}],
 'bank-identities': []
}
const editFields = computed(()=>fields[editTab.value]), columns = computed(()=>tab.value === 'bank-identities' ? [
 {key:'domain_id',label:'账户域 ID'},{key:'transaction_id',label:'银行流水号'},{key:'payment_ref',label:'原账本身份'},
 {key:'route',label:'办理路线'},{key:'currency',label:'币种'},{key:'amount',label:'原本金'}
] : fields[tab.value].filter(f=>!['checkpoint','old_responsibilities_cleared','writers_enforced'].includes(f.key)))
async function refresh() { const current=generation; await status.load(); if(current===generation) await fetchList() }
function changeTab() { appliedTab.value = tab.value; state.list.value = []; unmapped.value=[]; editOpen.value=false; choices.clear(); fetchList() }
let generation = 0
onActivated(()=>{generation++;refresh()})
const selected = ref(null), detailOpen = ref(false), editOpen = ref(false), form = ref({}), evidence = ref(''), command = useNativeCommand()
const display = value => JSON.stringify(value, null, 2)
function openEdit() {
 if(!canEdit.value) return
 editTab.value=tab.value
 form.value = Object.fromEntries(editFields.value.map(f=>[f.key,f.type==='accounts'?[]:f.type==='boolean'?false:f.type==='number'?1:f.options?.[0]?.value || '']))
 if(tab.value==='policy') Object.assign(form.value,{phase:status.data.value?.phase,expected_version:status.data.value?.version,min_writer_version:status.data.value?.min_writer_version || 1})
 if(editTab.value==='bank-identities') form.value={source:'',domain_id:null,transaction_id:'',statement_reference:''}
 evidence.value=''; command.reset(); choices.clear(); editOpen.value=true; choices.load()
}
const sourceLabel = source => source.replace('legacy-receipt:', '旧回款 #').replace('legacy-batch:', '完整旧批次 #')
async function save() {
 const resource=editTab.value, current=generation
 const result=await command.run({payload:()=>{
  if(!canEdit.value) throw new Error('当前账号无此核验权限')
  if(resource==='bank-identities') return legacyBankReconciliationPayload(form.value,unmapped.value,choices.data.value?.domains || [])
  if(!evidence.value.trim()) throw new Error('请填写核验记录和事实依据')
  for(const f of editFields.value) if(!f.optional && f.type!=='boolean' && !form.value[f.key]) throw new Error(`请填写${f.label}`)
  const body={...form.value},proof={reference:evidence.value.trim()}
  if(resource==='policy') {if(!body.expected_version) throw new Error('请先刷新配置版本');body.inventory_evidence=proof}
  else if(resource==='resources') {if(!body.old_responsibilities_cleared || !body.writers_enforced) throw new Error('全部排他核验完成后才能登记');body.evidence={...proof,checkpoint:body.checkpoint,old_responsibilities_cleared:body.old_responsibilities_cleared,writers_enforced:body.writers_enforced};delete body.checkpoint;delete body.old_responsibilities_cleared;delete body.writers_enforced}
  else body.evidence=proof
  if(resource==='bank-domains') {body.exclusive_route=body.exclusive_route || null;body.bank_account_ids=bankDomainAccounts(body.bank_account_ids,choices.data.value?.accounts || [])}
  return body
 },confirm:()=>confirmAction(resource==='bank-identities'?'将把所选旧款与真实银行流水关联；不会增加本金。':'将保存当前核验事实，后端继续检查阶段、版本与责任边界。','保存试点配置'),send:body=>{if(current!==generation) throw new Error('页面已切换，请返回后重新核对');const {request_key,...payload}=body;return saveTransitionResource(resource==='bank-identities'?'bank-identities/reconcile-legacy':resource,payload)}})
 if(result.ok && current===generation){msgSuccess(resource==='bank-identities'?'旧款流水核对已保存':'保存试点核验');editOpen.value=false;await refresh()}
}
onDeactivated(()=>{generation++;editOpen.value=false;detailOpen.value=false;state.cancel();status.cancel();choices.cancel()})
</script>
<style scoped>pre {white-space:pre-wrap;overflow-wrap:anywhere;color:var(--text-secondary);font-size:12px}.el-alert {margin-bottom:12px}</style>
