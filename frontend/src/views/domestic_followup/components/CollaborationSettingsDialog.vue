<template>
  <el-dialog v-model="visible" title="跟进协作管理" width="760px" append-to-body destroy-on-close>
    <el-tabs v-model="tab" @tab-change="switchTab">
      <el-tab-pane v-if="canConfigure" label="协作范围" name="scopes">
        <el-form label-position="top" @submit.prevent="addScope">
          <div class="settings-fields">
            <el-form-item label="人员" required>
              <el-select v-model="scope.user_id" class="full" filterable remote :remote-method="searchUsers" :loading="searching"
                         placeholder="按姓名搜索">
                <el-option v-for="person in users" :key="person.user_id" :label="person.name" :value="person.user_id" />
              </el-select>
            </el-form-item>
            <el-form-item label="授权对象">
              <el-select v-model="scopeType" class="full"><el-option label="地区" value="region" /><el-option label="指定客户" value="customer" /></el-select>
            </el-form-item>
            <el-form-item v-if="scopeType === 'customer'" label="客户档案编号" required>
              <el-input-number v-model="scope.customer_id" :min="1" :precision="0" :controls="false" class="full" />
            </el-form-item>
            <template v-else>
              <el-form-item label="省份" required><el-input v-model="scope.province" maxlength="50" /></el-form-item>
              <el-form-item label="城市"><el-input v-model="scope.city" maxlength="50" placeholder="留空覆盖全省" /></el-form-item>
            </template>
          </div>
          <GlassButton variant="primary" :loading="writing" :disabled="!canAddScope" @click="addScope">添加范围</GlassButton>
        </el-form>
        <div class="settings-threshold">
          <label for="pending-handoff-days">待接收进入协调清单（自然日）</label>
          <el-input-number id="pending-handoff-days" v-model="threshold" :min="1" :max="30" :precision="0" />
          <GlassButton :disabled="!threshold || threshold === savedThreshold || writing" @click="saveThreshold">保存天数</GlassButton>
        </div>
      </el-tab-pane>
      <el-tab-pane label="协调清单" name="queue">
        <p class="settings-hint">查看待分配、久未推进和接收异常的客户。</p>
      </el-tab-pane>
      <el-tab-pane label="历史责任初始化" name="initialization">
        <p class="settings-hint">核对名单后勾选要初始化的客户。有待核对事项的客户初始化为待分配。</p>
        <GlassButton variant="primary" :loading="writing" :disabled="!selected.length" @click="initialize">初始化所选客户</GlassButton>
      </el-tab-pane>
    </el-tabs>
    <el-alert v-if="error" type="error" :title="error" :closable="false" show-icon>
      <GlassButton variant="link" @click="load">刷新清单</GlassButton>
    </el-alert>
    <div v-loading="loading" class="settings-list">
      <article v-for="row in rows" :key="row.id || row.customer_id" class="settings-row">
        <template v-if="tab === 'scopes'">
          <span><strong>{{ row.user_name }}</strong> · {{ row.customer_id ? `客户档案 #${row.customer_id}` : [row.province, row.city].filter(Boolean).join(' · ') }}</span>
          <GlassButton variant="link" :disabled="writing" @click="removeScope(row)">撤销范围</GlassButton>
        </template>
        <template v-else-if="tab === 'queue'">
          <div><strong>{{ row.shop_name }}</strong><p>{{ reasonText(row.coordination_reasons) }}</p></div>
          <GlassButton variant="link" @click="inspect(row.customer_id)">处理</GlassButton>
        </template>
        <template v-else>
          <el-checkbox :model-value="selected.includes(row.customer_id)" @change="checked => toggle(row.customer_id, checked)">
            {{ row.shop_name }}
          </el-checkbox>
          <span>{{ row.candidate_owner_user_id ? (row.candidate_owner_name || `候选负责人 #${row.candidate_owner_user_id}`) : reasonText(row.issues) }}</span>
        </template>
      </article>
      <el-empty v-if="!loading && !error && !rows.length" description="当前没有待查看的条目" :image-size="64" />
    </div>
    <el-pagination v-if="total" v-model:current-page="page" v-model:page-size="pageSize" :total="total"
                   :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" :pager-count="5" class="pager"
                   @current-change="load" @size-change="switchTab" />
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import GlassButton from '@/components/GlassButton.vue'
import { confirmAction, isFeedbackCancelled, msgSuccessText } from '@/utils/feedback'
import { useAuthStore } from '@/stores/auth'
import { COORDINATION_REASON, labelFor } from '../customerOverview'

const emit = defineEmits(['changed', 'inspect'])
const auth = useAuthStore()
const canConfigure = computed(() => auth.hasPermission('domestic_followup:admin') && auth.hasPermission('domestic_followup:coordinate'))
const visible = ref(false), tab = ref('scopes'), error = ref(''), loading = ref(false), writing = ref(false)
const rows = ref([]), users = ref([]), selected = ref([]), searching = ref(false)
const scopeType = ref('region')
const scope = reactive({ user_id: null, customer_id: null, province: '', city: '' })
const threshold = ref(null), savedThreshold = ref(null)
const page = ref(1), total = ref(0), pageSize = ref(20)
const readers = { scopes: followupApi.collaborationScopes, queue: followupApi.collaborationCoordination, initialization: followupApi.collaborationInitialization }
const canAddScope = computed(() => !writing.value && scope.user_id && (scopeType.value === 'customer' ? scope.customer_id : scope.province.trim()))
const issues = { ...COORDINATION_REASON, missing_region: '地区未补齐', missing_owner: '客户归属待确认', development_conflict: '存在待核对的开发待办' }
const reasonText = reasons => reasons?.map(reason => labelFor(issues, reason)).join('、') || '待分配'
let readSequence = 0
let userSequence = 0
function open() {
  visible.value = true
  tab.value = canConfigure.value ? 'scopes' : 'queue'
  switchTab()
  if (canConfigure.value) {
    searchUsers('')
    loadThreshold()
  }
}
function switchTab() {
  rows.value = []
  total.value = 0
  page.value = 1
  load()
}
async function load() {
  const run = ++readSequence
  error.value = ''
  selected.value = []
  loading.value = true
  try {
    const result = await readers[tab.value]({ page: page.value, page_size: pageSize.value })
    if (run !== readSequence) return
    rows.value = result.items
    total.value = result.total
    if (page.value > 1 && !rows.value.length) {
      page.value = Math.max(1, Math.ceil(total.value / pageSize.value))
      return load()
    }
  } catch (failure) {
    if (run === readSequence) error.value = errorText(failure, '清单加载失败')
  } finally { if (run === readSequence) loading.value = false }
}
function errorText(failure, fallback) {
  const detail = apiError(failure, fallback)
  return typeof detail === 'string' ? detail : detail.message || fallback
}
async function searchUsers(value) {
  const run = ++userSequence
  searching.value = true
  try {
    const result = await followupApi.collaborationUsers(value)
    if (run === userSequence) users.value = result
  } catch (failure) {
    if (run === userSequence) error.value = errorText(failure, '人员加载失败')
  } finally { if (run === userSequence) searching.value = false }
}
async function loadThreshold() {
  try {
    const result = await followupApi.collaborationThresholds()
    threshold.value = savedThreshold.value = result.pending_handoff_days
  } catch (failure) { error.value = errorText(failure, '提醒阈值加载失败') }
}
async function saveThreshold() {
  await write(async () => {
    const result = await followupApi.saveCollaborationThresholds({ pending_handoff_days: threshold.value })
    threshold.value = savedThreshold.value = result.pending_handoff_days
    msgSuccessText('已更新协调阈值')
  })
}
async function write(action) {
  if (writing.value) return
  writing.value = true
  error.value = ''
  try { await action() }
  catch (failure) { error.value = errorText(failure, '保存失败，请核对后重试') }
  finally { writing.value = false }
}
async function addScope() {
  if (!canAddScope.value) return
  const target = scopeType.value === 'customer' ? { customer_id: scope.customer_id } : { province: scope.province.trim(), city: scope.city.trim() || null }
  await write(async () => {
    await followupApi.addCollaborationScope({ user_id: scope.user_id, ...target })
    msgSuccessText('已添加协作范围')
    emit('changed')
    await load()
  })
}
async function removeScope(row) {
  try { await confirmAction(`撤销 ${row.user_name} 的这一条协作授权？`, '撤销协作范围') }
  catch (failure) { if (!isFeedbackCancelled(failure)) error.value = errorText(failure, '无法确认撤销'); return }
  await write(async () => {
    await followupApi.removeCollaborationScope(row.id)
    msgSuccessText('已撤销协作范围')
    emit('changed')
    await load()
  })
}
function toggle(id, checked) {
  selected.value = checked ? [...selected.value, id] : selected.value.filter(current => current !== id)
}
async function initialize() {
  const items = rows.value.filter(row => selected.value.includes(row.customer_id)).map(({ customer_id, token }) => ({ customer_id, token }))
  if (!items.length) return
  await write(async () => {
    const result = await followupApi.initializeCollaboration(items)
    const initialized = result.items.filter(item => item.status === 'initialized').length
    const existing = result.items.filter(item => item.status === 'existing').length
    const changed = result.items.length - initialized - existing
    msgSuccessText(`已初始化 ${initialized} 个，已有责任 ${existing} 个，资料变化 ${changed} 个`)
    emit('changed')
    await load()
  })
}
function inspect(id) { visible.value = false; emit('inspect', id) }
defineExpose({ open })
</script>

<style scoped>
.settings-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.settings-threshold { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
.settings-hint, .settings-row p { color: var(--text-secondary); margin: 4px 0 8px; }
.settings-list { margin: 12px 0; }
.settings-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--border-color); }
.full { width: 100%; }
</style>
