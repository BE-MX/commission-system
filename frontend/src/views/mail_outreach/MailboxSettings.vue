<template>
  <section class="mailbox-settings" v-loading="loading">
    <div class="settings-header">
      <h3>发件邮箱与运行状态</h3>
      <div>
        <GlassButton variant="secondary" left-icon="Refresh" :loading="loading" @click="reload">刷新状态</GlassButton>
        <GlassButton v-permission="'mail_outreach:admin'" variant="primary" left-icon="Plus" @click="open()">绑定发件邮箱</GlassButton>
      </div>
    </div>
    <el-alert v-if="error" type="error" title="运行状态加载失败，请刷新重试；当前显示可能已过期。" :closable="false" />
    <template v-if="status">
      <el-alert :type="status.send_enabled ? 'success' : 'warning'" :title="status.send_enabled ? '发送总开关已开启；逐封审批后才会进入发送队列' : '发送总开关已关闭；审批排程后暂不会发送'" :closable="false" />
      <p class="hint">收件范围：{{ status.allowed_recipients?.length ? status.allowed_recipients.join('、') : '未配置允许收件人，发送会被阻断' }}。队列排程、通道接受与最终送达是不同状态。</p>
      <div class="mailbox-strip">
        <article v-for="mailbox in status.mailboxes || []" :key="mailbox.id" class="mailbox-card">
          <strong>{{ mailbox.sender_email }}</strong>
          <p>{{ mailbox.display_name || '未命名发件人' }} · 每日配额 {{ mailbox.daily_quota }}</p>
          <StatusBadge :type="mailboxAuthStatusTagType(mailbox.auth_status)">{{ mailboxAuthStatusLabel(mailbox.auth_status) }}</StatusBadge>
          <p>账号：{{ mailbox.status === 'active' ? '启用' : '停用' }} · 执行器：{{ (mailbox.worker_ready ?? status.worker_ready) === true ? '就绪' : (mailbox.worker_ready ?? status.worker_ready) === false ? '未就绪' : '待确认' }}</p>
          <p>最近心跳：{{ formatBeijingDateTime(mailbox.worker_last_seen_at) }}</p>
          <p>收信监听：{{ watchHealthLabel(mailbox.watch_health) }}</p>
          <el-alert v-if="mailbox.pause_reason" type="warning" :title="`已暂停：${mailbox.pause_reason}`" :closable="false" />
          <GlassButton v-permission="'mail_outreach:admin'" variant="link" left-icon="Edit" @click="open(mailbox)">管理邮箱</GlassButton>
        </article>
      </div>
      <el-empty v-if="!status.mailboxes?.length" description="尚未绑定发件邮箱，管理员可添加已完成授权的邮箱。" :image-size="64" />
    </template>
    <el-dialog v-model="visible" :title="editingId ? '管理发件邮箱' : '绑定发件邮箱'" width="640px" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
      <el-form label-position="top" :disabled="saving">
        <el-alert type="info" title="这里只登记邮箱和执行器信息。邮箱授权需在服务器完成；选择授权有效不会执行登录。" :closable="false" />
        <el-form-item label="发件邮箱"><el-input v-model="form.sender_email" :disabled="Boolean(editingId)" placeholder="leshinehair@agent.qq.com" maxlength="255" /></el-form-item>
        <el-form-item label="发件人显示名"><el-input v-model="form.display_name" maxlength="128" /></el-form-item>
        <el-form-item label="邮箱所属用户 ID（留空使用当前用户，仅新建时）"><el-input-number v-model="form.owner_user_id" :min="1" :precision="0" /></el-form-item>
        <el-form-item label="执行器身份"><el-input v-model="form.worker_identity" maxlength="64" /></el-form-item>
        <el-form-item label="邮箱工作空间"><el-input v-model="form.cli_workspace" maxlength="64" /></el-form-item>
        <el-form-item label="授权状态"><el-select v-model="form.auth_status"><el-option v-for="item in authOptions" :key="item" :value="item" :label="mailboxAuthStatusLabel(item)" /></el-select></el-form-item>
        <el-form-item label="每日发送配额"><el-input-number v-model="form.daily_quota" :min="1" :precision="0" /></el-form-item>
        <el-form-item label="账号状态"><el-radio-group v-model="form.status"><el-radio value="active">启用</el-radio><el-radio value="disabled">停用</el-radio></el-radio-group></el-form-item>
        <el-form-item label="暂停原因（填写即暂停，清空则解除暂停）"><el-input v-model="form.pause_reason" maxlength="255" /></el-form-item>
        <el-alert v-if="saveError" type="error" title="保存失败，内容已保留，请核对后重试。" :closable="false" />
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" :disabled="saving" @click="visible = false">取消</GlassButton>
        <GlassButton variant="primary" left-icon="Check" :loading="saving" :disabled="!canSave || saving" @click="save">保存</GlassButton>
      </template>
    </el-dialog>
  </section>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { createMailbox, getMailStatus, updateMailbox } from '@/api/mailOutreach'
import { formatBeijingDateTime } from '@/utils/datetime'
import { isEmail } from '@/utils/validators'
import { msgSuccess } from '@/utils/feedback'
import GlassButton from '@/components/GlassButton.vue'
import { mailboxAuthStatusLabel, mailboxAuthStatusTagType } from './presentation'
const emit = defineEmits(['updated'])
const status = ref(null), loading = ref(false), error = ref(null)
const visible = ref(false), saving = ref(false), saveError = ref(null), editingId = ref(null)
const authOptions = ['unknown', 'unbound', 'active', 'expired']
const blank = () => ({ sender_email: '', display_name: '', owner_user_id: null, worker_identity: '', cli_workspace: '', auth_status: 'unknown', daily_quota: 50, status: 'active', pause_reason: '' })
const form = reactive(blank())
const canSave = computed(() => isEmail(form.sender_email) && form.worker_identity.trim() && form.cli_workspace.trim() && form.daily_quota > 0)
function watchHealthLabel(value) {
  if (!value) return '待确认'
  if (typeof value === 'string') return ({ healthy: '正常', stale: '心跳过期', unknown: '待确认', stopped: '已停止' })[value] || value
  return value.status || value.message || JSON.stringify(value)
}
onMounted(reload)
async function reload() {
  if (loading.value) return
  loading.value = true; error.value = null
  try { status.value = (await getMailStatus()).data; emit('updated', status.value?.mailboxes || []) }
  catch (cause) { error.value = cause } finally { loading.value = false }
}
function open(mailbox) {
  editingId.value = mailbox?.id || null
  const defaults = blank()
  Object.assign(form, Object.fromEntries(Object.keys(defaults).map(key => [key, mailbox?.[key] ?? defaults[key]])))
  saveError.value = null; visible.value = true
}
async function save() {
  if (!canSave.value || saving.value) return
  saving.value = true; saveError.value = null
  try {
    const payload = { ...form }
    if (!payload.owner_user_id) delete payload.owner_user_id
    if (editingId.value) { delete payload.sender_email; await updateMailbox(editingId.value, payload) }
    else await createMailbox(payload)
    msgSuccess('邮箱配置已保存'); visible.value = false; await reload()
  } catch (cause) { saveError.value = cause } finally { saving.value = false }
}
</script>
<style scoped>
.mailbox-settings { display: grid; gap: 12px; }
.settings-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 15px; }
.mailbox-strip { display: flex; flex-wrap: wrap; gap: 12px; }
.mailbox-card { flex: 1 1 260px; min-width: 0; padding: 16px; border: 1px solid var(--border-color); border-radius: var(--card-radius); overflow-wrap: anywhere; }
.mailbox-card p, .hint { color: var(--text-secondary); font-size: 13px; }
</style>
