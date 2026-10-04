<template>
  <div class="accounts-page">
    <div class="accounts-aurora lg-aurora" aria-hidden="true"><div class="lg-aurora__blob lg-aurora__blob--gold" /><div class="lg-aurora__blob lg-aurora__blob--amber" /><div class="lg-aurora__blob lg-aurora__blob--peach" /></div>
    <header class="page-header"><div><h2>客户素材门户账号</h2><p>一个客户ID仅允许一个登录邮箱；密码只能设置或重置，不能查看。</p></div></header>
    <div ref="panelRef" class="table-card accounts-panel">
      <FilterBar :pending="search !== submittedSearch" @search="applySearch" @reset="resetFilters">
        <el-input v-model="search" placeholder="客户名称 / ID / 邮箱" clearable class="filter-w-lg" />
      </FilterBar>
      <div class="action-bar">
        <GlassButton variant="primary" left-icon="Plus" @click="openCreate">新建账号</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="load"
          @fullscreen="toggleFullscreen"
        />
      </div>
      <ListPageStatus :error="accountsResource.errorMessage.value" :loading="loading" :has-data="rows.length > 0" @retry="load" />
      <el-table :data="rows" v-loading="loading" class="list-table" :class="densityClass" border :max-height="isFullscreen ? undefined : 640">
        <template #empty>
          <el-empty v-if="!loading && !accountsResource.error.value" :image-size="96" :description="search ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="search" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
        </template>
        <el-table-column v-if="visibleKeys.includes('customer-name')" prop="customer_name" label="客户名称" min-width="190" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('customer-id')" prop="customer_id" label="客户ID" min-width="130" />
        <el-table-column v-if="visibleKeys.includes('login-email')" prop="login_email" label="登录邮箱" min-width="220" show-overflow-tooltip />
        <el-table-column prop="is_active" v-if="visibleKeys.includes('status')" label="状态" min-width="110"><template #default="{ row }"><StatusBadge :value="row.is_active" :dictionary="ENABLED_STATUS" effect="plain" /></template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('last-login')" prop="last_login_at" label="最近登录" min-width="180"><template #default="{ row }">{{ row.last_login_at || '从未登录' }}</template></el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="220" fixed="right"><template #default="{ row }"><GlassButton variant="link" left-icon="Edit" @click="openEdit(row)">修改邮箱/密码</GlassButton><GlassButton left-icon="SwitchButton" variant="link" :link-tone="row.is_active ? 'warning' : 'success'" @click="toggle(row)">{{ row.is_active ? '停用' : '启用' }}</GlassButton></template></el-table-column>
      </el-table>
    </div>
    <el-dialog v-model="dialog" :title="editing ? '修改门户账号' : '新建门户账号'" width="640px">
      <el-form label-position="top">
        <ListPageStatus :error="customersResource.errorMessage.value" :loading="customerLoading" :has-data="customers.length > 0" @retry="customersResource.load()" />
        <el-form-item v-if="!editing" label="客户"><el-select v-model="form.customer_id" filterable remote :remote-method="searchCustomers" :loading="customerLoading" style="width:100%" placeholder="输入客户名称或联系人名称搜索"><el-option v-for="item in customers" :key="item.id" :label="formatCustomerOptionLabel(item)" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="登录邮箱"><el-input v-model="form.login_email" autocomplete="off" /></el-form-item>
        <el-form-item :label="editing ? '重置密码（留空则不修改）' : '初始密码'"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" /><div class="field-hint">至少10位并包含字母和数字；保存后不会再次显示。</div></el-form-item>
      </el-form>
      <template #footer><GlassButton variant="ghost" @click="dialog=false">取消</GlassButton><GlassButton variant="primary" :loading="saving" @click="save">保存</GlassButton></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ENABLED_STATUS } from '@/utils/status'
import { msgWarning, msgSuccessText, confirmAction } from '@/utils/feedback'
import { onMounted, reactive, ref, computed, watch } from 'vue'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useAuthStore } from '@/stores/auth'
import { designActorScope } from './designListScope'

import { createPortalAccount, getPortalAccounts, searchMediaCustomers, updatePortalAccount } from '@/api/customerMedia'
import { formatCustomerOptionLabel } from './appointmentContract'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
const search=ref(''),dialog=ref(false),editing=ref(null),saving=ref(false)
const submittedSearch = ref('')
const accountsResource = useAsyncResource(async (term, { signal }) => (await getPortalAccounts(term, { signal, suppressToast: true })).data || [])
const rows = computed(() => accountsResource.data.value || []); const loading = accountsResource.loading
const customersResource = useAsyncResource(async (term, { signal }) => term ? (await searchMediaCustomers(term, { signal, suppressToast: true })).data || [] : [])
const customers = computed(() => customersResource.data.value || []); const customerLoading = customersResource.loading
const authStore = useAuthStore()
watch(() => designActorScope(authStore), () => { dialog.value = false; accountsResource.load(submittedSearch.value, { clear: true }); customersResource.load('', { clear: true }) }, { flush: 'sync' })
const form=reactive({customer_id:'',login_email:'',password:''})
// 列配置数组：TableTools 列显隐的数据源（操作列不进配置）
const columnDefs=[
  {key:'customer-name',label:'客户名称'},
  {key:'customer-id',label:'客户ID'},
  {key:'login-email',label:'登录邮箱'},
  {key:'status',label:'状态'},
  {key:'last-login',label:'最近登录'},
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('customer-media-accounts', columnDefs)
const load = () => accountsResource.load()
function applySearch() { submittedSearch.value = search.value; return accountsResource.load(submittedSearch.value) }
function resetFilters(){search.value='';return applySearch()}
function openCreate(){customersResource.load('', { clear: true });editing.value=null;Object.assign(form,{customer_id:'',login_email:'',password:''});dialog.value=true}
function openEdit(row){editing.value=row;Object.assign(form,{customer_id:row.customer_id,login_email:row.login_email,password:''});dialog.value=true}
const searchCustomers = term => customersResource.load(term?.trim() || '', { clear: true })
async function save(){if(!form.login_email||(!editing.value&&!form.customer_id)){msgWarning('请完整填写客户和邮箱');return}if(form.password&&(!/[A-Za-z]/.test(form.password)||!/\d/.test(form.password)||form.password.length<10)){msgWarning('密码至少10位并包含字母和数字');return}if(!editing.value&&!form.password){msgWarning('请填写初始密码');return}saving.value=true;try{if(editing.value){const data={login_email:form.login_email};if(form.password)data.password=form.password;await updatePortalAccount(editing.value.id,data)}else await createPortalAccount(form);msgSuccessText('账号已保存');dialog.value=false;await load()}finally{saving.value=false}}
async function toggle(row){try{await confirmAction(`确认${row.is_active?'停用':'启用'} ${row.customer_name} 的门户账号？`,'账号状态',{type:'warning'})}catch{return}await updatePortalAccount(row.id,{is_active:!row.is_active});await load()}
onMounted(() => accountsResource.load(submittedSearch.value))
</script>
<style scoped>
.accounts-page{position:relative}.accounts-aurora{inset:-24px -28px}.page-header,.accounts-panel{position:relative;z-index:1}.page-header{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:18px}.page-header h2{margin:0 0 5px}.page-header p{margin:0;color:var(--text-secondary)}.accounts-panel{background:var(--dash-glass-bg);border:1px solid var(--dash-glass-border);border-radius:var(--dash-card-radius);overflow:hidden}.field-hint{color:var(--text-secondary);font-size:12px;margin-top:5px}
</style>
