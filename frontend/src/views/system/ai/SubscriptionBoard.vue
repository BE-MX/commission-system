<template>
  <section class="sub-board">
    <div v-if="showMergeNotice" class="merge-notice">
      <span>原「提供商管理」已并入本页，卡片与表格共用同一份配置；顶部统计已统一收敛至下方汇总条。</span>
      <el-button link @click="$emit('dismiss-notice')">关闭</el-button>
    </div>

    <!-- 顶部 5 张概览卡（复用 OverviewMetricCard；390px 横向滚动） -->
    <div class="sub-summary">
      <OverviewMetricCard
        label="本月调用估算"
        :value="monthPrimaryText"
        :icon="Wallet"
        tone="gold"
        :hint="monthHintText"
      />
      <OverviewMetricCard
        label="上线后累计调用"
        :value="totalPrimaryText"
        :icon="DataLine"
        tone="info"
        :hint="totalHintText"
      />
      <OverviewMetricCard
        label="在用订阅"
        :value="`${summary.active_count} 个`"
        :icon="CircleCheck"
        tone="success"
        :hint="`共 ${summary.total_providers} 个订阅源 · 不含待确认续费与停用`"
      />
      <OverviewMetricCard
        label="续费提醒"
        :value="`${summary.renew_alert_count} 个`"
        :icon="Clock"
        tone="warning"
        :hint="'待确认续费或 7 天内到期 · 点击筛选'"
        interactive
        :selected="filters.statusFilter === 'renew_alert'"
        @click="$emit('toggle-status', 'renew_alert')"
      />
      <OverviewMetricCard
        label="余额预警"
        :value="`${summary.balance_alert_count} 个`"
        :icon="WarningFilled"
        tone="danger"
        :hint="'独立维度统计（不被续费状态遮蔽）· 点击筛选'"
        interactive
        :selected="filters.statusFilter === 'balance_alert'"
        @click="$emit('toggle-status', 'balance_alert')"
      />
    </div>

    <!-- 状态 Chip 筛选行 -->
    <div class="sub-chip-bar">
      <button
        v-for="chip in statusChips"
        :key="chip.key"
        type="button"
        class="filter-chip"
        :class="{ 'is-on': filters.statusFilter === chip.key }"
        @click="filters.statusFilter = chip.key"
      >
        {{ chip.label }}<span class="filter-chip__n">{{ chip.count }}</span>
      </button>
    </div>

    <!-- 工具栏 -->
    <div class="sub-toolbar">
      <el-select v-model="filters.serviceKind" placeholder="全部接入类型" clearable class="w-kind">
        <el-option label="直连官方" value="official" />
        <el-option label="中转站" value="relay" />
        <el-option label="ACCIO WORK" value="accio_work" />
      </el-select>
      <el-select v-model="filters.apiType" placeholder="全部协议" clearable class="w-proto">
        <el-option label="OpenAI" value="openai" />
        <el-option label="Anthropic" value="anthropic" />
      </el-select>
      <el-input v-model="filters.search" placeholder="搜索名称、API Base 或模型名" clearable class="w-search" />
      <el-select v-model="filters.sort" class="w-sort">
        <el-option label="按到期日（近的在前）" value="renew" />
        <el-option label="按余额剩余占比（低的在前）" value="balance" />
        <el-option label="按本月消费（同币种降序）" value="month" />
      </el-select>
      <el-checkbox v-model="filters.hideDisabled">隐藏已停用</el-checkbox>
      <span class="sub-spacer" />
      <el-radio-group :model-value="viewMode" size="small" @update:model-value="$emit('update:viewMode', $event)">
        <el-radio-button value="card">卡片</el-radio-button>
        <el-radio-button value="table">表格</el-radio-button>
      </el-radio-group>
      <GlassButton v-permission="'ai:admin'" variant="primary" left-icon="Plus" @click="$emit('add')">
        新增订阅源
      </GlassButton>
    </div>

    <p class="sub-disclaimer">费用由方舟按单价估算，以供应商账单为准；跨币种分列展示，不换算。</p>

    <ListPageStatus v-if="hasError" :error="errorMessage" :loading="loading" :has-data="items.length > 0" @retry="$emit('refresh')" />

    <!-- 卡片视图 -->
    <div v-if="viewMode === 'card'" v-loading="loading" class="sub-grid">
      <SubscriptionCard
        v-for="item in items"
        :key="item.id"
        :item="item"
        :logo-url="logoUrls[item.id] || ''"
        @confirm-renew="$emit('confirm-renew', $event)"
        @register-balance="$emit('register-balance', $event)"
        @edit="$emit('edit', $event)"
        @test="$emit('test', $event)"
        @view-logs="$emit('view-logs', $event)"
        @toggle="$emit('toggle', $event)"
        @delete="$emit('delete', $event)"
      />
    </div>

    <!-- 表格视图（完整保留旧提供商管理能力） -->
    <el-table
      v-else
      v-loading="loading"
      :data="items"
      border
      class="list-table"
      max-height="640"
      v-sticky-scrollbar
    >
      <el-table-column prop="id" label="ID" min-width="60" />
      <el-table-column label="名称 / 接入" min-width="170">
        <template #default="{ row }">
          <div class="tbl-title">{{ row.name }}</div>
          <div class="tbl-sub">{{ row.service_kind === 'relay' ? '中转站' : (row.service_kind === 'accio_work' ? 'ACCIO WORK' : '直连官方') }}</div>
        </template>
      </el-table-column>
      <el-table-column label="协议" min-width="100">
        <template #default="{ row }">
          <StatusBadge v-if="row.provider_type === 'direct'" :type="row.api_type === 'anthropic' ? 'warning' : 'info'" size="small" effect="plain">
            {{ row.api_type === 'anthropic' ? 'Anthropic' : 'OpenAI' }}
          </StatusBadge>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="API Base / Key" min-width="230">
        <template #default="{ row }">
          <div class="mono-text">{{ row.api_base }}</div>
          <div class="key-row">
            <span class="mono-text">{{ showKeyMap[row.id] ? row.api_key : (row.api_key ? '****' : '-') }}</span>
            <el-button v-if="row.api_key" link @click="$emit('toggle-key', row.id)">
              <el-icon><component :is="showKeyMap[row.id] ? 'Hide' : 'View'" /></el-icon>
            </el-button>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="续费 / 余额" min-width="170">
        <template #default="{ row }">
          <template v-if="row.provider_type === 'accio_work'">
            <div class="tbl-sub">内部通道不计费</div>
          </template>
          <template v-else>
            <div v-if="row.balance?.currency_mismatch">
              <StatusBadge type="warning" size="small" effect="plain">异币种不可估算</StatusBadge>
            </div>
            <div v-else class="num">{{ row.balance?.has_checkpoint ? formatMoney(row.balance.estimated_amount, row.balance.currency) : '未登记余额' }}</div>
            <div class="tbl-sub">{{ row.renew ? `续费 ${row.renew.renew_at}` : '无续费日' }}</div>
          </template>
        </template>
      </el-table-column>
      <el-table-column label="本月调用" min-width="120" align="right">
        <template #default="{ row }">
          <span class="num">{{ formatSpendList(row.spend?.month) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="启用" min-width="76">
        <template #default="{ row }">
          <el-switch :model-value="row.is_enabled" @change="$emit('toggle', row)" />
        </template>
      </el-table-column>
      <el-table-column class-name="table-action-column" label="操作" min-width="230" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" :loading="testingId === row.id" @click="$emit('test', row)">测试</el-button>
          <el-button v-if="row.provider_type !== 'accio_work'" link type="primary" @click="$emit('register-balance', row)">余额</el-button>
          <el-button link type="primary" @click="$emit('edit', row)">编辑</el-button>
          <el-button link type="danger" @click="$emit('delete', row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && items.length === 0" description="没有符合条件的订阅源" :image-size="88" />
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { CircleCheck, Clock, DataLine, Wallet, WarningFilled } from '@element-plus/icons-vue'
import OverviewMetricCard from '@/components/OverviewMetricCard.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import { formatMoney as fmtMoney } from '@/utils/money'
import SubscriptionCard from './SubscriptionCard.vue'

const props = defineProps({
  summary: { type: Object, required: true },
  items: { type: Array, required: true },
  filters: { type: Object, required: true },
  viewMode: { type: String, default: 'card' },
  loading: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
  showMergeNotice: { type: Boolean, default: false },
  logoUrls: { type: Object, default: () => ({}) },
  showKeyMap: { type: Object, default: () => ({}) },
  testingId: { type: [Number, null], default: null },
})

defineEmits([
  'update:viewMode', 'dismiss-notice', 'toggle-status', 'refresh', 'add',
  'confirm-renew', 'register-balance', 'edit', 'test', 'view-logs', 'toggle', 'delete', 'toggle-key',
])

const SYM = { CNY: '¥', USD: '$' }
const hasError = computed(() => Boolean(props.errorMessage))

function formatMoney(val, cur = 'CNY') {
  if (val == null) return '—'
  return `${SYM[cur] || `${cur} `}${fmtMoney(val, 2)}`
}

function formatSpendList(list) {
  if (!list || !list.length) return '¥0.00'
  return list.map(entry => formatMoney(entry.amount, entry.currency)).join(' + ')
}

const monthPrimaryText = computed(() => formatSpendList(props.summary.month_spend))
const monthHintText = computed(() => {
  const fixed = props.summary.fixed_subscriptions_monthly || []
  const fixedTxt = fixed.length ? formatSpendList(fixed) : '无固定套餐'
  return `在用固定订阅月折算：${fixedTxt}（不混算）`
})

const totalPrimaryText = computed(() => formatSpendList(props.summary.total_spend))
const totalHintText = computed(() => {
  const unpriced = props.summary.unpriced_count || 0
  return `含 ${unpriced} 次未定价（未计入）· 含停用/历史总账`
})

const statusChips = computed(() => [
  { key: 'all', label: '全部', count: props.summary.total_providers || 0 },
  { key: 'renew_alert', label: '续费提醒', count: props.summary.renew_alert_count || 0 },
  { key: 'balance_alert', label: '余额预警', count: props.summary.balance_alert_count || 0 },
  { key: 'disabled', label: '已停用', count: props.summary.disabled_count || 0 },
])
</script>

<style scoped>
.sub-board { display: flex; flex-direction: column; gap: 14px; }
.merge-notice {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 9px 14px; border-radius: 10px;
  background: var(--tag-gold-bg); border: 1px solid var(--tag-gold-border);
  color: var(--tag-gold-text); font-size: 13px;
}
.sub-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.sub-chip-bar { display: flex; flex-wrap: wrap; gap: 8px; }
.filter-chip {
  border: 1px solid var(--border-color); background: var(--card-bg);
  border-radius: 999px; padding: 5px 12px; font-size: 13px; cursor: pointer;
  color: var(--text-primary); white-space: nowrap;
  transition: background-color var(--motion-fast) ease, border-color var(--motion-fast) ease, color var(--motion-fast) ease;
}
.filter-chip__n { margin-left: 4px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.filter-chip.is-on { background: var(--tag-gold-bg); border-color: var(--tag-gold-solid); color: var(--tag-gold-text); font-weight: 600; }
.filter-chip.is-on .filter-chip__n { color: var(--tag-gold-text); }
.sub-toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.w-kind { width: 130px; }
.w-proto { width: 120px; }
.w-search { width: 210px; }
.w-sort { width: 190px; }
.sub-spacer { flex: 1; min-width: 12px; }
.sub-disclaimer { margin: -4px 0 0; font-size: 12px; color: var(--text-muted); }
.sub-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 14px; }
.tbl-title { font-weight: 600; color: var(--text-primary); }
.tbl-sub { font-size: 12px; color: var(--text-muted); }
.mono-text { font-family: var(--font-mono); font-size: 12px; }
.key-row { display: flex; align-items: center; gap: 4px; }
.num { font-variant-numeric: tabular-nums; }

@media (max-width: 1180px) {
  .sub-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .sub-summary {
    display: flex; overflow-x: auto; gap: 10px; padding-bottom: 4px;
    scroll-snap-type: x mandatory; -webkit-overflow-scrolling: touch;
  }
  .sub-summary > :deep(*) { flex: 0 0 210px; scroll-snap-align: start; }
  .sub-grid { grid-template-columns: 1fr; }
  .w-kind, .w-proto, .w-search, .w-sort { width: 100%; }
}
</style>
