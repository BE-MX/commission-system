<template>
  <div class="workspace-monitor">
    <section class="lg-card panel">
      <h3>监控订阅 <span class="hint">调度开关与采集状态分列；暂停不清历史</span></h3>
      <div class="toolbar">
        <el-button type="primary" v-permission="'customer_pcw:write'" @click="dialogVisible = true">新增订阅</el-button>
      </div>
      <el-empty v-if="!subscriptions.length" description="未配置监控来源" :image-size="60" />
      <el-table class="list-table" v-else :data="subscriptions" size="small" border>
        <el-table-column prop="channel" label="渠道" min-width="100" />
        <el-table-column prop="url" label="URL" min-width="180" show-overflow-tooltip />
        <el-table-column label="采集状态" min-width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTagType(row.collection_status)">
              {{ MONITOR_COLLECTION_STATUS_LABELS[row.collection_status] || row.collection_status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_success_at" label="最近成功" min-width="160" />
        <el-table-column prop="last_error" label="最近失败" min-width="120" show-overflow-tooltip />
        <el-table-column label="操作" min-width="170" class-name="table-action-column" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" v-permission="'customer_pcw:write'" @click="toggleEnabled(row)">
              {{ row.enabled ? '暂停' : '恢复' }}
            </GlassButton>
            <GlassButton variant="link" v-permission="'customer_pcw:write'" @click="runOnce(row)">采集</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="lg-card panel">
      <h3>变化事件</h3>
      <el-empty v-if="!events.length" description="暂无事件（首次采集只建基线）" :image-size="60" />
      <el-table class="list-table" v-else :data="events" size="small" border>
        <el-table-column prop="event_type" label="类型" min-width="110" />
        <el-table-column prop="title" label="标题" min-width="150" show-overflow-tooltip />
        <el-table-column prop="discovered_at" label="发现时间" min-width="160" />
        <el-table-column label="状态" min-width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ MONITOR_EVENT_STATUS_LABELS[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="150" class-name="table-action-column" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'pending'">
              <GlassButton variant="link" v-permission="'customer_pcw:write'" @click="decide(row, 'confirm')">确认</GlassButton>
              <GlassButton variant="link" v-permission="'customer_pcw:write'" @click="decide(row, 'ignore')">忽略</GlassButton>
            </template>
            <span v-else class="hint">{{ row.action_id ? `行动 #${row.action_id}` : '—' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialogVisible" title="新增监控订阅" min-width="480px" class="customer-hub-dialog">
      <el-form label-width="72px" size="small">
        <el-form-item label="渠道">
          <el-select v-model="form.channel" style="width: 100%">
            <el-option value="website" label="官网" />
            <el-option value="instagram" label="Instagram" />
            <el-option value="facebook" label="Facebook" />
            <el-option value="linkedin" label="LinkedIn" />
            <el-option value="news" label="新闻页" />
          </el-select>
        </el-form-item>
        <el-form-item label="URL">
          <el-input v-model="form.url" placeholder="https://..." />
        </el-form-item>
        <el-form-item label="频率">
          <el-input-number v-model="form.interval_days" :min="1" :max="90" />
          <span class="hint">天/次</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitSubscription">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import {
  createMonitorSubscription, decideMonitorEvent,
  listMonitorEvents, listMonitorSubscriptions, patchMonitorSubscription, runMonitorSubscription,
} from '@/api/customerHub'
import { msgSuccess, confirmDanger } from '@/utils/feedback'
import {
  MONITOR_COLLECTION_STATUS_LABELS, MONITOR_EVENT_STATUS_LABELS,
  buildEventDecisionPayload, buildSubscriptionPayload,
} from '../customerWorkspaceController'

const props = defineProps({ customerId: { type: Number, required: true }, customer: { type: Object, default: null } })
const subscriptions = ref([])
const events = ref([])
const dialogVisible = ref(false)
const form = reactive({ channel: 'website', url: '', interval_days: 7 })

function statusTagType(status) {
  return { baseline: 'info', active: 'success', failed: 'danger', restricted: 'warning' }[status] || 'info'
}

async function loadAll() {
  try {
    const [subRes, eventRes] = await Promise.all([
      listMonitorSubscriptions(props.customerId),
      listMonitorEvents(props.customerId, {}),
    ])
    subscriptions.value = subRes.data?.items ?? subRes.data ?? []
    events.value = eventRes.data?.items ?? []
  } catch { /* 拦截器已提示 */ }
}

async function submitSubscription() {
  try {
    await createMonitorSubscription(
      props.customerId,
      buildSubscriptionPayload(form),
      `monitor-sub-${Date.now()}`,
    )
    msgSuccess('订阅已创建；首次采集只建立基线')
    dialogVisible.value = false
    form.url = ''
    await loadAll()
  } catch { /* 拦截器已提示（含 URL_NOT_ALLOWED） */ }
}

async function toggleEnabled(row) {
  try {
    await patchMonitorSubscription(row.id, {
      expected_subscription_version: row.row_version, enabled: !row.enabled,
    }, `monitor-toggle-${row.id}-${Date.now()}`)
    msgSuccess(row.enabled ? '已暂停（历史与水位保留）' : '已恢复')
    await loadAll()
  } catch { /* 拦截器已提示 */ }
}

async function runOnce(row) {
  try {
    await runMonitorSubscription(row.id, `monitor-run-${row.id}-${Date.now()}`)
    msgSuccess('采集已执行')
    await loadAll()
  } catch { /* 拦截器已提示 */ }
}

async function decide(row, operation) {
  if (operation === 'ignore') {
    const reason = window.prompt('忽略原因（必填）', '')
    if (!reason || !reason.trim()) return
    try {
      await decideMonitorEvent(row.id, buildEventDecisionPayload(operation, {
        expected_event_version: row.row_version, reason,
      }), `event-${row.id}-${Date.now()}`)
      msgSuccess('已忽略')
      await loadAll()
    } catch { return }
    return
  }
  const confirmed = await confirmDanger('确认该事件并生成跟进任务？')
  if (!confirmed) return
  try {
    await decideMonitorEvent(row.id, buildEventDecisionPayload(operation, {
      expected_event_version: row.row_version,
    }), `event-${row.id}-${Date.now()}`)
    msgSuccess('已确认并生成任务')
    await loadAll()
  } catch { /* 拦截器已提示 */ }
}

onMounted(loadAll)
</script>

<style scoped>
.workspace-monitor { display: grid; gap: 14px; }
.panel { padding: 14px 16px; }
.panel h3 { margin: 0 0 10px; font-size: 14px; }
.hint { font-size: 12px; color: var(--text-muted); font-weight: normal; }
.toolbar { margin-bottom: 10px; }
</style>
