<template>
  <section class="source-settings" v-permission="'alibaba_feed:admin'" v-loading="loading">
    <header class="pilot-header">
      <div>
        <h2>店铺试点</h2>
        <p>登记一个店铺和一位业务员。保存配置后，可单独启用试点。</p>
      </div>
      <GlassButton :disabled="loading || !!busy" left-icon="Refresh" @click="load()">刷新配置</GlassButton>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="pilot">
      <div class="pilot-status">
        <StatusBadge :type="pilot.enabled ? 'success' : 'info'" effect="plain">{{ statusLabel }}</StatusBadge>
        <span v-if="pilot.source">采集代次 {{ pilot.source.collection_generation }}</span>
      </div>
      <el-form label-position="top" :disabled="locked || pilot.enabled" @submit.prevent="save">
        <div class="pilot-fields">
          <el-form-item label="店铺名称" required>
            <el-input v-model.trim="form.name" maxlength="100" placeholder="输入阿里国际站店铺名称" />
          </el-form-item>
          <el-form-item label="店铺来源标识" required>
            <el-input v-model.trim="form.source_account_uid" maxlength="64" placeholder="与 AW 配置中的来源标识一致" />
          </el-form-item>
          <el-form-item label="AW 采集账号" required>
            <el-select v-model="form.integration_app_id" filterable placeholder="选择 AW 专用接入应用">
              <el-option v-if="missingCollector" disabled :value="form.integration_app_id" label="已绑定的采集账号不可用" />
              <el-option v-for="app in pilot.collectors" :key="app.id" :value="app.id" :label="app.name + ' · ' + app.public_id" />
            </el-select>
            <div class="collector-help">
              <span v-if="!pilot.collectors.length">暂无有效的 AW 专用接入应用。</span>
              <GlassButton v-permission="'integration:admin'" variant="link" :disabled="!canIssue" @click="issueCollector">创建 AW 专用凭据</GlassButton>
            </div>
          </el-form-item>
          <el-form-item label="试点业务员" required>
            <el-select v-model="form.user_id" filterable placeholder="选择有 TM 资料读取权限的业务员">
              <el-option v-if="missingUser" disabled :value="form.user_id" label="已选业务员已停用或缺少权限" />
              <el-option v-for="user in pilot.users" :key="user.id" :value="user.id" :label="userLabel(user)" />
            </el-select>
          </el-form-item>
          <el-form-item label="AW 导出的负责人显示名" required>
            <el-input v-model="form.owner_alias" maxlength="200" placeholder="输入完整显示名，按原文精确匹配" />
          </el-form-item>
        </div>
        <p v-if="pilot.enabled" class="pilot-hint">停用试点后可修改店铺配置。已接收的批次会保留。</p>
        <p v-else-if="dirty && pilot.source" class="pilot-hint">请先保存更改，再启用试点。</p>
        <div class="pilot-actions">
          <GlassButton v-if="!pilot.enabled" native-type="submit" variant="primary" :disabled="!dirty || !valid || locked" :loading="busy === 'save'">保存配置</GlassButton>
          <GlassButton v-if="!pilot.enabled" :disabled="!canActivate" :loading="busy === 'activation'" @click="setEnabled(true)">启用试点</GlassButton>
          <GlassButton v-else :disabled="locked" :loading="busy === 'activation'" @click="setEnabled(false)">停用试点</GlassButton>
        </div>
      </el-form>
    </template>
    <el-dialog :model-value="!!issuedToken" title="AW 专用凭据" width="480px" @update:model-value="visible => { if (!visible) issuedToken = '' }" destroy-on-close>
      <p>Token 仅显示一次。请将它保存到 AW 的凭据环境变量。</p>
      <el-input :model-value="issuedToken" readonly type="password" show-password aria-label="AW Token" />
      <el-alert v-if="copyError" :title="copyError" type="warning" :closable="false" />
      <template #footer>
        <GlassButton @click="issuedToken = ''">关闭</GlassButton>
        <GlassButton variant="primary" @click="copyToken">复制 Token</GlassButton>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { alibabaFeedApi as api } from '@/api/alibabaFeed'
import { createIntegrationApp } from '@/api/integrationApps'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { confirmAction, isFeedbackCancelled, msgSuccessText } from '@/utils/feedback'
import { createReadScope } from './feedState'

const errors = {
  PILOT_CONFIGURATION_UNAVAILABLE: '试点配置尚未初始化，请联系系统管理员。',
  PILOT_VERSION_CONFLICT: '其他管理员已更新配置。请刷新后核对。',
  PILOT_PAUSE_REQUIRED: '试点正在启用，请刷新并停用后再修改。',
  PILOT_SOURCE_ALREADY_BOUND: '该来源标识已绑定其他采集账号。请选择原账号，或使用新的来源标识。',
  PILOT_COLLECTOR_ALREADY_BOUND: '该采集账号已绑定其他店铺来源。请选择另一 AW 专用账号。',
  PILOT_COLLECTOR_INVALID: '采集账号不可用。请选择有接收和回执权限的 AW 专用应用。',
  PILOT_USER_INVALID: '试点业务员须为有效账号，且拥有 TM 资料读取权限。',
  PILOT_CONSENT_REQUIRED: '请先保存配置并确认店铺已授权采集和资料共享。',
  PILOT_MAPPING_REQUIRED: '请先保存 AW 负责人与试点业务员的精确映射。',
}

const auth = useAuthStore()
const pilot = ref(null)
const form = ref(formFor(null))
const loading = ref(false)
const error = ref('')
const busy = ref('')
const needsRefresh = ref(false)
const issuedToken = ref('')
const copyError = ref('')
const scope = createReadScope()
let authority = 0

function formFor(value) {
  return {
    name: value?.source?.name ?? '',
    source_account_uid: value?.source?.source_account_uid ?? '',
    integration_app_id: value?.source?.integration_app_id ?? null,
    user_id: value?.user_id ?? null,
    owner_alias: value?.owner_alias ?? '',
  }
}

const dirty = computed(() => JSON.stringify(form.value) !== JSON.stringify(formFor(pilot.value)))
const locked = computed(() => loading.value || !!busy.value || needsRefresh.value)
const missingCollector = computed(() => !!form.value.integration_app_id && !pilot.value?.collectors.some(app => app.id === form.value.integration_app_id))
const missingUser = computed(() => !!form.value.user_id && !pilot.value?.users.some(user => user.id === form.value.user_id))
const valid = computed(() => !!(form.value.name && /^[A-Za-z0-9._:-]{1,64}$/.test(form.value.source_account_uid)
  && form.value.integration_app_id && !missingCollector.value && form.value.user_id && !missingUser.value && form.value.owner_alias.trim()))
const statusLabel = computed(() => pilot.value?.enabled ? '试点已启用' : pilot.value?.source ? '已配置 · 未启用' : '未配置')
const canActivate = computed(() => !!pilot.value?.source && !dirty.value && valid.value && !locked.value)
const canIssue = computed(() => !locked.value && !pilot.value?.enabled && !!auth.user?.id && form.value.name.length >= 2
  && ['integration:admin', 'alibaba_feed:read', 'alibaba_feed:write'].every(permission => auth.hasPermission(permission)))

function userLabel(user) {
  return user.real_name ? user.real_name + ' · ' + user.username : user.username
}

async function load({ keepDraft = false } = {}) {
  if (!auth.hasPermission('alibaba_feed:admin')) return
  const read = scope.begin()
  loading.value = true
  error.value = ''
  try {
    const data = await api.pilot(read.signal)
    if (!read.isCurrent()) return
    pilot.value = data
    if (!keepDraft || data.enabled) form.value = formFor(data)
    needsRefresh.value = false
  } catch (failure) {
    if (read.isCurrent()) reportFailure(failure, false)
  } finally {
    if (read.isCurrent()) loading.value = false
  }
}

function reportFailure(failure, write = true) {
  const status = failure.response?.status
  const code = failure.response?.data?.data?.error_code
  if ([401, 403].includes(status)) {
    pilot.value = null
    form.value = formFor(null)
    issuedToken.value = ''
  }
  const uncertain = write && (!status || status >= 500)
  needsRefresh.value = uncertain || !write || ['PILOT_VERSION_CONFLICT', 'PILOT_PAUSE_REQUIRED'].includes(code)
  error.value = uncertain ? '提交结果待核对，请先刷新配置。' : errors[code] || errorMessage(failure, '操作失败，请重试')
}

function applyState(data) {
  pilot.value = { ...pilot.value, ...data }
  form.value = formFor(pilot.value)
}

async function save() {
  if (locked.value || !dirty.value || !valid.value || pilot.value?.enabled || !auth.hasPermission('alibaba_feed:admin')) return
  const current = authority
  busy.value = 'save'
  error.value = ''
  try {
    const data = await api.savePilot({ ...form.value, expected_version: pilot.value.version })
    if (current !== authority) return
    applyState(data)
    msgSuccessText('已保存配置，试点仍未启用')
  } catch (failure) {
    if (current === authority) reportFailure(failure)
  } finally {
    if (current === authority) busy.value = ''
  }
}

async function setEnabled(enabled) {
  if (locked.value || !pilot.value || !auth.hasPermission('alibaba_feed:admin')
    || (enabled ? !canActivate.value : !pilot.value.enabled)) return
  const current = authority
  const version = pilot.value.version
  busy.value = 'activation'
  error.value = ''
  try {
    if (enabled) {
      const user = pilot.value.users.find(row => row.id === pilot.value.user_id)
      await confirmAction('确认“' + pilot.value.source.name + '”已授权采集和资料共享。启用后接收该店铺的 AW 批次，资料只开放给 ' + userLabel(user) + '。',
        '确认启用试点', { confirmButtonText: '确认授权并启用', cancelButtonText: '取消', type: 'warning' })
    }
    if (current !== authority) return
    const data = await api.activatePilot({ enabled, expected_version: version, consent_confirmed: enabled })
    if (current !== authority) return
    applyState(data)
    msgSuccessText(enabled ? '试点已启用' : '试点已停用')
  } catch (failure) {
    if (current === authority && !isFeedbackCancelled(failure)) reportFailure(failure)
  } finally {
    if (current === authority) busy.value = ''
  }
}

async function issueCollector() {
  if (!canIssue.value || !auth.hasPermission('alibaba_feed:admin')) return
  const current = authority
  busy.value = 'issue'
  error.value = ''
  try {
    await confirmAction('为当前登录账号生成专用 AW Token。请准备好 AW 的凭据环境变量，Token 仅显示一次。',
      '创建 AW 专用凭据', { confirmButtonText: '生成 Token', cancelButtonText: '取消' })
    if (current !== authority) return
    const { data } = await createIntegrationApp({
      name: (form.value.name + ' · AW').slice(0, 100),
      owner_user_id: auth.user.id,
      scopes: ['alibaba_feed:read', 'alibaba_feed:write'],
    })
    if (current !== authority) return
    issuedToken.value = data.token
    copyError.value = ''
    form.value.integration_app_id = data.id
    await load({ keepDraft: true })
  } catch (failure) {
    if (current === authority && !isFeedbackCancelled(failure)) reportFailure(failure)
  } finally {
    if (current === authority) busy.value = ''
  }
}

async function copyToken() {
  try {
    await navigator.clipboard.writeText(issuedToken.value)
    copyError.value = ''
    msgSuccessText('已复制 Token')
  } catch {
    copyError.value = '无法访问剪贴板，请显示 Token 后选中复制。'
  }
}

function resetAuthority() {
  authority += 1
  scope.clear()
  pilot.value = null
  form.value = formFor(null)
  loading.value = false
  busy.value = ''
  error.value = ''
  needsRefresh.value = false
  issuedToken.value = ''
}

watch(() => JSON.stringify([auth.user?.id, auth.permissions, auth.roles]), () => {
  resetAuthority()
  load()
}, { flush: 'sync' })
onMounted(() => load())
onUnmounted(resetAuthority)
</script>

<style scoped>
.source-settings { padding: 20px; }
.pilot-header, .pilot-status, .pilot-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.pilot-header { justify-content: space-between; margin-bottom: 16px; }
.pilot-header h2 { font-size: 16px; margin: 0 0 4px; }
.pilot-header p, .pilot-hint, .pilot-status > span, .collector-help { color: var(--text-secondary); font-size: 13px; margin: 0; }
.pilot-status { margin-bottom: 18px; }
.pilot-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 20px; max-width: 920px; }
.pilot-fields .el-select { width: 100%; }
.collector-help { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pilot-actions { margin-top: 12px; }
.source-settings .el-alert { margin-bottom: 12px; }
@media (max-width: 640px) {
  .source-settings { padding: 12px; }
  .pilot-fields { grid-template-columns: minmax(0, 1fr); }
}
</style>
