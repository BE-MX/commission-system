<template>
  <div class="oi-page" v-loading="loading">
    <div class="oi-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <header class="oi-header">
      <div>
        <div class="oi-eyebrow"><el-icon><DataAnalysis /></el-icon> ORDER INTELLIGENCE</div>
        <h2>订单经营决策台</h2>
        <p>从订单事实识别市场机会、团队能力与客户下一步行动，所有建议均附证据与口径。</p>
      </div>
      <GlassButton variant="primary" :loading="aiLoading" :disabled="aiLoading" @click="handleBriefAction()">
        <el-icon><MagicStick /></el-icon> {{ briefButtonText }}
      </GlassButton>
    </header>

    <el-alert v-if="error" class="oi-error" type="error" :title="error" show-icon :closable="false">
      <template #default><el-button link type="danger" @click="loadPage">重新加载</el-button></template>
    </el-alert>

    <OrderFilters :filters="filters" :options="options" :scoped-users="scopedUsers" @team-change="changeTeam" @apply="loadPage" />

    <template v-if="overview">
      <section class="oi-metrics" aria-label="经营摘要">
        <article class="oi-metric lg-card is-static">
          <span>有效订单 GMV</span>
          <strong>${{ compactMoney(overview.metrics.amount_usd) }}</strong>
          <p :class="changeClass(overview.metrics.changes.amount_usd)">{{ changeText(overview.metrics.changes.amount_usd) }} 较上期</p>
        </article>
        <article class="oi-metric lg-card is-static">
          <span>新签客户</span>
          <strong>{{ number(overview.metrics.new_sign_customers) }}</strong>
          <p :class="changeClass(overview.metrics.changes.new_sign_customers)">{{ changeText(overview.metrics.changes.new_sign_customers) }} 较上期</p>
        </article>
        <article class="oi-metric lg-card is-static">
          <span>首返客户</span>
          <strong>{{ number(overview.metrics.first_return_customers) }}</strong>
          <p :class="changeClass(overview.metrics.changes.first_return_customers)">{{ changeText(overview.metrics.changes.first_return_customers) }} 较上期</p>
        </article>
        <article class="oi-metric lg-card is-static">
          <span>复购客户 / 金额</span>
          <strong>{{ number(overview.metrics.repeat_customers) }}</strong>
          <p>${{ compactMoney(overview.metrics.repeat_amount_usd) }}</p>
        </article>
        <article class="oi-metric lg-card is-static">
          <span>复购率</span>
          <strong>{{ overview.metrics.repurchase_rate }}%</strong>
          <p>首返 {{ number(overview.metrics.first_return_customers) }} / 新签 {{ number(overview.metrics.new_sign_customers) }}</p>
        </article>
      </section>

      <section class="oi-tabs lg-card is-static">
        <el-tabs v-model="activeTab" @tab-change="changeTab">
          <el-tab-pane label="经营总览" name="overview" />
          <el-tab-pane label="国家机会" name="countries" />
          <el-tab-pane label="团队与个人" name="people" />
          <el-tab-pane label="客户画像" name="profiles" />
          <el-tab-pane label="客户行动清单" name="customers" />
        </el-tabs>

        <div v-if="activeTab === 'overview'" class="oi-overview-grid">
          <article class="oi-panel oi-panel--wide">
            <div class="oi-panel-title">
              <div><h3>月度经营趋势</h3><p>GMV、新签/首返客户与有效订单数分开观察</p></div>
              <el-radio-group v-model="trendMode" size="small"><el-radio-button label="amount">GMV</el-radio-button><el-radio-button label="customers">新签/首返</el-radio-button><el-radio-button label="orders">下单频次</el-radio-button></el-radio-group>
            </div>
            <OrderTrendChart :rows="overview.monthly_trend" :mode="trendMode" />
          </article>
          <article class="oi-panel oi-panel--wide">
            <div class="oi-panel-title"><div><h3>月度复购订单趋势</h3><p>复购订单数按订单计数，复购金额使用订单 amount_usd</p></div></div>
            <RepeatPurchaseTrendChart :rows="overview.monthly_trend" />
          </article>
          <article class="oi-panel">
            <div class="oi-panel-title"><div><h3>成交来源结构</h3><p>不是广告 ROI，仅反映成交订单归因</p></div></div>
            <div class="oi-source-list">
              <div v-for="source in overview.source_mix.slice(0, 7)" :key="source.code" class="oi-source-row">
                <div><strong>{{ source.label }}</strong><span>{{ source.new_sign_customers }} 新签 · ${{ compactMoney(source.amount_usd) }}</span></div>
                <el-progress :percentage="source.order_share" :show-text="false" :stroke-width="7" />
                <b>{{ source.order_share }}% <em :class="changeClass(source.share_change_pp)">{{ ppChangeText(source.share_change_pp) }}</em></b>
              </div>
            </div>
          </article>
          <article class="oi-panel">
            <div class="oi-panel-title"><div><h3>产品偏好</h3><p>按订单明细销量，不与订单 GMV 混算</p></div></div>
            <div class="oi-preference-columns">
              <div><span>热销型号</span><ol><li v-for="item in overview.top_models.slice(0, 6)" :key="item.name"><b>{{ item.name }}</b><em>{{ productQuantityText(item) }}</em></li></ol></div>
              <div><span>热销颜色</span><ol><li v-for="item in overview.top_colors.slice(0, 6)" :key="item.name"><b>{{ item.name }}</b><em>{{ productQuantityText(item) }}</em></li></ol></div>
            </div>
          </article>
          <article class="oi-panel">
            <div class="oi-panel-title"><div><h3>订单金额分布</h3><p>按正金额订单统计，识别小单与大单结构</p></div></div>
            <div class="oi-amount-list">
              <div v-for="bucket in overview.amount_distribution" :key="bucket.label">
                <span>{{ bucket.label }}</span>
                <div><i :style="{ width: `${Math.max(bucket.share, 1)}%` }" /></div>
                <b>{{ bucket.orders }} 单 · {{ bucket.share }}% <em :class="changeClass(bucket.share_change_pp)">{{ ppChangeText(bucket.share_change_pp) }}</em></b>
              </div>
            </div>
          </article>
          <article class="oi-panel oi-quality">
            <div class="oi-panel-title"><div><h3>数据可信度</h3><p>任何建议都应先看覆盖率</p></div></div>
            <div class="oi-quality-grid">
              <div><el-progress type="dashboard" :percentage="overview.data_quality.country_coverage" :width="86" /><span>国家</span></div>
              <div><el-progress type="dashboard" :percentage="overview.data_quality.source_coverage" :width="86" /><span>来源</span></div>
              <div><el-progress type="dashboard" :percentage="overview.data_quality.product_model_coverage" :width="86" /><span>型号</span></div>
              <div><el-progress type="dashboard" :percentage="overview.data_quality.product_color_coverage" :width="86" /><span>颜色</span></div>
            </div>
            <el-collapse class="oi-definitions">
              <el-collapse-item title="查看完整统计口径" name="definition">
                <p v-for="(definition, key) in overview.definitions" :key="key">{{ definition }}</p>
              </el-collapse-item>
            </el-collapse>
          </article>
        </div>

        <div v-else-if="activeTab === 'countries'" v-loading="detailLoading" class="oi-table-wrap">
          <div class="oi-section-note"><b>国家机会评分</b><span>{{ countries.score_definition }}</span></div>
          <el-table :data="countries.items" border class="list-table">
            <el-table-column type="expand" min-width="48">
              <template #default="{ row }">
                <div class="oi-row-evidence">
                  <section><h4>订单金额层级 · 较上期份额变化</h4><div><span v-for="bucket in row.amount_distribution" :key="bucket.label"><b>{{ bucket.label }}</b>{{ bucket.share }}% <em :class="changeClass(bucket.share_change_pp)">{{ ppChangeText(bucket.share_change_pp) }}</em></span></div></section>
                  <section><h4>成交来源结构</h4><div><span v-for="source in row.source_mix" :key="source.code"><b>{{ source.label }}</b>{{ source.orders }} 单 · {{ source.order_share }}% <em :class="changeClass(source.share_change_pp)">{{ ppChangeText(source.share_change_pp) }}</em></span></div></section>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="国家" prop="country" min-width="100" fixed />
            <el-table-column label="机会分" prop="opportunity_score" min-width="92">
              <template #default="{ row }"><el-tag effect="plain" :type="scoreType(row.opportunity_score)">{{ row.opportunity_score }}</el-tag></template>
            </el-table-column>
            <el-table-column label="新签客户" prop="new_sign_customers" min-width="104" />
            <el-table-column label="首返客户" prop="first_return_customers" min-width="104" />
            <el-table-column label="复购客户" prop="repeat_customers" min-width="104" />
            <el-table-column label="复购金额" min-width="128"><template #default="{ row }">${{ money(row.repeat_amount_usd) }}</template></el-table-column>
            <el-table-column label="客单中位" min-width="112"><template #default="{ row }">${{ money(row.median_order_amount_usd) }}</template></el-table-column>
            <el-table-column label="GMV 趋势" min-width="105"><template #default="{ row }"><span :class="changeClass(row.amount_growth)">{{ changeText(row.amount_growth) }}</span></template></el-table-column>
            <el-table-column label="下单频次变化" min-width="116"><template #default="{ row }"><span :class="changeClass(row.order_frequency_growth)">{{ changeText(row.order_frequency_growth) }}</span></template></el-table-column>
            <el-table-column label="典型周期" min-width="104"><template #default="{ row }">{{ row.median_cycle_days ? `${row.median_cycle_days} 天` : '样本不足' }}</template></el-table-column>
            <el-table-column label="流失风险" prop="at_risk_customers" min-width="96" />
            <el-table-column label="主要来源" prop="top_source_label" min-width="124" show-overflow-tooltip />
            <el-table-column label="产品偏好" min-width="210"><template #default="{ row }">{{ preferenceText(row) }}</template></el-table-column>
            <el-table-column label="30天预测" min-width="118"><template #default="{ row }">{{ row.next_30d_amount_forecast == null ? '样本不足' : `$${money(row.next_30d_amount_forecast)}` }}</template></el-table-column>
            <el-table-column label="投流方向建议" min-width="300">
              <template #default="{ row }"><div class="oi-advice"><b>{{ row.marketing_advice.title }}</b><span>{{ row.marketing_advice.action }}</span><em>{{ evidenceLabel(row.evidence_level) }}</em></div></template>
            </el-table-column>
          </el-table>
        </div>

        <div v-else-if="activeTab === 'people'" v-loading="detailLoading" class="oi-table-wrap">
          <div class="oi-section-note"><b>能力评估</b><span>{{ people.evaluation_note }}</span><el-radio-group v-model="peopleDimension" size="small" @change="changePeopleDimension"><el-radio-button label="user">个人</el-radio-button><el-radio-button label="team">团队</el-radio-button></el-radio-group></div>
          <el-table :data="people.items" border class="list-table">
            <el-table-column :label="peopleDimension === 'team' ? '团队' : '业务员'" prop="name" min-width="120" fixed />
            <el-table-column v-if="peopleDimension === 'user'" label="所属团队" prop="team" min-width="110" />
            <el-table-column label="能力标签" min-width="210"><template #default="{ row }"><div class="oi-tags"><el-tag v-for="tag in row.capability_labels" :key="tag" effect="plain">{{ tag }}</el-tag></div></template></el-table-column>
            <el-table-column label="新签" prop="new_sign_customers" min-width="76" />
            <el-table-column label="新客均单" min-width="110"><template #default="{ row }">${{ money(row.new_avg_amount) }}</template></el-table-column>
            <el-table-column label="首返" prop="first_return_customers" min-width="76" />
            <el-table-column label="复购率" min-width="88"><template #default="{ row }">{{ row.repeat_customer_rate }}%</template></el-table-column>
            <el-table-column label="复购金额" min-width="120"><template #default="{ row }">${{ money(row.repeat_amount_usd) }}</template></el-table-column>
            <el-table-column label="优势国家" min-width="140"><template #default="{ row }">{{ row.top_country }} · {{ row.top_country_share }}%</template></el-table-column>
            <el-table-column label="主要来源" prop="top_source" min-width="120" />
            <el-table-column label="产品偏好" min-width="200"><template #default="{ row }">{{ preferenceText(row) }}</template></el-table-column>
            <el-table-column label="客户周期/风险" min-width="150"><template #default="{ row }">{{ row.median_cycle_days ? `${row.median_cycle_days} 天` : '样本不足' }} · {{ row.at_risk_customers }} 风险</template></el-table-column>
            <el-table-column label="GMV 变化" min-width="100"><template #default="{ row }"><span :class="changeClass(row.amount_growth)">{{ changeText(row.amount_growth) }}</span></template></el-table-column>
            <el-table-column label="下单频次变化" min-width="116"><template #default="{ row }"><span :class="changeClass(row.order_frequency_growth)">{{ changeText(row.order_frequency_growth) }}</span></template></el-table-column>
            <el-table-column label="新签变化" min-width="94"><template #default="{ row }"><span :class="changeClass(row.new_sign_growth)">{{ changeText(row.new_sign_growth) }}</span></template></el-table-column>
            <el-table-column label="复购额变化" min-width="104"><template #default="{ row }"><span :class="changeClass(row.repeat_amount_growth)">{{ changeText(row.repeat_amount_growth) }}</span></template></el-table-column>
            <el-table-column label="证据等级" min-width="96"><template #default="{ row }">{{ evidenceLabel(row.evidence_level) }}</template></el-table-column>
          </el-table>
        </div>

        <div v-else-if="activeTab === 'profiles'" v-loading="detailLoading" class="oi-table-wrap">
          <div class="oi-section-note"><b>客户画像分析</b><span>{{ profiles.definitions?.profile }}；{{ profiles.definitions?.repeat_cycle }}</span></div>
          <div class="oi-profile-summary">
            <div><span>本期客户</span><b>{{ number(profiles.summary?.active_customer_count) }}</b></div>
            <div><span>画像组合</span><b>{{ number(profiles.summary?.profile_count) }}</b></div>
            <div><span>客户性质覆盖</span><b>{{ profiles.summary?.customer_nature_coverage || 0 }}%</b></div>
            <div><span>B1/B3 新签覆盖</span><b>{{ profiles.summary?.new_sign_b1_b3_coverage || 0 }}%</b></div>
            <div><span>复购周期覆盖</span><b>{{ profiles.summary?.repeat_cycle_coverage || 0 }}%</b></div>
          </div>
          <el-table :data="profiles.items" border class="list-table">
            <el-table-column type="expand" min-width="48">
              <template #default="{ row }">
                <div class="oi-profile-evidence">
                  <section><h4>统计期畅销产品</h4><div><span v-for="item in row.period_best_sellers" :key="item.name"><b>{{ item.name }}</b>{{ number(item.quantity) }} · {{ item.share }}%</span></div></section>
                  <section><h4>统计期型号</h4><div><span v-for="item in row.period_models" :key="item.name"><b>{{ item.name }}</b>{{ number(item.quantity) }} · {{ item.share }}%</span></div></section>
                  <section><h4>统计期颜色</h4><div><span v-for="item in row.period_colors" :key="item.name"><b>{{ item.name }}</b>{{ number(item.quantity) }} · {{ item.share }}%</span></div></section>
                  <section><h4>统计期幅度</h4><div><span v-for="item in row.period_amplitudes" :key="item.name"><b>{{ item.name }}寸</b>{{ number(item.quantity) }} · {{ item.share }}%</span></div></section>
                  <section><h4>历史复购型号</h4><div><span v-for="item in row.repeat_models" :key="item.name"><b>{{ item.name }}</b>{{ number(item.quantity) }} · {{ item.share }}%</span></div></section>
                  <section><h4>历史复购幅度</h4><div><span v-for="item in row.repeat_amplitudes" :key="item.name"><b>{{ item.name }}寸</b>{{ number(item.quantity) }} · {{ item.share }}%</span></div></section>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="国家" prop="country" min-width="92" fixed />
            <el-table-column label="来源渠道" prop="source_label" min-width="116" />
            <el-table-column label="客户性质" prop="customer_nature" min-width="94" />
            <el-table-column label="新签型号" prop="new_sign_model_family" min-width="92" />
            <el-table-column label="型号归类说明" prop="new_sign_model_reason_summary" min-width="220" show-overflow-tooltip />
            <el-table-column label="本期客户" prop="active_customer_count" min-width="88" />
            <el-table-column label="同画像客户" prop="peer_customer_count" min-width="100" />
            <el-table-column label="典型首返周期" min-width="122"><template #default="{ row }">{{ row.typical_first_return_cycle_days != null ? `${row.typical_first_return_cycle_days} 天` : '样本不足' }}</template></el-table-column>
            <el-table-column label="首返样本" prop="first_return_sample_count" min-width="88" />
            <el-table-column label="典型复购周期" min-width="122"><template #default="{ row }">{{ row.typical_repeat_cycle_days ? `${row.typical_repeat_cycle_days} 天` : '样本不足' }}</template></el-table-column>
            <el-table-column label="复购间隔样本" prop="repeat_interval_count" min-width="110" />
            <el-table-column label="本期订单" prop="period_orders" min-width="88" />
            <el-table-column label="本期金额" min-width="120"><template #default="{ row }">${{ money(row.period_amount_usd) }}</template></el-table-column>
            <el-table-column label="证据等级" min-width="90"><template #default="{ row }">{{ evidenceLabel(row.evidence_level) }}</template></el-table-column>
          </el-table>
        </div>

        <div v-else v-loading="detailLoading" class="oi-table-wrap">
          <div class="oi-section-note oi-customer-filters">
            <div><b>客户行动清单</b><span>{{ customers.risk_definition }}</span></div>
            <el-select v-model="customerFilters.risk_status" clearable placeholder="全部风险" @change="changeCustomerPage"><el-option label="到期提醒" value="due" /><el-option label="周期异常" value="abnormal" /><el-option label="样本不足" value="insufficient_data" /></el-select>
            <el-select v-model="customerFilters.country" clearable filterable placeholder="全部国家" @change="changeCustomerPage"><el-option v-for="country in options.countries" :key="country" :label="country" :value="country" /></el-select>
          </div>
          <el-table :data="customers.items" border class="list-table">
            <el-table-column label="客户" prop="company_name" min-width="190" show-overflow-tooltip fixed />
            <el-table-column label="国家" prop="country" min-width="94" />
            <el-table-column label="负责人" prop="user_name" min-width="96" />
            <el-table-column label="风险" min-width="108"><template #default="{ row }"><el-tag effect="plain" :type="riskType(row.risk_status)">{{ riskLabel(row.risk_status) }}</el-tag></template></el-table-column>
            <el-table-column label="所属画像" prop="profile_label" min-width="280" show-overflow-tooltip />
            <el-table-column label="典型周期" min-width="158"><template #default="{ row }">{{ row.typical_cycle_days ? `${row.typical_cycle_days} 天` : '样本不足' }} · {{ cycleSourceLabel(row.cycle_source) }}</template></el-table-column>
            <el-table-column label="上次下单" prop="last_order_date" min-width="108" />
            <el-table-column label="提醒日期" prop="expected_order_date" min-width="108" />
            <el-table-column label="异常日期" prop="abnormal_date" min-width="108" />
            <el-table-column label="超期" min-width="80"><template #default="{ row }">{{ row.overdue_days ? `${row.overdue_days} 天` : '—' }}</template></el-table-column>
            <el-table-column label="历史金额" min-width="118"><template #default="{ row }">${{ money(row.lifetime_amount_usd) }}</template></el-table-column>
            <el-table-column label="偏好" min-width="190"><template #default="{ row }">{{ preferenceText(row) }}</template></el-table-column>
            <el-table-column label="建议动作" prop="recommended_action" min-width="300" />
          </el-table>
          <div class="oi-pagination"><el-pagination v-model:current-page="customers.page" v-model:page-size="customers.page_size" :total="customers.total" :page-sizes="[20, 50, 100]" layout="total,sizes,prev,pager,next" @size-change="changeCustomerPage" @current-change="changeCustomerPage" /></div>
        </div>
      </section>
    </template>

    <el-drawer v-model="aiBrief.visible" title="AI 经营简报" size="min(680px, 92vw)">
      <div class="oi-ai-brief">
        <el-alert :type="briefAlert.type" :title="briefAlert.title" :closable="false" show-icon />
        <pre>{{ briefDisplayContent }}</pre>
      </div>
      <template #footer><GlassButton v-if="['succeeded', 'failed'].includes(aiBrief.status)" variant="secondary" @click="generateBrief()">重新生成</GlassButton></template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { DataAnalysis, MagicStick } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import OrderFilters from './components/OrderFilters.vue'
import OrderTrendChart from './components/OrderTrendChart.vue'
import RepeatPurchaseTrendChart from './components/RepeatPurchaseTrendChart.vue'
import { useOrderIntelligence } from './composables/useOrderIntelligence'

const {
  activeTab, aiBrief, aiLoading, briefMatchesFilters, changeCustomerPage, changePeopleDimension,
  changeTab, changeTeam, countries, customerFilters, customers, detailLoading,
  error, filters, generateBrief, handleBriefAction, loadPage, loading, options, overview,
  people, peopleDimension, profiles, scopedUsers,
} = useOrderIntelligence()

const trendMode = ref('amount')
const briefButtonText = computed(() => {
  if (aiLoading.value) return '简报后台生成中'
  if (aiBrief.value.status === 'succeeded' && aiBrief.value.content && briefMatchesFilters.value) return '查看 AI 经营简报'
  return '生成 AI 经营简报'
})
const briefAlert = computed(() => {
  if (['queued', 'running'].includes(aiBrief.value.status)) return { type: 'info', title: '已转入后台生成，可以关闭弹窗；完成前不能重复提交' }
  if (aiBrief.value.status === 'failed') return { type: 'error', title: aiBrief.value.error_message || '简报生成失败，可重新提交' }
  if (aiBrief.value.source === 'ai') return { type: 'success', title: '已基于实时证据生成' }
  if (aiBrief.value.source === 'rules') return { type: 'warning', title: 'AI 不可用，当前为规则简报' }
  return { type: 'info', title: '等待生成简报' }
})
const briefDisplayContent = computed(() => {
  if (aiBrief.value.content) return aiBrief.value.content
  if (aiBrief.value.status === 'queued') return '任务已提交，正在等待后台执行…'
  if (aiBrief.value.status === 'running') return '正在汇总国家、人员与客户行动证据，完成后将自动显示…'
  return aiBrief.value.error_message || '暂无简报内容'
})
const number = value => Number(value || 0).toLocaleString('zh-CN')
const money = value => Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
const compactMoney = value => Number(value || 0).toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 1 })
const changeText = value => value == null ? '—' : `${value > 0 ? '+' : ''}${value}%`
const changeClass = value => value > 0 ? 'is-up' : (value < 0 ? 'is-down' : '')
const evidenceLabel = value => ({ high: '高证据', medium: '中证据', low: '小样本' }[value] || '待评估')
const scoreType = value => value >= 70 ? 'success' : (value >= 45 ? 'warning' : 'info')
const riskType = value => ({ abnormal: 'danger', due: 'warning', insufficient_data: 'info' }[value] || 'info')
const riskLabel = value => ({ abnormal: '周期异常', due: '到期提醒', insufficient_data: '样本不足' }[value] || value)
const cycleSourceLabel = value => ({ profile_robust: '同画像中位数', customer_robust: '客户历史中位数', insufficient_data: '样本不足' }[value] || '估算')
const ppChangeText = value => value == null ? '无上期' : `${value > 0 ? '+' : ''}${value}pp`
const growthText = value => value == null ? '新增' : `${value > 0 ? '+' : ''}${value}%`
const productQuantityText = item => `${number(item.quantity)} · ${growthText(item.quantity_growth)}`
const preferenceText = row => [...(row.top_models || []), ...(row.top_colors || [])].slice(0, 4).map(item => {
  const metric = Object.prototype.hasOwnProperty.call(item, 'previous_quantity')
    ? growthText(item.quantity_growth)
    : `${number(item.quantity)} 件`
  return `${item.name} ${metric}`
}).join(' / ') || '暂无稳定偏好'
</script>

<style scoped src="./order-intelligence.css"></style>
