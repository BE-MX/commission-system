<template>
  <section class="gateway-apps">
    <p class="intro">每个站点使用独立密钥。已占用次数包含准入后的失败调用，未知用量单独统计。</p>
    <div class="toolbar">
      <el-input v-model="searchForm.search" placeholder="搜索应用名称" clearable aria-label="搜索应用名称" @keyup.enter="handleSearch" @clear="handleSearch" />
      <GlassButton @click="handleSearch">搜索</GlassButton>
      <GlassButton @click="fetchList">刷新</GlassButton>
      <GlassButton v-permission="'ai:admin'" variant="primary" left-icon="Plus" @click="openEditor()">创建站点应用</GlassButton>
    </div>
    <div class="table-card">
      <el-table :data="list" v-loading="loading" border class="list-table">
        <el-table-column prop="name" label="应用名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="owner_name" label="负责人" min-width="100" />
        <el-table-column label="状态" min-width="95">
          <template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'" effect="plain">{{ row.is_enabled ? '启用' : '停用' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="今日已占用" min-width="125"><template #default="{ row }">{{ row.today_calls }} / {{ row.daily_limit }}</template></el-table-column>
        <el-table-column label="已知输入 / 输出 token" min-width="185"><template #default="{ row }">{{ row.tokens_prompt }} / {{ row.tokens_completion }}</template></el-table-column>
        <el-table-column prop="unknown_usage" label="用量未完整返回" min-width="140" />
        <el-table-column prop="failures" label="失败 / 未知" min-width="110" />
        <el-table-column label="并发占用" min-width="160"><template #default="{ row }">{{ row.occupied }} / {{ row.concurrency_limit }}<el-tag v-if="row.needs_review" type="warning" effect="plain">{{ row.needs_review }} 条待核查</el-tag></template></el-table-column>
        <el-table-column label="最近调用" min-width="170"><template #default="{ row }">{{ formatDateTime(row.last_used_at) || '尚未调用' }}</template></el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="300" :fixed="isNarrow ? false : 'right'">
          <template #default="{ row }">
            <GlassButton v-permission="'ai:admin'" variant="link" @click="openEditor(row)">编辑</GlassButton>
            <GlassButton v-permission="'ai:admin'" variant="link" @click="showRequests(row)">调用记录</GlassButton>
            <GlassButton v-permission="'ai:admin'" variant="link" :disabled="busy" @click="rotate(row)">重置密钥</GlassButton>
            <GlassButton v-permission="'ai:admin'" variant="link" :disabled="busy" @click="toggle(row)">{{ row.is_enabled ? '停用' : '启用' }}</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination :current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="handlePageChange" />
    </div>

    <el-dialog v-model="editorVisible" :title="editId ? '编辑站点应用' : '创建站点应用'" width="620px" destroy-on-close append-to-body>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" v-loading="optionsLoading">
        <el-form-item label="应用名称" prop="name"><el-input v-model="form.name" maxlength="100" /></el-form-item>
        <el-form-item label="负责人" prop="owner_user_id"><el-select v-model="form.owner_user_id" filterable placeholder="选择负责人"><el-option v-for="owner in options.owners" :key="owner.id" :label="owner.name" :value="owner.id" /></el-select></el-form-item>
        <el-form-item label="站点地址（备注）"><el-input v-model="form.site_url" maxlength="512" /></el-form-item>
        <el-form-item label="用途说明"><el-input v-model="form.description" type="textarea" maxlength="1000" /></el-form-item>
        <el-form-item label="允许的文本能力" prop="preset_ids">
          <el-select v-model="form.preset_ids" multiple filterable placeholder="选择已配置的文本 Preset">
            <el-option v-for="preset in options.presets" :key="preset.id" :value="preset.id" :label="`${preset.name} · ${preset.model}`" />
          </el-select>
          <p class="hint">只列出可用的 direct 文本配置。若无选项，请先在调用预设中配置。</p>
        </el-form-item>
        <div class="limits">
          <el-form-item label="每日次数"><el-input-number v-model="form.daily_limit" :min="1" :max="100000" :precision="0" /></el-form-item>
          <el-form-item label="每分钟次数"><el-input-number v-model="form.rpm_limit" :min="1" :max="1000" :precision="0" /></el-form-item>
          <el-form-item label="最大并发"><el-input-number v-model="form.concurrency_limit" :min="1" :max="20" :precision="0" /></el-form-item>
          <el-form-item label="最大输出 token"><el-input-number v-model="form.max_output_tokens" :min="1" :max="4096" :precision="0" /></el-form-item>
        </div>
      </el-form>
      <template #footer><GlassButton @click="editorVisible = false">取消</GlassButton><GlassButton v-permission="'ai:admin'" variant="primary" :loading="busy" :disabled="optionsLoading" @click="save">保存</GlassButton></template>
    </el-dialog>

    <el-dialog v-model="keyVisible" title="保存站点密钥" width="620px" :close-on-click-modal="false" append-to-body @closed="issuedKey = ''">
      <el-alert title="密钥只显示这一次，请保存到站点服务端的密钥配置中。关闭后无法找回，可通过重置生成新密钥。" type="warning" :closable="false" />
      <textarea ref="configField" class="key-config" :value="keyConfig" readonly rows="4" aria-label="站点服务端配置" spellcheck="false" />
      <p>让 Codex 编写后端调用代码，密钥由你填入服务端配置。不要把这段密钥粘贴进网页源码或公开文档。</p>
      <template #footer><GlassButton @click="copyKey">复制配置</GlassButton><GlassButton variant="primary" @click="keyVisible = false">已保存，关闭</GlassButton></template>
    </el-dialog>

    <DetailDrawer v-model="requestsVisible" :title="`${selected?.name || ''} · 调用记录`" width="1000px">
      <div class="toolbar">
        <el-select v-model="requests.searchForm.status" placeholder="全部状态" clearable @change="requests.handleSearch">
          <el-option v-for="(label, value) in statusNames" :key="value" :label="label" :value="value" />
        </el-select>
        <el-date-picker v-model="requests.searchForm.date_from" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" @change="requests.handleSearch" />
        <el-date-picker v-model="requests.searchForm.date_to" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" @change="requests.handleSearch" />
        <GlassButton @click="requests.fetchList">刷新</GlassButton>
      </div>
      <p class="hint">待核查请求继续占用并发。解除前请确认本地执行已结束并核查供应商结果；解除不退还次数，也不会重发请求。</p>
      <el-table :data="requests.list.value" v-loading="requests.loading.value" border class="list-table">
        <el-table-column prop="request_id" label="Request ID" min-width="200" show-overflow-tooltip />
        <el-table-column prop="preset_name" label="能力" min-width="130" />
        <el-table-column label="时间" min-width="170"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></el-table-column>
        <el-table-column label="状态" min-width="115"><template #default="{ row }">{{ statusNames[row.status] }}</template></el-table-column>
        <el-table-column label="输入 / 输出" min-width="130"><template #default="{ row }">{{ row.tokens_prompt ?? '未知' }} / {{ row.tokens_completion ?? '未知' }}</template></el-table-column>
        <el-table-column prop="error_code" label="错误分类" min-width="160" />
        <el-table-column prop="resolution_reason" label="核查结论" min-width="180" show-overflow-tooltip />
        <el-table-column class-name="table-action-column" label="处理" min-width="130" :fixed="isNarrow ? false : 'right'"><template #default="{ row }"><GlassButton v-if="row.can_resolve" v-permission="'ai:admin'" variant="link" @click="openResolution(row)">解除占用</GlassButton></template></el-table-column>
      </el-table>
      <el-pagination :current-page="requests.page.value" :page-size="requests.pageSize.value" :total="requests.total.value" layout="total, prev, pager, next" @current-change="requests.handlePageChange" />
    </DetailDrawer>
    <el-dialog v-model="resolveVisible" title="核查后解除并发占用" width="520px" append-to-body>
      <el-input v-model="resolutionReason" type="textarea" :rows="4" maxlength="1000" placeholder="填写执行状态、上游核查结果（至少 5 个字，不含客户正文或密钥）" aria-label="核查结论" />
      <el-checkbox v-model="resolutionConfirmed">已确认本地执行结束，并完成上游结果核查</el-checkbox>
      <template #footer><GlassButton @click="resolveVisible = false">取消</GlassButton><GlassButton v-permission="'ai:admin'" variant="primary" :loading="busy" :disabled="!resolutionConfirmed || resolutionReason.trim().length < 5" @click="resolve">解除占用</GlassButton></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { useListPage } from '@/composables/useListPage'
import { msgSuccess, msgError, confirmDanger } from '@/utils/feedback'
import { formatBeijingDateTime as formatDateTime } from '@/utils/datetime'
import { gatewayOptions, listGatewayApps, createGatewayApp, updateGatewayApp, rotateGatewayKey, listGatewayRequests, resolveGatewayRequest } from '@/api/aiGateway'

const { list, loading, page, pageSize, total, searchForm, fetchList, handleSearch, handlePageChange } = useListPage(
  async params => (await listGatewayApps(params)).data, { searchForm: { search: '' } },
)
const options = ref({ owners: [], presets: [] })
const optionsLoading = ref(false)
const busy = ref(false)
const narrowQuery = window.matchMedia('(max-width: 600px)')
const isNarrow = ref(narrowQuery.matches)
function updateNarrow(event) { isNarrow.value = event.matches }
narrowQuery.addEventListener('change', updateNarrow)
const editorVisible = ref(false)
const editId = ref(null)
const formRef = ref()
const defaults = () => ({ name: '', owner_user_id: null, site_url: '', description: '', preset_ids: [], daily_limit: 100, rpm_limit: 10, concurrency_limit: 2, max_output_tokens: 2048 })
const form = reactive(defaults())
const rules = { name: [{ required: true, message: '请输入应用名称', trigger: 'blur' }], owner_user_id: [{ required: true, message: '请选择负责人', trigger: 'change' }], preset_ids: [{ type: 'array', required: true, min: 1, message: '至少选择一种文本能力', trigger: 'change' }] }
const keyVisible = ref(false)
const issuedKey = ref('')
const issuedPreset = ref('')
// Public service entry is independent of the administrator's LAN/dev address.
const gatewayBase = 'https://leshine.work/api/ai-gateway'
const configField = ref(null)
const keyConfig = computed(() => `ARK_AI_BASE_URL=${gatewayBase}\nARK_AI_KEY=${issuedKey.value}\nARK_AI_PRESET=${issuedPreset.value}`)
const requestsVisible = ref(false)
const selected = ref(null)
const statusNames = { pending: '执行中 / 待核查', success: '成功', error: '失败', timeout: '已核查超时', unknown: '结果未知' }
const requests = useListPage(async params => {
  const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v != null))
  return (await listGatewayRequests(selected.value.id, clean)).data
}, { immediate: false, searchForm: { status: '', date_from: '', date_to: '' } })
const resolveVisible = ref(false)
const resolvingRow = ref(null)
const resolutionReason = ref('')
const resolutionConfirmed = ref(false)

async function openEditor(row) {
  editId.value = row?.id || null
  Object.assign(form, defaults(), row ? Object.fromEntries(Object.keys(defaults()).map(k => [k, Array.isArray(row[k]) ? [...row[k]] : row[k]])) : {})
  editorVisible.value = true
  optionsLoading.value = true
  try { options.value = (await gatewayOptions()).data } finally { optionsLoading.value = false }
}
function revealKey(data, presetIds) {
  issuedKey.value = data.api_key
  issuedPreset.value = data.preset_names?.[0] || options.value.presets.find(p => presetIds?.includes(p.id))?.name || '<已授权的 Preset 名称>'
  keyVisible.value = true
}
async function save() {
  if (!await formRef.value.validate().catch(() => false)) return
  busy.value = true
  try {
    const result = editId.value ? await updateGatewayApp(editId.value, { ...form }) : await createGatewayApp({ ...form })
    if (!editId.value) revealKey(result.data, form.preset_ids)
    editorVisible.value = false
    msgSuccess('保存')
    await fetchList()
  } finally { busy.value = false }
}
async function rotate(row) {
  if (!await confirmDanger('重置密钥', row.name, '旧密钥立即失效，需要更新站点的服务端配置。').then(() => true).catch(() => false)) return
  busy.value = true
  try { revealKey({ ...(await rotateGatewayKey(row.id)).data, preset_names: row.preset_names }, row.preset_ids); await fetchList() } finally { busy.value = false }
}
async function toggle(row) {
  if (row.is_enabled && !await confirmDanger('停用', row.name, '新的请求会被拒绝，已准入请求仍可能完成并计费。').then(() => true).catch(() => false)) return
  busy.value = true
  try { await updateGatewayApp(row.id, { is_enabled: !row.is_enabled }); msgSuccess(row.is_enabled ? '停用' : '启用'); await fetchList() } finally { busy.value = false }
}
async function copyKey() {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(keyConfig.value); msgSuccess('复制'); return }
    catch { /* Permission denial: try selection-based copy inside this dialog. */ }
  }
  const field = configField.value
  if (!field) return
  field.focus()
  field.select()
  field.setSelectionRange(0, field.value.length)
  try {
    if (document.execCommand('copy')) { msgSuccess('复制'); return }
  } catch { /* Keep the full configuration selected for keyboard copy. */ }
  msgError('浏览器阻止了自动复制，配置已全选，请按 Ctrl+C（Mac：⌘C）保存')
}
async function showRequests(row) {
  selected.value = row
  requestsVisible.value = true
  await requests.handleReset()
}
function openResolution(row) {
  resolvingRow.value = row
  resolutionReason.value = ''
  resolutionConfirmed.value = false
  resolveVisible.value = true
}
async function resolve() {
  if (!resolutionConfirmed.value || resolutionReason.value.trim().length < 5) return
  busy.value = true
  try {
    await resolveGatewayRequest(selected.value.id, resolvingRow.value.request_id, resolutionReason.value.trim())
    resolveVisible.value = false
    msgSuccess('解除占用')
    await Promise.all([requests.fetchList(), fetchList()])
  } finally { busy.value = false }
}
onBeforeUnmount(() => { issuedKey.value = ''; narrowQuery.removeEventListener('change', updateNarrow) })
</script>

<style scoped>
.gateway-apps { display: grid; gap: 16px; min-width: 0; }
.intro, .hint { color: var(--text-secondary); line-height: 1.6; }
.hint { margin: 8px 0; font-size: 12px; }
.toolbar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.toolbar > .el-input { width: 220px; }
.toolbar > .el-select { width: 170px; }
.table-card { min-width: 0; overflow: auto; }
.el-pagination { margin-top: 16px; }
.el-select { width: 100%; }
.limits { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.key-config { display: block; width: 100%; box-sizing: border-box; margin-top: 16px; resize: vertical; font-family: monospace; white-space: pre-wrap; overflow-wrap: anywhere; padding: 16px; background: var(--page-bg); color: var(--text-primary); border: 1px solid var(--border-color); border-radius: 8px; }
@media (max-width: 600px) { .limits { grid-template-columns: 1fr; } }
</style>
