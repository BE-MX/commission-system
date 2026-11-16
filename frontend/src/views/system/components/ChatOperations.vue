<template>
  <section v-loading="loading" class="chat-operations">
    <div class="operations-toolbar">
      <el-date-picker v-model="range" class="operations-date" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" />
      <el-button :disabled="loading" @click="load">查询</el-button>
      <span>北京时间 · 最多 93 天</span>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="report">
      <div class="operations-metrics">
        <div><span>生成请求</span><strong>{{ report.totals.requests }}</strong></div>
        <div><span>完成 / 失败 / 停止</span><strong>{{ report.totals.completed }} / {{ report.totals.failed }} / {{ report.totals.stopped }}</strong></div>
        <div><span>输入 / 输出 token</span><strong>{{ report.totals.input_tokens }} / {{ report.totals.output_tokens }}</strong></div>
        <div><span>平均首帧 / 总耗时</span><strong>{{ seconds(report.totals.avg_first_token_ms) }} / {{ seconds(report.totals.avg_duration_ms) }}</strong></div>
      </div>
      <p class="operations-note">已报告完整 token：{{ report.totals.token_requests }} 次；未计价：{{ report.totals.unpriced_requests }} 次。估算费用：{{ costs(report.totals) }}。不同币种分别统计，以供应商账单为准。</p>
      <el-tabs>
        <el-tab-pane label="按模型">
          <el-table :data="report.models" border class="list-table" v-sticky-scrollbar>
            <el-table-column label="模型" min-width="180"><template #default="{ row }">{{ row.label }}<small>{{ row.model }}</small></template></el-table-column>
            <el-table-column prop="requests" label="请求" min-width="85" />
            <el-table-column prop="failed" label="失败" min-width="85" />
            <el-table-column label="失败率" min-width="100"><template #default="{ row }">{{ row.failure_rate == null ? '—' : `${(row.failure_rate * 100).toFixed(1)}%` }}</template></el-table-column>
            <el-table-column prop="input_tokens" label="输入 token" min-width="120" />
            <el-table-column prop="output_tokens" label="输出 token" min-width="120" />
            <el-table-column label="估算费用" min-width="140"><template #default="{ row }">{{ costs(row) }}</template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="按用户">
          <el-table :data="report.users" border class="list-table" v-sticky-scrollbar>
            <el-table-column prop="name" label="用户" min-width="140" />
            <el-table-column prop="requests" label="请求" min-width="90" />
            <el-table-column prop="failed" label="失败" min-width="90" />
            <el-table-column prop="input_tokens" label="输入 token" min-width="110" />
            <el-table-column prop="output_tokens" label="输出 token" min-width="110" />
            <el-table-column label="估算费用" min-width="140"><template #default="{ row }">{{ costs(row) }}</template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="按日期">
          <el-table :data="report.days" border class="list-table" v-sticky-scrollbar>
            <el-table-column prop="day" label="日期" min-width="130" />
            <el-table-column prop="requests" label="请求" min-width="80" />
            <el-table-column prop="completed" label="完成" min-width="80" />
            <el-table-column prop="failed" label="失败" min-width="80" />
            <el-table-column prop="stopped" label="停止" min-width="80" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </template>
    <h3>角色每日额度</h3>
    <p class="operations-note">未配置时使用默认 {{ limits.default_limit }} 次；多个角色取已配置额度中的最小值。0 表示暂停生成，停止或失败也占一次。删除会话不返还额度。</p>
    <el-table :data="limits.items" border class="list-table" v-sticky-scrollbar>
      <el-table-column prop="label" label="角色" min-width="120" />
      <el-table-column label="每日次数" min-width="190"><template #default="{ row }">
        <el-input-number v-model="row.daily_limit" :min="0" :max="10000" :precision="0" placeholder="默认" :disabled="saving === row.role_id" aria-label="角色每日次数" />
      </template></el-table-column>
      <el-table-column label="操作" min-width="170"><template #default="{ row }">
        <el-button v-permission="'ai:admin'" :loading="saving === row.role_id" :disabled="saving != null" @click="save(row)">保存</el-button>
        <el-button v-permission="'ai:admin'" link :disabled="saving != null" @click="save(row, true)">恢复默认</el-button>
      </template></el-table-column>
    </el-table>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getChatUsage, getChatRoleLimits, setChatRoleLimit } from '@/api/aiChat'
import { msgError, msgSuccess } from '@/utils/feedback'
const range = ref(null)
const report = ref(null)
const limits = ref({ items: [], default_limit: 100 })
const loading = ref(false)
const saving = ref(null)
const error = ref('')
const seconds = value => value == null ? '未知' : `${(value / 1000).toFixed(1)}s`
const costs = row => Object.entries(row.estimated_costs || {}).map(([currency, value]) => `${currency} ${value}`).join(' · ') || '未计价'
async function load() {
  loading.value = true
  error.value = ''
  try {
    const [usage, roles] = await Promise.all([getChatUsage(range.value ? { start: range.value[0], end: range.value[1] } : {}), getChatRoleLimits()])
    report.value = usage.data
    range.value = [usage.data.start, usage.data.end]
    limits.value = roles.data
  } catch (failure) {
    error.value = failure?.response?.data?.detail || '运行情况加载失败，请重试'
    report.value = null
  } finally { loading.value = false }
}
async function save(row, reset = false) {
  saving.value = row.role_id
  try {
    limits.value = (await setChatRoleLimit(row.role_id, reset ? null : row.daily_limit ?? null)).data
    msgSuccess('额度已保存')
  } catch (failure) { msgError('额度保存失败，请重试', failure) }
  finally { saving.value = null }
}
onMounted(load)
</script>

<style scoped>
.operations-toolbar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-bottom: 16px; }
.operations-date { max-width: 100%; }
.operations-toolbar > span, .operations-note, small { color: var(--text-secondary); font-size: 13px; }
.operations-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 20px 0; }
.operations-metrics > div { padding: 16px; border: 1px solid var(--border-color); border-radius: 8px; }
.operations-metrics span, .operations-metrics strong, small { display: block; }
.operations-metrics strong { margin-top: 8px; font-size: 20px; color: var(--text-primary); }
.operations-note { line-height: 1.7; }
</style>
