<template>
  <section class="source-settings" v-permission="'alibaba_feed:admin'">
    <p class="muted">精确匹配平台负责人显示名。配置来源不读取聊天正文；采集 token 不能用于此页面登录。开关仅在保存时变更。</p>
    <div class="action-bar"><GlassButton :loading="loading" left-icon="Refresh" @click="load">刷新配置</GlassButton></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table :data="sources" v-loading="loading" border class="list-table" v-sticky-scrollbar>
      <el-table-column prop="name" label="来源" min-width="150" show-overflow-tooltip />
      <el-table-column prop="source_account_uid" label="来源账号" min-width="190" show-overflow-tooltip />
      <el-table-column prop="consent_state" label="授权状态" min-width="120" show-overflow-tooltip />
      <el-table-column label="资料共享 / AI 出站 / 私海资料" min-width="240"><template #default="{ row }">{{ row.crm_shared ? '开' : '关' }} / {{ row.ai_egress_allowed ? '开' : '关' }} / {{ row.private_feed_enabled ? '开' : '关' }}</template></el-table-column>
      <el-table-column prop="version" label="版本" min-width="80" />
      <el-table-column label="身份闸门" min-width="150"><template #default="{ row }"><StatusBadge size="small" effect="plain" :type="row.legacy_identity_blocked ? 'warning' : 'info'">{{ row.legacy_identity_blocked ? '旧身份已阻断' : '按规则核验' }}</StatusBadge></template></el-table-column>
      <el-table-column label="操作" class-name="table-action-column" min-width="100" fixed="right"><template #default="{ row }"><GlassButton variant="link" left-icon="Setting" @click="edit(row)" :disabled="saving || uncertain">配置</GlassButton></template></el-table-column>
    </el-table>
    <el-dialog :model-value="!!editing" @update:model-value="v => { if (!v && !saving) editing = null }" title="来源配置" width="640px" :close-on-click-modal="!saving" :close-on-press-escape="!saving" destroy-on-close>
      <template v-if="editing">
        <p>{{ editing.name }} · 版本 {{ editing.version }}</p>
        <el-alert title="自动规则保持关闭；采集能力的核验结果仅供查看，不在此开启自动经营。" type="info" :closable="false" />
        <p class="muted">采集能力版本 {{ editing.capability_version ?? '—' }} · {{ editing.legacy_identity_blocked ? '旧身份已阻断' : '旧身份未阻断' }}</p>
        <p class="muted">已核验：{{ capabilities(editing) }}</p>
        <p v-if="editing.verified_capabilities?.evidence_note" class="evidence-note">核验依据：{{ editing.verified_capabilities.evidence_note }}</p>
        <el-form label-position="top">
          <el-form-item label="精确显示名 → 方舟业务员">
            <div class="aliases">
              <div v-for="(alias, index) in aliases" :key="index" class="alias-row">
                <el-input v-model="alias.name" placeholder="平台完整显示名（精确匹配）" aria-label="平台完整显示名" />
                <el-select v-model="alias.userId" filterable placeholder="选择业务员" aria-label="映射方舟业务员"><el-option v-for="owner in owners" :key="owner.id" :label="owner.real_name || owner.username" :value="owner.id" /></el-select>
                <GlassButton variant="link" link-tone="danger" @click="aliases.splice(index, 1)" :disabled="saving">移除</GlassButton>
              </div>
              <GlassButton @click="aliases.push({ name: '', userId: null })" :disabled="saving">添加精确映射</GlassButton>
            </div>
          </el-form-item>
          <el-form-item label="业务资料共享"><el-switch v-model="editing.crm_shared" :disabled="saving" /></el-form-item>
          <el-form-item label="允许 AI 出站"><el-switch v-model="editing.ai_egress_allowed" :disabled="saving" /></el-form-item>
          <el-form-item label="开放本人私海 TM 资料"><el-switch v-model="editing.private_feed_enabled" :disabled="saving" /></el-form-item>
        </el-form>
        <el-alert v-if="saveError" :title="saveError" type="error" :closable="false" />
      </template>
      <template #footer><GlassButton :disabled="saving" @click="editing = null">取消</GlassButton><GlassButton variant="primary" :loading="saving" :disabled="uncertain" @click="save">保存配置</GlassButton></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { alibabaFeedApi as api } from '@/api/alibabaFeed'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { msgSuccessText } from '@/utils/feedback'
import { createReadScope } from './feedState'
const auth = useAuthStore()
const sources = ref([]), owners = ref([]), loading = ref(false), error = ref('')
const editing = ref(null), aliases = ref([]), saving = ref(false), saveError = ref(''), uncertain = ref(false)
const scope = createReadScope()
let authority = 0
function capabilities(row) {
  const labels = { stable_message_ids: '稳定消息标识', reliable_order: '可靠顺序', latest_coverage: '最新消息覆盖', human_identity: '人工身份', activity_scan: '活跃扫描', deletions: '删除覆盖' }
  return Object.entries(labels).filter(([key]) => row.verified_capabilities?.[key] === true).map(([, label]) => label).join('、') || '尚无已核验能力'
}
async function load() {
  if (!auth.hasPermission('alibaba_feed:admin')) return
  const read = scope.begin(); loading.value = true; error.value = ''; sources.value = []; owners.value = []
  try {
    const [sourceData, ownerData] = await Promise.all([api.sources(read.signal), api.owners(read.signal)])
    if (read.isCurrent()) { sources.value = sourceData.items; owners.value = ownerData.items }
  } catch (failure) { if (read.isCurrent()) error.value = errorMessage(failure) }
  finally { if (read.isCurrent()) loading.value = false }
}
function edit(row) {
  editing.value = { ...row }; saveError.value = ''
  aliases.value = Object.entries(row.owner_aliases || {}).map(([name, userId]) => ({ name, userId }))
}
async function save() {
  if (!editing.value || saving.value || uncertain.value || !auth.hasPermission('alibaba_feed:admin')) return
  const names = aliases.value.map(item => item.name)
  if (aliases.value.some(item => !item.name.trim() || !owners.value.some(owner => owner.id === item.userId)) || new Set(names).size !== names.length) {
    saveError.value = '请为每个完整显示名选择有效业务员，显示名不可重复。'; return
  }
  const current = authority, row = editing.value
  saving.value = true; saveError.value = ''
  try {
    await api.saveSource(row.source_account_uid, {
      expected_version: row.version, owner_aliases: Object.fromEntries(aliases.value.map(item => [item.name, item.userId])),
      crm_shared: row.crm_shared, ai_egress_allowed: row.ai_egress_allowed, private_feed_enabled: row.private_feed_enabled,
    })
    if (current !== authority) return
    editing.value = null; msgSuccessText('来源配置已保存'); await load()
  } catch (failure) {
    if (current !== authority) return
    uncertain.value = !failure.response || failure.response.status >= 500
    saveError.value = uncertain.value ? '保存结果待核对，未自动重试。请关闭窗口并刷新配置核对；重新进入页面后再编辑。' : errorMessage(failure)
    if ([401, 403].includes(failure.response?.status)) { editing.value = null; sources.value = []; owners.value = [] }
  } finally { if (current === authority) saving.value = false }
}
watch(() => JSON.stringify([auth.user?.id, auth.permissions, auth.roles]), () => {
  authority += 1; scope.clear(); sources.value = []; owners.value = []; editing.value = null; aliases.value = []; saving.value = false
}, { flush: 'sync' })
onMounted(load)
onUnmounted(() => { authority += 1; scope.clear(); sources.value = []; owners.value = [] })
</script>

<style scoped>
.muted { color: var(--text-secondary); }
.evidence-note { white-space: pre-wrap; overflow-wrap: anywhere; }
.source-settings { padding: 18px; }
.aliases { display: grid; gap: 12px; width: 100%; }
.alias-row { display: flex; gap: 8px; align-items: center; }
.alias-row > .el-input, .alias-row > .el-select { min-width: 0; flex: 1; }
@media (max-width: 600px) { .alias-row { flex-wrap: wrap; } }
</style>
