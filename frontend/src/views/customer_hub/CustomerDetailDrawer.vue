<template>
  <DetailDrawer
    :model-value="modelValue"
    :title="customerTitle"
    width="min(820px, 100vw)"
    :loading="loading"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-alert v-if="detailError" type="error" title="客户详情加载失败，请检查权限或网络后重试。" :closable="false" show-icon>
      <template #default><el-button link type="primary" @click="retryDetail">重试</el-button></template>
    </el-alert>
    <template v-else-if="customer">
      <section class="identity-strip" aria-label="客户核心概览">
        <div>
          <div class="eyebrow">{{ customer.customer_code || `CUSTOMER-${customer.customer_id}` }}</div>
          <h2>{{ customer.display_name || customer.canonical_company_name || `临时客户 #${customer.customer_id}` }}</h2>
          <p>{{ identityExplanation }}</p>
        </div>
        <div class="identity-metrics">
          <el-tag :type="customer.identity_status === 'verified' ? 'success' : 'warning'">
            {{ customer.identity_status || 'provisional' }}
          </el-tag>
          <span>完整度 {{ customer.profile_completeness ?? 0 }}%</span>
          <span>{{ customer.is_public_pool ? '公海 · 暂无主负责人' : '已有主负责人' }}</span>
        </div>
      </section>

      <el-tabs v-model="activeTab" class="detail-tabs" @tab-change="handleTabChange">
        <el-tab-pane label="概览" name="overview">
          <div class="fact-grid">
            <article><span>关系阶段</span><strong>{{ customer.relationship_stage || '未评估' }}</strong></article>
            <article><span>主要市场</span><strong>{{ customer.primary_market || customer.primary_country_code || '待补充' }}</strong></article>
            <article><span>主要行业</span><strong>{{ customer.primary_industry || '待补充' }}</strong></article>
            <article><span>互动健康度</span><strong>{{ customer.engagement_health || '待评估' }}</strong></article>
          </div>
          <SectionBlock title="Overview · 档案概览" section-key="overview" :value="sections.overview" />
          <SectionBlock title="当前需求" section-key="current needs" :value="sections.currentNeeds" />
          <SectionBlock title="下一步行动" section-key="actions" :value="sections.actions" />
        </el-tab-pane>

        <el-tab-pane label="身份与联系人" name="identity">
          <SectionBlock title="Identity · 身份" section-key="identity" :value="sections.identity" />
          <SectionBlock title="Contacts · 联系人" section-key="contacts" :value="sections.contacts" />
          <SectionBlock title="Preferences · 偏好" section-key="preferences" :value="sections.preferences" />
          <SectionBlock title="Behavior · 行为模式" section-key="behavior patterns" :value="sections.behaviorPatterns" />
        </el-tab-pane>

        <el-tab-pane label="往来与订单" name="relationships" lazy>
          <SectionBlock title="Conversations · 沟通记录" section-key="conversations" :value="sections.conversations" />
          <div v-loading="timelineLoading" class="timeline-block">
            <el-alert v-if="timelineError" type="error" title="时间线加载失败，当前内容不是空数据。" :closable="false" show-icon>
              <template #default><el-button link type="primary" @click="loadTimeline(customer.customer_id)">重试</el-button></template>
            </el-alert>
            <el-timeline v-else-if="timeline.length">
              <el-timeline-item v-for="event in timeline" :key="event.event_id" :timestamp="formatDate(event.occurred_at)">
                <strong>{{ event.title || event.event_type }}</strong>
                <p>{{ event.summary || '无补充摘要' }}</p>
              </el-timeline-item>
            </el-timeline>
            <el-empty v-else-if="!timelineLoading" description="暂无可见时间线记录" :image-size="72" />
            <p v-if="timelineLimitNotice" class="timeline-limit">{{ timelineLimitNotice }}</p>
          </div>
          <SectionBlock title="Orders · 商业摘要" section-key="orders" :value="sections.orders" />
        </el-tab-pane>

        <el-tab-pane label="证据与机会" name="intelligence" lazy>
          <SectionBlock title="Evidence · 证据" section-key="evidence" :value="sections.evidence" />
          <SectionBlock title="Opportunities · 客户机会" section-key="opportunities" :value="sections.opportunities" />
          <SectionBlock title="Actions · 经营动作" section-key="actions" :value="sections.actions" />
          <SectionBlock title="Risks · 风险" section-key="risks" :value="sections.risks" />
          <SectionBlock title="Recent changes · 最近变化" section-key="recent changes" :value="sections.recentChanges" />
          <SectionBlock title="Open questions · 待确认问题" section-key="open questions" :value="sections.openQuestions" />
        </el-tab-pane>

        <el-tab-pane label="治理信息" name="governance" lazy>
          <SectionBlock title="Annotations · 人工批注" section-key="annotations" :value="customer.annotations ?? sections.annotations" />
          <section class="section-block" data-section="version quality">
            <h3>Version quality · 版本质量</h3>
            <dl>
              <div><dt>档案质量</dt><dd><StructuredValue :value="sections.versionQuality" /></dd></div>
              <div><dt>档案版本</dt><dd>{{ sections.profileMetadata?.version_no ?? '该档案版本未提供' }}</dd></div>
              <div><dt>档案契约</dt><dd>{{ sections.profileMetadata?.profile_schema_version || '该档案版本未提供' }}</dd></div>
              <div><dt>编译时间</dt><dd>{{ formatDate(sections.profileMetadata?.compiled_at) }}</dd></div>
              <div><dt>数据截至</dt><dd>{{ formatDate(sections.profileMetadata?.data_as_of) }}</dd></div>
              <div><dt>章节数据截至</dt><dd><StructuredValue :value="sections.profileMetadata?.section_data_as_of" /></dd></div>
            </dl>
          </section>
        </el-tab-pane>
      </el-tabs>
    </template>
  </DetailDrawer>
</template>

<script setup>
import { computed, defineComponent, h, ref, watch } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { formatBeijingDateTime } from '@/utils/datetime'
import { getTimelineLimitNotice, mapCustomerProfileSections } from './customerHubController'
import { getProfileValueKind, profileFieldLabel } from './customerHubPresentation'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  customer: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  timeline: { type: Array, default: () => [] },
  timelineTotal: { type: Number, default: 0 },
  timelineLoading: { type: Boolean, default: false },
  detailError: { type: Object, default: null },
  timelineError: { type: Object, default: null },
  loadTimeline: { type: Function, required: true },
  retryDetail: { type: Function, required: true },
})
defineEmits(['update:modelValue'])

const activeTab = ref('overview')
watch(() => props.customer?.customer_id, customerId => {
  if (customerId) activeTab.value = 'overview'
})
const customerTitle = computed(() => props.customer ? `客户档案 · ${props.customer.display_name || props.customer.customer_code || props.customer.customer_id}` : '客户档案')
const identityExplanation = computed(() => props.customer?.identity_status === 'verified'
  ? '身份已核验；customer_id 是唯一业务主键。'
  : '临时客户：名称可为空，系统仍以 customer_id 持续归集证据，待身份核验后再确认主体。')
const sections = computed(() => mapCustomerProfileSections(props.customer || {}, props.timeline))
const timelineLimitNotice = computed(() => getTimelineLimitNotice(props.timeline.length, props.timelineTotal))
const formatDate = value => value ? formatBeijingDateTime(value) : '该档案版本未提供'

function handleTabChange(name) {
  if (name === 'relationships') props.loadTimeline(props.customer?.customer_id)
}

const StructuredValue = defineComponent({
  name: 'StructuredValue',
  props: { value: null },
  setup(valueProps) {
    return () => {
      const kind = getProfileValueKind(valueProps.value)
      if (kind === 'empty') return h('span', { class: 'structured-empty' }, '该档案版本未提供')
      if (kind === 'scalar') {
        const text = typeof valueProps.value === 'boolean' ? (valueProps.value ? '是' : '否') : String(valueProps.value)
        return h('span', { class: 'structured-scalar' }, text)
      }
      if (kind === 'list') {
        if (valueProps.value.length === 0) return h('span', { class: 'structured-empty' }, '暂无记录')
        return h('ul', { class: 'structured-list' }, valueProps.value.map((item, index) =>
          h('li', { key: index }, [h(StructuredValue, { value: item })])))
      }
      const entries = Object.entries(valueProps.value)
      if (entries.length === 0) return h('span', { class: 'structured-empty' }, '暂无记录')
      return h('dl', { class: 'structured-record' }, entries.map(([key, value]) =>
        h('div', { key }, [
          h('dt', profileFieldLabel(key)),
          h('dd', [h(StructuredValue, { value })]),
        ])))
    }
  },
})

const SectionBlock = defineComponent({
  props: { title: String, sectionKey: String, value: null },
  setup(blockProps) {
    return () => h('section', { class: 'section-block', 'data-section': blockProps.sectionKey }, [
      h('h3', blockProps.title),
      blockProps.value == null || (Array.isArray(blockProps.value) && blockProps.value.length === 0)
        ? h('p', { class: 'empty-copy' }, '该档案版本未提供此部分')
        : h(StructuredValue, { value: blockProps.value }),
    ])
  },
})
</script>

<style scoped>
.identity-strip { display: flex; justify-content: space-between; gap: 24px; padding: 18px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--toolbar-bg); }
.eyebrow { color: var(--text-muted); font-size: 12px; letter-spacing: .08em; }
h2 { margin: 4px 0; color: var(--text-primary); font-size: 22px; }
.identity-strip p { margin: 0; color: var(--text-secondary); line-height: 1.6; }
.identity-metrics { min-width: 180px; display: grid; align-content: start; justify-items: end; gap: 8px; color: var(--text-secondary); font-size: 13px; }
.detail-tabs { margin-top: 16px; }
.fact-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.fact-grid article { padding: 13px; border: 1px solid var(--border-color); border-radius: 8px; }
.fact-grid span { display: block; color: var(--text-muted); font-size: 12px; margin-bottom: 6px; }
.fact-grid strong { color: var(--text-primary); }
.section-block { margin-bottom: 12px; padding: 14px; border: 1px solid var(--border-color); border-radius: 8px; }
.section-block h3 { margin: 0 0 10px; color: var(--text-primary); font-size: 14px; }
.empty-copy { margin: 0; color: var(--text-muted); }
.structured-scalar { color: var(--text-primary); overflow-wrap: anywhere; }
.structured-empty { color: var(--text-muted); font-weight: 400; }
.structured-list { display: grid; gap: 8px; margin: 0; padding-left: 20px; color: var(--text-secondary); }
.structured-list > li { padding-left: 2px; }
.structured-record { margin: 0; }
.structured-record > div { display: grid; grid-template-columns: minmax(96px, 28%) 1fr; gap: 14px; padding: 8px 0; border-bottom: 1px solid var(--border-color); }
.structured-record > div:last-child { border-bottom: 0; }
.structured-record dt { color: var(--text-muted); font-size: 13px; }
.structured-record dd { min-width: 0; margin: 0; color: var(--text-primary); font-weight: 500; }
.structured-record .structured-record { padding-left: 0; }
.timeline-block { min-height: 80px; padding: 8px 4px; }
.timeline-block p { margin: 5px 0 0; color: var(--text-secondary); }
.timeline-limit { padding: 8px 12px; border-radius: 8px; background: var(--toolbar-bg); }
dl { margin: 0; }
dl div { display: flex; justify-content: space-between; padding: 7px 0; border-bottom: 1px solid var(--border-color); }
dl div:last-child { border-bottom: 0; }
dt { color: var(--text-secondary); } dd { margin: 0; color: var(--text-primary); font-weight: 600; }
@media (max-width: 768px) { .identity-strip { flex-direction: column; } .identity-metrics { justify-items: start; } .fact-grid { grid-template-columns: repeat(2, 1fr); } .structured-record > div { grid-template-columns: 1fr; gap: 4px; } }
</style>
