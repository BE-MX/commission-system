<template>
  <el-dialog
    v-model="visible"
    title="生成今日公海背调批次"
    width="min(760px, calc(100vw - 32px))"
    destroy-on-close
    @closed="resetDraft"
  >
    <el-form label-position="top">
      <section class="condition-section">
        <div class="section-title">
          <div><strong>成交画像</strong><span>以下已启用规则满足任意一条即可</span></div>
          <el-input-number v-model="draft.quota_per_tier" :min="1" :max="100" controls-position="right" />
        </div>
        <p class="quota-label">T1 最多生成数量</p>

        <el-alert
          title="当前成交画像都要求存在历史订单，因此本批次只会生成 T1 再激活客户，T2/T3 数量为 0。"
          type="info"
          :closable="false"
          show-icon
          class="profile-alert"
        />

        <div class="rule-row">
          <el-checkbox v-model="draft.value_pair_enabled">成交单数与累计金额</el-checkbox>
          <div class="inline-fields" :class="{ disabled: !draft.value_pair_enabled }">
            <span>不少于</span><el-input-number v-model="draft.min_order_count" :min="1" :max="1000" :disabled="!draft.value_pair_enabled" controls-position="right" />
            <span>单，且累计金额大于 USD</span><el-input-number v-model="draft.total_amount_over_usd" :min="0" :max="1000000000" :disabled="!draft.value_pair_enabled" controls-position="right" />
          </div>
        </div>
        <div class="rule-row">
          <el-checkbox v-model="draft.single_order_enabled">单笔大额成交</el-checkbox>
          <div class="inline-fields" :class="{ disabled: !draft.single_order_enabled }">
            <span>任一订单金额大于 USD</span><el-input-number v-model="draft.single_order_over_usd" :min="0" :max="1000000000" :disabled="!draft.single_order_enabled" controls-position="right" />
          </div>
        </div>
        <div class="rule-row compact-rule">
          <el-checkbox v-model="draft.sample_only_orders">仅成交样品订单</el-checkbox>
          <span>客户全部历史成交单的名称均标记为 Sample / 样品 / 样单</span>
        </div>
      </section>

      <section class="condition-section">
        <div class="section-title"><div><strong>其他特征</strong><span>所有已开启条件必须同时满足</span></div></div>
        <div class="feature-grid">
          <el-form-item label="国家范围">
            <div class="switch-field">
              <el-checkbox v-model="draft.top_country_enabled">仅历史成交额 Top</el-checkbox>
              <el-input-number v-model="draft.top_country_limit" :min="1" :max="50" :disabled="!draft.top_country_enabled" controls-position="right" />
              <span>国家</span>
            </div>
          </el-form-item>
          <el-form-item label="可触达方式（满足任一）">
            <el-checkbox-group v-model="draft.contact_channels">
              <el-checkbox value="instagram">Instagram（优先）</el-checkbox>
              <el-checkbox value="facebook">Facebook</el-checkbox>
              <el-checkbox value="phone">电话</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <el-form-item label="历史成交产品（匹配任一关键词）" class="wide-field">
            <el-select v-model="draft.product_keywords" multiple filterable allow-create default-first-option style="width: 100%" placeholder="留空则不限制产品">
              <el-option v-for="item in draft.product_keywords" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>
          <el-form-item label="最近下单">
            <div class="switch-field">
              <el-checkbox v-model="draft.inactive_order_enabled">至少</el-checkbox>
              <el-input-number v-model="draft.inactive_order_days" :min="1" :max="3650" :disabled="!draft.inactive_order_enabled" controls-position="right" />
              <span>天未下单</span>
            </div>
          </el-form-item>
          <el-form-item label="客户资料最近更新时间（跟进代理）">
            <div class="switch-field">
              <el-checkbox v-model="draft.stale_followup_enabled">至少</el-checkbox>
              <el-input-number v-model="draft.stale_followup_days" :min="1" :max="3650" :disabled="!draft.stale_followup_enabled" controls-position="right" />
              <span>天未更新</span>
            </div>
          </el-form-item>
        </div>
        <el-alert
          title="同步库没有独立跟进记录表；当前以 OKKI 客户 update_time 作为最近跟进代理，未记录时间的客户也会纳入。"
          type="info"
          :closable="false"
          show-icon
        />
      </section>
    </el-form>
    <template #footer>
      <GlassButton variant="secondary" @click="visible = false">取消</GlassButton>
      <GlassButton variant="primary" left-icon="Plus" :loading="loading" :disabled="!canSubmit" @click="submit">按画像生成批次</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive } from 'vue'
import GlassButton from '@/components/GlassButton.vue'

const props = defineProps({ modelValue: Boolean, loading: Boolean })
const emit = defineEmits(['update:modelValue', 'submit'])

const defaults = () => ({
  quota_per_tier: 20,
  value_pair_enabled: true,
  min_order_count: 2,
  total_amount_over_usd: 1500,
  single_order_enabled: true,
  single_order_over_usd: 1000,
  sample_only_orders: true,
  top_country_enabled: true,
  top_country_limit: 10,
  contact_channels: ['instagram', 'facebook', 'phone'],
  product_keywords: ['天才', '平型', '贴发'],
  inactive_order_enabled: true,
  inactive_order_days: 60,
  stale_followup_enabled: true,
  stale_followup_days: 30,
})
const draft = reactive(defaults())
const visible = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
const canSubmit = computed(() => draft.value_pair_enabled || draft.single_order_enabled || draft.sample_only_orders)

function resetDraft() { Object.assign(draft, defaults()) }
function submit() {
  if (!canSubmit.value) return
  emit('submit', {
    quota_per_tier: draft.quota_per_tier,
    policy_version: 'v3',
    profile_conditions: {
      value_rules: {
        min_order_count: draft.value_pair_enabled ? draft.min_order_count : null,
        total_amount_over_usd: draft.value_pair_enabled ? draft.total_amount_over_usd : null,
        single_order_over_usd: draft.single_order_enabled ? draft.single_order_over_usd : null,
        sample_only_orders: draft.sample_only_orders,
      },
      top_country_limit: draft.top_country_enabled ? draft.top_country_limit : null,
      contact_channels: draft.contact_channels,
      product_keywords: draft.product_keywords.map(item => item.trim()).filter(Boolean),
      inactive_order_days: draft.inactive_order_enabled ? draft.inactive_order_days : null,
      stale_followup_days: draft.stale_followup_enabled ? draft.stale_followup_days : null,
    },
  })
}
</script>

<style scoped>
.condition-section { padding: 16px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--toolbar-bg); }
.condition-section + .condition-section { margin-top: 14px; }
.section-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.section-title div { display: grid; gap: 3px; }
.section-title strong { color: var(--text-primary); font-size: 14px; }
.section-title span,.quota-label,.compact-rule > span { color: var(--text-muted); font-size: 12px; }
.quota-label { margin: -10px 0 12px; text-align: right; }
.profile-alert { margin-bottom: 12px; }
.rule-row { display: grid; grid-template-columns: 180px 1fr; align-items: center; gap: 12px; padding: 10px 0; border-top: 1px solid var(--border-color); }
.inline-fields,.switch-field { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; color: var(--text-secondary); font-size: 13px; }
.inline-fields :deep(.el-input-number) { width: 118px; }
.inline-fields.disabled { color: var(--text-muted); }
.compact-rule { align-items: start; }
.feature-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 18px; }
.wide-field { grid-column: 1 / -1; }
.switch-field :deep(.el-input-number) { width: 108px; }
@media (max-width: 720px) {
  .rule-row,.feature-grid { grid-template-columns: 1fr; }
  .wide-field { grid-column: auto; }
}
</style>
