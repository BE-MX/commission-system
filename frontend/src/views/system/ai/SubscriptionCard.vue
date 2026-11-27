<template>
  <article class="sub-card lg-card is-static" :class="`sub-card--${cardTone}`">
    <div class="sub-card__head">
      <div class="sub-card__logo" :class="{ 'is-img': Boolean(logoUrl) }" :style="!logoUrl ? { background: avatarColor } : undefined">
        <img v-if="logoUrl" :src="logoUrl" :alt="item.name" />
        <span v-else aria-hidden="true">{{ initialChar }}</span>
      </div>
      <div class="sub-card__title-wrap">
        <div class="sub-card__name" :title="item.name">{{ item.name }}</div>
        <div class="sub-card__sub">{{ subMeta }}</div>
      </div>
      <div class="sub-card__badges">
        <span class="sub-tag" :class="`sub-tag--${statusTone(item.status)}`">{{ statusLabel(item.status) }}</span>
        <span
          v-for="flag in item.secondary_flags || []"
          :key="flag"
          class="sub-tag"
          :class="`sub-tag--${statusTone(flag)}`"
        >{{ statusLabel(flag) }}</span>
      </div>
    </div>

    <div class="sub-card__models" aria-label="下挂模型">
      <template v-if="item.models && item.models.length">
        <span v-for="m in item.models.slice(0, 4)" :key="m" class="model-chip">{{ m }}</span>
        <span v-if="item.models.length > 4" class="model-chip">+{{ item.models.length - 4 }}</span>
      </template>
      <span v-else class="sub-unset">未配置启用预设</span>
    </div>

    <!-- 内部不计费通道（如 ACCIO WORK）紧凑摘要 -->
    <div v-if="isInternal" class="sub-card__block">
      <div class="internal-summary">
        <div>
          <span class="sub-label">费用口径</span>
          <strong class="internal-val">内部通道不计费</strong>
        </div>
        <div>
          <span class="sub-label">本月调用</span>
          <strong class="internal-val num">{{ item.spend?.month_calls ?? 0 }} 次</strong>
        </div>
      </div>
    </div>

    <template v-else>
      <!-- 周期 / 续费段（正交可选：登记了 renew_at 即展示） -->
      <div v-if="item.renew" class="sub-card__block">
        <div class="sub-row">
          <span class="sub-label">下次续费 {{ item.renew.renew_at.slice(5) }}</span>
          <span class="sub-renew-txt num" :class="{ 'is-warn': Boolean(item.renew_flag) }">
            {{ item.renew.days_left < 0
              ? `已过续费日 ${Math.abs(item.renew.days_left)} 天 · 待确认`
              : `剩 ${item.renew.days_left} 天（已过 ${item.renew.elapsed_pct}%）` }}
          </span>
        </div>
        <div class="bar-track" :aria-label="`本周期已过 ${item.renew.elapsed_pct}%`">
          <div
            class="bar-fill"
            :class="item.renew_flag ? 'bar-fill--warn' : 'bar-fill--ok'"
            :style="{ width: `${item.renew.elapsed_pct}%` }"
          />
        </div>
        <div class="sub-hint">
          {{ item.billing?.plan_name || billingModeLabel }}
          <template v-if="item.billing?.price_amount != null">
            · {{ formatMoney(item.billing.price_amount, item.billing.price_currency) }} / {{ cycleUnit }}
          </template>
        </div>
      </div>

      <!-- 余额段（正交可选：登记过余额流水即展示） -->
      <div v-if="item.balance?.has_checkpoint" class="sub-card__block">
        <div class="sub-row">
          <span class="sub-label">余额（{{ item.balance.deduct_by_usage ? '估算' : '固定不扣减' }}）</span>
          <span v-if="item.balance.currency_mismatch" class="sub-tag sub-tag--warn">异币种不可估算</span>
          <span v-else class="sub-val num">{{ formatMoney(item.balance.estimated_amount, item.balance.currency) }}</span>
        </div>
        <template v-if="item.balance.currency_mismatch">
          <div class="sub-hint">登记后存在其他币种已计费调用，余额估算不可用，请核对账单后重新登记。</div>
        </template>
        <template v-else>
          <div class="bar-track" :aria-label="`较上次登记剩 ${item.balance.remaining_pct}%`">
            <div
              class="bar-fill"
              :class="balanceBarClass"
              :style="{ width: `${item.balance.remaining_pct ?? 0}%` }"
            />
            <span
              v-if="item.balance.threshold_pct != null"
              class="bar-mark"
              :style="{ left: `${item.balance.threshold_pct}%` }"
              :title="`预警线 ${formatMoney(item.balance.threshold, item.balance.currency)}`"
            />
          </div>
          <div class="sub-hint">
            较上次登记（{{ formatMoney(item.balance.base_amount, item.balance.currency) }}）剩 {{ item.balance.remaining_pct }}%
            <template v-if="item.balance.threshold != null">
              · 预警 {{ formatMoney(item.balance.threshold, item.balance.currency) }}
            </template>
            <template v-if="item.balance.is_stale">
              · <span class="sub-tag sub-tag--warn">登记 {{ item.balance.stale_days }} 天前，建议核对</span>
            </template>
            <template v-else-if="item.balance.recorded_at">
              · 核对于 {{ item.balance.recorded_at.slice(5, 16).replace('T', ' ') }}
            </template>
            <template v-if="item.balance.inflight_count > 0">
              · 含 {{ item.balance.inflight_count }} 次在途未计入
            </template>
          </div>
        </template>
      </div>

      <!-- 消费段 -->
      <div class="sub-card__block sub-spend">
        <div>
          <div class="sub-label">本月调用估算</div>
          <div class="sub-val num">{{ formatSpendList(item.spend?.month) }}</div>
        </div>
        <div>
          <div class="sub-label">上线后累计</div>
          <div class="sub-val num">{{ formatSpendList(item.spend?.total) }}</div>
        </div>
        <div v-if="item.spend?.unpriced_count > 0" class="sub-hint sub-spend__note">
          含 {{ item.spend.unpriced_count }} 次未定价调用（未计入）
        </div>
      </div>
    </template>

    <!-- 底部外链与操作 -->
    <div class="sub-card__foot">
      <div class="sub-card__links">
        <a v-if="item.billing?.console_url" :href="item.billing.console_url" target="_blank" rel="noopener noreferrer">控制台 ↗</a>
        <span v-else class="sub-unset">无控制台</span>
        <a v-if="item.billing?.docs_url" :href="item.billing.docs_url" target="_blank" rel="noopener noreferrer">文档 ↗</a>
      </div>
      <div class="sub-card__actions">
        <el-button
          v-if="item.renew_flag === 'renew_pending' && item.billing?.billing_mode !== 'pay_as_you_go' && !isInternal"
          v-permission="'ai:admin'"
          type="primary"
          @click="$emit('confirm-renew', item)"
        >已续费</el-button>
        <el-button
          v-if="!isInternal"
          v-permission="'ai:admin'"
          @click="$emit('register-balance', item)"
        >登记余额</el-button>
        <el-button v-permission="'ai:admin'" @click="$emit('edit', item)">编辑</el-button>
        <el-dropdown trigger="click" @command="cmd => $emit(cmd, item)">
          <el-button>更多 ▾</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="test">连通性测试</el-dropdown-item>
              <el-dropdown-item command="view-logs">查看调用日志</el-dropdown-item>
              <el-dropdown-item command="toggle">{{ item.is_enabled ? '停用提供商' : '启用提供商' }}</el-dropdown-item>
              <el-dropdown-item command="delete" divided class="danger-item">删除提供商</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { formatMoney as fmtMoney } from '@/utils/money'

const props = defineProps({
  item: { type: Object, required: true },
  logoUrl: { type: String, default: '' },
})

defineEmits(['confirm-renew', 'register-balance', 'edit', 'test', 'view-logs', 'toggle', 'delete'])

const SYM = { CNY: '¥', USD: '$' }
const STATUS_LABELS = {
  disabled: '已停用',
  renew_pending: '待确认续费',
  renew_soon: '即将到期',
  balance_empty: '余额不足',
  balance_low: '余额偏低',
  healthy: '正常',
}
const STATUS_TONES = {
  disabled: 'neutral',
  renew_pending: 'warn',
  renew_soon: 'warn',
  balance_empty: 'danger',
  balance_low: 'warn',
  healthy: 'ok',
}
const AVATAR_COLORS = [
  'var(--tag-success-solid)',
  'var(--tag-info-solid)',
  'var(--tag-warning-solid)',
  'var(--metric-violet-ink)',
  'var(--tag-gold-text)',
  'var(--tag-neutral-solid)',
]

const isInternal = computed(() => props.item.provider_type === 'accio_work')
const initialChar = computed(() => (props.item.name || '?')[0].toUpperCase())
const avatarColor = computed(() => AVATAR_COLORS[(props.item.id || 0) % AVATAR_COLORS.length])

const cardTone = computed(() => {
  const t = STATUS_TONES[props.item.status] || 'neutral'
  return t === 'ok' ? 'healthy' : t
})

const kindLabel = computed(() => {
  if (props.item.service_kind === 'accio_work') return 'ACCIO WORK'
  return props.item.service_kind === 'relay' ? '中转站' : '直连'
})

const protoLabel = computed(() => {
  if (isInternal.value) return '内部协议'
  return props.item.api_type === 'anthropic' ? 'Anthropic 协议' : 'OpenAI 协议'
})

const subMeta = computed(() => {
  const parts = [kindLabel.value, protoLabel.value]
  if (props.item.billing?.subscribed_at) {
    parts.push(`订阅于 ${props.item.billing.subscribed_at.slice(0, 7).replace('-', '.')}`)
  }
  return parts.join(' · ')
})

const billingModeLabel = computed(() => ({
  monthly: '包月',
  quarterly: '包季',
  yearly: '包年',
  pay_as_you_go: '按量充值',
}[props.item.billing?.billing_mode] || '按量充值'))

const cycleUnit = computed(() => ({
  monthly: '月',
  quarterly: '季',
  yearly: '年',
}[props.item.billing?.billing_mode] || '期'))

const balanceBarClass = computed(() => {
  if (props.item.balance_flag === 'balance_empty') return 'bar-fill--danger'
  if (props.item.balance_flag === 'balance_low') return 'bar-fill--warn'
  return 'bar-fill--ok'
})

function statusLabel(st) { return STATUS_LABELS[st] || st }
function statusTone(st) { return STATUS_TONES[st] || 'neutral' }

function formatMoney(val, cur = 'CNY') {
  if (val == null || val === '') return '未登记'
  const num = Number(val)
  if (Number.isNaN(num)) return String(val)
  return `${SYM[cur] || `${cur} `}${fmtMoney(num, 2)}`
}

function formatSpendList(list) {
  if (!list || !list.length) return '¥0.00'
  return list.map(entry => formatMoney(entry.amount, entry.currency)).join(' + ')
}
</script>

<style scoped>
.sub-card {
  border-top: 3px solid var(--tag-neutral-solid);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition: box-shadow var(--motion-base) var(--ease-out-strong);
}
.sub-card--healthy { border-top-color: var(--tag-success-solid); }
.sub-card--warn { border-top-color: var(--tag-warning-solid); }
.sub-card--danger { border-top-color: var(--tag-danger-solid); }
.sub-card--neutral { opacity: 0.74; }
.sub-card__head { display: flex; gap: 11px; align-items: flex-start; }
.sub-card__logo {
  width: 40px; height: 40px; border-radius: 10px; flex: none;
  display: grid; place-items: center; overflow: hidden;
  color: var(--card-bg); font-family: var(--font-display); font-weight: 800; font-size: 16px;
}
.sub-card__logo.is-img { background: var(--card-bg); border: 1px solid var(--border-color); }
.sub-card__logo img { width: 100%; height: 100%; object-fit: contain; }
.sub-card__title-wrap { min-width: 0; flex: 1; }
.sub-card__name { font-family: var(--font-display); font-weight: 700; font-size: 15px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub-card__sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
.sub-card__badges { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; }
.sub-tag {
  display: inline-flex; align-items: center; font-size: 11px; font-weight: 600;
  border-radius: 6px; padding: 2px 8px; white-space: nowrap; border: 1px solid transparent;
}
.sub-tag--ok { background: var(--tag-success-bg); color: var(--tag-success-text); border-color: var(--tag-success-border); }
.sub-tag--warn { background: var(--tag-warning-bg); color: var(--tag-warning-text); border-color: var(--tag-warning-border); }
.sub-tag--danger { background: var(--tag-danger-bg); color: var(--tag-danger-text); border-color: var(--tag-danger-border); }
.sub-tag--neutral { background: var(--tag-neutral-bg); color: var(--tag-neutral-text); border-color: var(--tag-neutral-border); }
.sub-card__models { display: flex; flex-wrap: wrap; gap: 6px; }
.model-chip {
  font-family: var(--font-mono); font-size: 12px;
  background: var(--tag-neutral-bg); border: 1px solid var(--tag-neutral-border);
  border-radius: 5px; padding: 2px 7px; color: var(--text-secondary);
}
.sub-unset { color: var(--text-muted); font-style: italic; font-size: 12px; }
.sub-card__block { border-top: 1px dashed var(--border-color); padding-top: 10px; }
.sub-row { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.sub-label { font-size: 12px; color: var(--text-muted); }
.sub-val { font-family: var(--font-display); font-weight: 700; font-size: 16px; color: var(--text-primary); }
.sub-renew-txt { font-size: 12px; font-weight: 600; color: var(--text-primary); }
.sub-renew-txt.is-warn { color: var(--tag-warning-text); }
.num { font-variant-numeric: tabular-nums; }
.bar-track {
  position: relative; height: 7px; background: var(--tag-neutral-bg);
  border-radius: 999px; margin: 7px 0 5px;
}
.bar-fill { height: 100%; border-radius: 999px; transition: width var(--motion-base) var(--ease-out-strong); }
.bar-fill--ok { background: var(--tag-success-solid); }
.bar-fill--warn { background: var(--tag-warning-solid); }
.bar-fill--danger { background: var(--tag-danger-solid); }
.bar-mark {
  position: absolute; top: -3px; bottom: -3px; width: 2px;
  background: var(--text-secondary); border-radius: 2px; opacity: 0.7;
}
.sub-hint { font-size: 12px; color: var(--text-muted); line-height: 1.5; }
.sub-spend { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.sub-spend__note { grid-column: 1 / 3; }
.internal-summary {
  background: var(--tag-neutral-bg); border: 1px solid var(--tag-neutral-border);
  border-radius: 10px; padding: 10px 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
}
.internal-val { display: block; font-size: 13px; color: var(--text-primary); margin-top: 2px; }
.sub-card__foot {
  display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-top: auto; padding-top: 8px; border-top: 1px solid var(--border-color);
}
.sub-card__links { display: flex; gap: 10px; align-items: center; }
.sub-card__links a { font-size: 12px; font-weight: 600; color: var(--button-primary-text); text-decoration: none; }
.sub-card__links a:hover { text-decoration: underline; }
.sub-card__actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
:deep(.danger-item) { color: var(--tag-danger-text); }
</style>
