<template>
  <div class="accounts-page">
    <div class="accounts-aurora lg-aurora" aria-hidden="true"><div class="lg-aurora__blob lg-aurora__blob--gold" /><div class="lg-aurora__blob lg-aurora__blob--amber" /><div class="lg-aurora__blob lg-aurora__blob--peach" /></div>
    <header class="page-header"><div><h2>客户素材门户账号</h2><p>一个客户ID仅允许一个登录邮箱；密码只能设置或重置，不能查看。</p></div><GlassButton variant="primary" left-icon="Plus" @click="openCreate">新建账号</GlassButton></header>
    <div class="toolbar"><el-input v-model="search" placeholder="客户名称 / ID / 邮箱" clearable @keyup.enter="load" @clear="load" /><GlassButton left-icon="Search" @click="load">查询</GlassButton></div>
    <div class="table-card accounts-panel"><el-table :data="rows" v-loading="loading" class="list-table" border>
      <el-table-column prop="customer_name" label="客户名称" min-width="190" show-overflow-tooltip /><el-table-column prop="customer_id" label="客户ID" min-width="130" /><el-table-column prop="login_email" label="登录邮箱" min-width="220" show-overflow-tooltip />
      <el-table-column label="状态" min-width="100"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'" effect="plain">{{ row.is_active ? '启用' : '停用' }}</el-tag></template></el-table-column>
      <el-table-column prop="last_login_at" label="最近登录" min-width="180"><template #default="{ row }">{{ row.last_login_at || '从未登录' }}</template></el-table-column>
      <el-table-column label="操作" min-width="220" fixed="right"><template #default="{ row }"><GlassButton variant="link" left-icon="Edit" @click="openEdit(row)">修改邮箱/密码</GlassButton><GlassButton variant="link" :link-tone="row.is_active ? 'danger' : 'success'" @click="toggle(row)">{{ row.is_active ? '停用' : '启用' }}</GlassButton></template></el-table-column>
    </el-table></div>
    <el-dialog v-model="dialog" :title="editing ? '修改门户账号' : '新建门户账号'" width="520px">
      <el-form label-position="top">
        <el-form-item v-if="!editing" label="客户"><el-select v-model="form.customer_id" filterable remote :remote-method="searchCustomers" :loading="customerLoading" style="width:100%" placeholder="输入客户名称或ID"><el-option v-for="item in customers" :key="item.id" :label="`${item.name} · ID ${item.id}`" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="登录邮箱"><el-input v-model="form.login_email" autocomplete="off" /></el-form-item>
        <el-form-item :label="editing ? '重置密码（留空则不修改）' : '初始密码'"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" /><div class="field-hint">至少10位并包含字母和数字；保存后不会再次显示。</div></el-form-item>
      </el-form>
      <template #footer><GlassButton variant="ghost" @click="dialog=false">取消</GlassButton><GlassButton variant="primary" :loading="saving" @click="save">保存</GlassButton></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createPortalAccount, getPortalAccounts, searchMediaCustomers, updatePortalAccount } from '@/api/customerMedia'
const rows=ref([]),loading=ref(false),search=ref(''),dialog=ref(false),editing=ref(null),saving=ref(false),customers=ref([]),customerLoading=ref(false)
const form=reactive({customer_id:'',login_email:'',password:''})
async function load(){loading.value=true;try{rows.value=(await getPortalAccounts(search.value)).data||[]}finally{loading.value=false}}
function openCreate(){editing.value=null;Object.assign(form,{customer_id:'',login_email:'',password:''});dialog.value=true}
function openEdit(row){editing.value=row;Object.assign(form,{customer_id:row.customer_id,login_email:row.login_email,password:''});dialog.value=true}
async function searchCustomers(term){if(!term?.trim())return;customerLoading.value=true;try{customers.value=(await searchMediaCustomers(term)).data||[]}finally{customerLoading.value=false}}
async function save(){if(!form.login_email||(!editing.value&&!form.customer_id)){ElMessage.warning('请完整填写客户和邮箱');return}if(form.password&&(!/[A-Za-z]/.test(form.password)||!/\d/.test(form.password)||form.password.length<10)){ElMessage.warning('密码至少10位并包含字母和数字');return}if(!editing.value&&!form.password){ElMessage.warning('请填写初始密码');return}saving.value=true;try{if(editing.value){const data={login_email:form.login_email};if(form.password)data.password=form.password;await updatePortalAccount(editing.value.id,data)}else await createPortalAccount(form);ElMessage.success('账号已保存');dialog.value=false;await load()}finally{saving.value=false}}
async function toggle(row){try{await ElMessageBox.confirm(`确认${row.is_active?'停用':'启用'} ${row.customer_name} 的门户账号？`,'账号状态',{type:'warning'})}catch{return}await updatePortalAccount(row.id,{is_active:!row.is_active});await load()}
onMounted(load)
</script>
<style scoped>
.accounts-page{position:relative}.accounts-aurora{inset:-24px -28px}.page-header,.toolbar,.accounts-panel{position:relative;z-index:1}.page-header{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:18px}.page-header h2{margin:0 0 5px}.page-header p{margin:0;color:var(--text-secondary)}.toolbar{display:flex;gap:10px;margin-bottom:14px}.toolbar .el-input{max-width:340px}.accounts-panel{background:var(--dash-glass-bg);border:1px solid var(--dash-glass-border);border-radius:var(--dash-card-radius);overflow:hidden}.field-hint{color:var(--text-secondary);font-size:12px;margin-top:5px}
</style>
