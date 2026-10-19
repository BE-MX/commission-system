<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { portalAdminApi } from '@/api/portal'
import { msgError, msgSuccess, promptAction } from '@/utils/feedback'
const requests = ref([]), loading = ref(false), error = ref(''), status = ref('pending'), keyword = ref(''), selected = ref(null), accessId = ref(''), reason = ref(''), busy = ref(false)
let controller
async function load() { loading.value = true; error.value = ''; controller?.abort(); controller = new AbortController(); try { const data = await portalAdminApi.accessRequests({ status: status.value, keyword: keyword.value }, controller.signal); requests.value = data.items || [] } catch (e) { if (e.code !== 'REQUEST_ABORTED') error.value = e.message || '读取申请失败。' } finally { loading.value = false } }
function open(row) { selected.value = row; accessId.value = ''; reason.value = '' }
async function review(decision) {
  if (!selected.value || busy.value) return
  if (decision === 'approve' && !accessId.value) { msgError('批准前请选择已启用的客户门户授权。'); return }
  if (!reason.value.trim()) { msgError('请填写审核备注。'); return }
  busy.value = true
  try { const data = await portalAdminApi.reviewAccessRequest(selected.value.id, { decision, access_id: decision === 'approve' ? accessId.value : null, reason: reason.value.trim() }); msgSuccess(decision === 'approve' ? '申请已批准，激活邮件已进入发送队列。' : '申请已拒绝。'); selected.value = null; await load(); return data } catch (e) { msgError(e.message || '处理申请失败。') } finally { busy.value = false }
}
onMounted(load); onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <section class="portal-access-requests">
    <header class="portal-heading"><div><h1>客户账号申请</h1><p>先核对申请人，再绑定现有客户门户授权。批准后发送邮箱激活链接，客户自行设置密码。</p></div><GlassButton :disabled="loading" @click="load">刷新</GlassButton></header>
    <div class="toolbar"><el-input v-model="keyword" aria-label="搜索申请" placeholder="姓名或邮箱" maxlength="100" @keyup.enter="load" /><el-select v-model="status" aria-label="申请状态" @change="load"><el-option label="待审核" value="pending" /><el-option label="已批准" value="approved" /><el-option label="已拒绝" value="rejected" /></el-select><GlassButton @click="load">搜索</GlassButton></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="table-card"><el-table v-loading="loading" :data="requests" border class="list-table" v-sticky-scrollbar><el-table-column prop="full_name" label="申请人" min-width="130" /><el-table-column prop="email" label="邮箱" min-width="220" /><el-table-column prop="phone" label="电话" min-width="150" /><el-table-column prop="created_at" label="申请时间" min-width="180" /><el-table-column label="状态" min-width="110"><template #default="{ row }"><el-tag>{{ row.status }}</el-tag></template></el-table-column><el-table-column label="操作" fixed="right" min-width="90"><template #default="{ row }"><GlassButton variant="link" :disabled="row.status !== 'pending'" @click="open(row)">审核</GlassButton></template></el-table-column></el-table></div>
    <el-dialog :model-value="Boolean(selected)" title="审核客户账号申请" width="640px" @update:model-value="value => { if (!value) selected = null }">
      <template v-if="selected"><dl class="request-detail"><div><dt>申请人</dt><dd>{{ selected.full_name }}</dd></div><div><dt>邮箱</dt><dd>{{ selected.email }}</dd></div><div><dt>电话</dt><dd>{{ selected.phone }}</dd></div></dl><el-alert title="批准不会让申请人直接登录。系统会把邮箱绑定到你选择的现有客户授权，并发送一次性激活链接，由客户设置邮箱密码。" type="info" :closable="false" /><el-form label-position="top"><el-form-item label="绑定客户授权（批准必选）"><el-input v-model="accessId" placeholder="粘贴客户门户授权 ID" maxlength="36" /></el-form-item><el-form-item label="审核备注"><el-input v-model="reason" type="textarea" :rows="3" maxlength="500" placeholder="说明核对结果" /></el-form-item></el-form></template>
      <template #footer><GlassButton :disabled="busy" @click="selected = null">取消</GlassButton><GlassButton :disabled="busy" @click="review('reject')">拒绝申请</GlassButton><GlassButton variant="primary" :loading="busy" @click="review('approve')">批准并发送激活邮件</GlassButton></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.portal-heading { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 24px; } h1 { margin: 0 0 8px; } p, dd { color: var(--text-secondary); overflow-wrap: anywhere; } .toolbar { display: flex; gap: 12px; margin-bottom: 16px; } .table-card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px; overflow: hidden; } .request-detail { display: grid; gap: 10px; } .request-detail div { display: flex; justify-content: space-between; gap: 16px; } dt { color: var(--text-secondary); } dd { margin: 0; } @media (max-width: 600px) { .portal-heading, .toolbar { align-items: stretch; flex-direction: column; } }
</style>
