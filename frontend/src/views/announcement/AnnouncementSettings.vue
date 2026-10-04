<template>
  <div v-loading="loading" class="settings">
    <ListPageStatus v-if="configResource.error.value || !configResource.hasLoaded.value" v-bind="resourceStatus(configResource)" @retry="load" />
    <template v-if="configResource.hasLoaded.value && !configResource.error.value && !config.initialized">
      <el-empty description="建立公告库后，可配置类别、成员和推送群。" />
      <el-button :icon="Plus" type="primary" @click="initialize">初始化公告库</el-button>
    </template>
    <el-tabs v-if="config.initialized" v-model="tab">
      <el-tab-pane label="推送与周报" name="config">
        <el-alert type="info" :closable="false" title="使用企业应用机器人。先保存群配置、发送图文测试，再确认图片可见并开启自动推送。" />
        <ListPageStatus v-if="peopleResource.error.value" v-bind="resourceStatus(peopleResource)" @retry="peopleResource.load()" />
        <el-form label-position="top" class="config-form">
          <el-form-item label="公告群名称"><el-input v-model="config.group_name" maxlength="120" /></el-form-item>
          <el-form-item label="群会话 ID（openConversationId）"><el-input v-model="config.conversation_id" maxlength="256" /></el-form-item>
          <el-form-item label="机器人编码（robotCode）"><el-input v-model="config.robot_code" maxlength="128" /></el-form-item>
          <el-form-item label="后台执行账号"><el-select v-model="config.executor_id" filterable remote :remote-method="searchPeople" placeholder="搜索方舟用户"><el-option v-for="p in people" :key="p.user_id" :label="`${p.real_name}（${p.username}）`" :value="p.user_id" /></el-select><small>账号须保持公告库访问权限及公告入口权限。</small></el-form-item>
          <el-form-item label="自动推送"><el-switch v-model="config.delivery_enabled" :disabled="!config.channel_verified" /><span>{{ config.channel_verified ? '图文通道已验证' : '尚未验证图文通道' }}</span></el-form-item>
          <el-form-item label="每周公告周报"><el-switch v-model="config.weekly_enabled" /><span>每周一（北京时间）</span><el-input-number v-model="config.weekly_hour" :min="0" :max="23" />时<el-input-number v-model="config.weekly_minute" :min="0" :max="59" />分</el-form-item>
          <el-form-item label="周报 AI Preset 名称"><el-input v-model="config.preset_name" placeholder="已在 AI 管理中配置的直连文本方案" maxlength="100" /></el-form-item>
        </el-form>
        <div class="actions">
          <el-button :icon="Check" type="primary" :loading="saving" :disabled="Boolean(configResource.error.value) || loading" @click="saveConfig">保存设置</el-button>
          <el-button :icon="Promotion" @click="testChannel">向当前配置群发送图文测试</el-button>
          <el-button v-if="testKey" :icon="View" @click="verify">已确认测试图文可见</el-button>
        </div>
      </el-tab-pane>
      <el-tab-pane label="公告类别" name="categories">
        <ListPageStatus v-if="categoryResource.error.value || categoryResource.loading.value" v-bind="resourceStatus(categoryResource)" @retry="loadCategories" />
        <el-empty v-if="categoryResource.hasLoaded.value && !categoryResource.error.value && !categoryResource.loading.value && !categories.length" description="暂无类别" />
        <div class="actions"><el-input v-model="newCategory" placeholder="新类别名称" maxlength="256" /><el-button :icon="Plus" @click="addCategory">新增类别</el-button></div>
        <div v-for="c in categories" :key="c.id" class="category-row">
          <el-input v-model="c.title" maxlength="256" /><el-switch v-model="c.active" active-text="启用" inactive-text="停用" />
          <el-button :icon="Check" @click="saveCategory(c)">保存</el-button>
        </div>
      </el-tab-pane>
      <el-tab-pane label="公告库成员" name="members">
        <ListPageStatus v-if="membersResource.error.value || membersResource.loading.value" v-bind="resourceStatus(membersResource)" @retry="loadMembers" />
        <p>入口权限在角色管理中分配；这里配置公告库内的查看、编辑、审核与管理范围。修改成员后，旧投递任务会重新核验披露范围。</p>
        <div class="actions"><el-select v-model="newMember" filterable remote :remote-method="searchPeople" placeholder="搜索姓名或用户名"><el-option v-for="p in people" :key="p.user_id" :label="`${p.real_name}（${p.username}）`" :value="p.user_id" /></el-select><el-button :icon="Plus" @click="addMember">添加成员</el-button></div>
        <div v-for="m in members" :key="m.user_id" class="member-row">
          <span>{{ m.real_name || m.username || m.user_id }}</span>
          <el-select v-model="m.role"><el-option v-for="(label, value) in roles" :key="value" :label="label" :value="value" /></el-select>
          <el-button :icon="Delete" @click="members = members.filter(row => row.user_id !== m.user_id)">移除</el-button>
        </div>
        <el-button :icon="Check" type="primary" :disabled="Boolean(membersResource.error.value) || membersResource.loading.value" @click="saveMembers">保存成员权限</el-button>
      </el-tab-pane>
      <el-tab-pane label="投递记录" name="deliveries">
        <p>显示最近 200 条投递记录。</p>
        <ListPageStatus v-if="deliveriesResource.error.value && deliveries.length" v-bind="resourceStatus(deliveriesResource)" @retry="loadDeliveries" />
        <div ref="panelRef" class="table-card">
          <div class="action-bar">
            <TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columnDefs" :fullscreen="isFullscreen" :loading="deliveriesResource.loading.value" @refresh="loadDeliveries" @fullscreen="toggleFullscreen" />
          </div>
          <el-table :data="deliveries" class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" border>
            <template #empty><ListPageStatus v-bind="resourceStatus(deliveriesResource)" @retry="loadDeliveries"><el-empty description="暂无投递记录" /></ListPageStatus></template>
            <el-table-column v-if="visibleKeys.includes('source')" prop="source_key" label="来源" min-width="160" show-overflow-tooltip />
            <el-table-column v-if="visibleKeys.includes('sequence')" prop="sequence" label="分片" min-width="70" />
            <el-table-column prop="status" v-if="visibleKeys.includes('status')" label="状态" min-width="120"><template #default="{ row }"><StatusBadge :value="row.status" :dictionary="DELIVERY_STATUS" /></template></el-table-column>
            <el-table-column v-if="visibleKeys.includes('error')" prop="error" label="处理说明" min-width="180" show-overflow-tooltip />
            <el-table-column label="操作" min-width="230" class-name="table-action-column"><template #default="{ row }">
              <el-button v-if="row.status === 'failed'" :icon="Refresh" link type="primary" @click="retry(row)">重试</el-button>
              <template v-if="row.status === 'uncertain'">
                <el-button :icon="Check" link type="primary" @click="retry(row, true)">核实已送达</el-button>
                <el-button :icon="Check" link type="info" @click="retry(row, false, true)">核实后取消</el-button>
                <el-button :icon="Promotion" link type="warning" @click="retry(row)">核实后重发</el-button>
              </template>
            </template></el-table-column>
          </el-table>
        </div>
        <p>推送成功表示钉钉接口已接收，不代表群成员已读。</p>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>import { confirmAction, msgError, msgSuccess } from '@/utils/feedback'
import { onMounted, ref, watch } from 'vue'

import { Plus, Check, Promotion, View, Delete, Refresh } from '@element-plus/icons-vue'
import { useAsyncResource } from '@/composables/useAsyncResource'
import ListPageStatus from '@/components/ListPageStatus.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { announcementApi as api } from '@/api/announcement'
import { DELIVERY_STATUS } from './presentation.js'
const emit = defineEmits(['updated'])
const readResource = (path, initialData) => useAsyncResource((params, { signal }) => api.get(path, params, { signal, suppressToast: true }), { initialData })
const configResource = readResource('/config', { initialized: false }), categoryResource = readResource('/categories', [])
const membersResource = readResource('/members', []), peopleResource = readResource('/member-candidates', []), deliveriesResource = readResource('/deliveries', [])
const config = configResource.data, loading = configResource.loading, categories = categoryResource.data, members = membersResource.data
const people = peopleResource.data, deliveries = deliveriesResource.data
const saving = ref(false), tab = ref('config')
const resourceStatus = resource => ({ error: resource.errorMessage.value, loading: resource.loading.value, hasData: resource.hasLoaded.value, paged: false })
const loadCategories = () => categoryResource.load()
const loadMembers = () => membersResource.load()
const columnDefs = [
  { key: 'source', label: '来源' },
  { key: 'sequence', label: '分片' },
  { key: 'status', label: '状态' },
  { key: 'error', label: '处理说明' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('announcement-deliveries', columnDefs)
const newCategory = ref(''), newMember = ref(null), testKey = ref('')
const roles = { viewer: '查看', editor: '编辑', reviewer: '审核', admin: '管理' }
async function load() {
  const success = await configResource.load()
  if (success && config.value.initialized) await Promise.all([loadCategories(), loadMembers(), searchPeople('')])
  return success
}
async function initialize() { await api.post('/initialize'); await load(); emit('updated') }
async function saveConfig() {
  if (configResource.error.value || loading.value || saving.value) return
  saving.value = true
  try { config.value = await api.put('/config', config.value); emit('updated'); msgSuccess('保存') }
  finally { saving.value = false }
}
async function testChannel() {
  try { await confirmAction('将向已保存的公告群发送一条测试文字和一张测试图片。', '发送图文测试', { confirmButtonText: '发送测试', cancelButtonText: '取消' }) } catch { return }
  testKey.value = (await api.post('/channel-test')).test_key
  msgSuccess('加入测试发送队列')
}
async function verify() {
  await api.post('/channel-verify', { test_key: testKey.value, images_visible: true })
  emit('updated'); msgSuccess('确认图文通道'); await configResource.load()
}
async function addCategory() { if (!newCategory.value.trim()) return msgError('请输入类别名称'); await api.post('/categories', { title: newCategory.value }); newCategory.value = ''; await loadCategories(); emit('updated'); msgSuccess('新增类别') }
async function saveCategory(c) { await api.put(`/categories/${c.id}`, c); emit('updated'); msgSuccess('保存类别') }
function searchPeople(q) { return peopleResource.load({ q }, { clear: true }) }
function addMember() {
  if (!newMember.value || members.value.some(m => m.user_id === newMember.value)) return
  members.value.push({ ...people.value.find(p => p.user_id === newMember.value), role: 'viewer' }); newMember.value = null
}
async function saveMembers() { if (membersResource.error.value || membersResource.loading.value) return; await api.put('/members', { members: members.value.map(({ user_id, role }) => ({ user_id, role })) }); await load(); msgSuccess('保存成员') }
const loadDeliveries = () => deliveriesResource.load()
async function retry(row, markDelivered = false, cancel = false) {
  if (row.status === 'uncertain') {
    try { await confirmAction(cancel ? '已核对群消息，并确认取消这条投递？' : markDelivered ? '已在钉钉群核对这条消息确实送达？' : '请先核对群消息。重发可能产生重复内容，确认继续？', '核实投递结果', { confirmButtonText: '确认', cancelButtonText: '取消' }) } catch { return }
  }
  await api.post(`/deliveries/${row.id}/retry`, { confirm_uncertain: row.status === 'uncertain', mark_delivered: markDelivered, cancel }); await loadDeliveries()
}
watch(tab, value => { if (value === 'deliveries') loadDeliveries() })
onMounted(load)
</script>

<style scoped>
.settings { display: grid; gap: 16px; }
.table-card:fullscreen { overflow: auto; }
.config-form { margin-top: 20px; }
.actions, .category-row, .member-row { display: flex; align-items: center; gap: 12px; margin: 16px 0; flex-wrap: wrap; }
.actions .el-input { max-width: 320px; }
.category-row .el-input { flex: 1; min-width: 160px; }
.member-row > span { min-width: 130px; }
.member-row .el-select { width: 140px; }
p, small { color: var(--text-secondary); line-height: 1.7; }
.el-form-item span, .el-form-item small { margin-left: 12px; }
</style>
