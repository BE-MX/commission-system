<template>
  <el-drawer class="customer-hub-drawer" v-model="visible" title="公海筛选规则" size="min(820px, 100vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
    <div v-loading="loading" class="rule-panel">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <template v-if="draft">
        <div class="rule-intro"><el-tag :type="version ? 'success' : 'info'">{{ version ? `已保存 · 版本 ${version}` : '推荐草稿 · 尚未启用' }}</el-tag><span v-if="dirty">有未保存修改</span><el-button link :disabled="busy" @click="load">重新加载已保存规则</el-button></div>
        <p class="hint">保存后用于后续定时批次和新建批次，已有批次保留原规则。仅筛选身份已确认、无主负责人且允许开发的活跃客户。</p>
        <el-radio-group :model-value="mode" :disabled="busy" aria-label="规则编辑方式" @change="switchMode"><el-radio-button value="visual">可视化配置</el-radio-button><el-radio-button value="json">高级 JSON</el-radio-button></el-radio-group>
        <el-input v-if="mode === 'json'" v-model="jsonText" :disabled="busy" type="textarea" :rows="26" aria-label="高级规则 JSON" class="json-editor" />
        <el-form v-else label-position="top" :disabled="busy" class="rules-form">
          <section class="rule-section"><h3>成交条件 <small>以下任一成立</small></h3>
            <div class="rule-grid"><el-form-item label="至少成交单数"><el-input-number v-model="draft.rules.commerce.min_orders" :min="1" :max="10000" /></el-form-item><el-form-item label="且累计金额大于（美元）"><el-input-number v-model="draft.rules.commerce.total_usd_gt" :min="0" :max="1000000000" :precision="2" /></el-form-item><el-form-item label="或者，单笔金额大于（美元）"><el-input-number v-model="draft.rules.commerce.single_usd_gt" :min="0" :max="1000000000" :precision="2" /></el-form-item></div>
            <el-checkbox v-model="draft.rules.commerce.allow_sample_only">或者，仅成交过样品订单</el-checkbox>
            <el-checkbox v-if="draft.rules.commerce.allow_sample_only" v-model="draft.rules.commerce.sample_requires_product">纯样品客户也须符合下方产品条件</el-checkbox>
            <p class="hint">按有效订单统计；纯样品要求每笔订单都有明细且全部明确标为样品。未知类型不会当作样品。</p>
          </section>
          <section class="rule-section"><h3>国家与联系渠道 <small>同时满足</small></h3>
            <el-form-item label="客户国家（可输入其他两位国家代码）"><el-select v-model="draft.rules.countries" multiple filterable allow-create default-first-option aria-label="客户国家"><el-option v-for="[code, label] in COUNTRY_OPTIONS" :key="code" :label="`${label} · ${code}`" :value="code" /></el-select></el-form-item>
            <el-form-item label="至少拥有一个渠道"><el-checkbox-group v-model="draft.rules.contact_channels"><el-checkbox value="instagram">Instagram</el-checkbox><el-checkbox value="facebook">Facebook</el-checkbox><el-checkbox value="phone">电话</el-checkbox></el-checkbox-group></el-form-item>
            <el-checkbox v-model="draft.rules.prefer_instagram">配额内优先选择有 Instagram 的客户</el-checkbox><p class="hint">失效、争议、退订、退信或禁止联系的渠道不计入。</p>
          </section>
          <section class="rule-section"><h3>成交产品 <small>命中任一产品词</small></h3>
            <el-form-item label="产品词（输入后按回车添加）"><el-select v-model="draft.rules.product_terms" multiple filterable allow-create default-first-option aria-label="产品词"><el-option v-for="term in draft.rules.product_terms" :key="term" :label="term" :value="term" /></el-select></el-form-item>
            <el-form-item label="排除词（避免胶水、卸胶剂等被误认）"><el-select v-model="draft.rules.product_exclusions" multiple filterable allow-create default-first-option aria-label="产品排除词"><el-option v-for="term in draft.rules.product_exclusions" :key="term" :label="term" :value="term" /></el-select></el-form-item>
            <p class="hint">匹配有效订单明细的产品族、型号和名称，忽略大小写、空格与连字符。平型对应 Flat Tip。</p>
          </section>
          <section class="rule-section"><h3>沉默周期 <small>同时满足</small></h3><div class="rule-grid">
            <el-form-item label="近多少天没有下单"><el-input-number v-model="draft.rules.no_order_days" :min="1" :max="3650" /></el-form-item><el-form-item label="最近跟进久于多少天"><el-input-number v-model="draft.rules.no_followup_days" :min="1" :max="3650" /></el-form-item></div>
            <el-form-item label="缺少跟进日期时"><el-radio-group v-model="draft.rules.missing_followup"><el-radio value="exclude">排除，待补资料</el-radio><el-radio value="include">允许入选</el-radio></el-radio-group></el-form-item>
            <p class="hint">按北京时间判断，临界日有订单或临界时刻有跟进均排除。跟进取最近客户会话或对外销售活动；缺少订单日期始终排除。</p>
          </section>
          <section class="rule-section"><h3>每批配额</h3><div class="rule-grid"><el-form-item v-for="tier in ['T1', 'T2', 'T3']" :key="tier" :label="`${tier} 最多客户数`"><el-input-number v-model="draft.quotas.tiers[tier]" :min="0" :max="500" /></el-form-item><el-form-item label="总量上限"><el-input-number v-model="draft.quotas.total_limit" :min="1" :max="1500" /></el-form-item></div><p class="hint">沿用目标匹配分档：T1 ≥ 80，T2 ≥ 60，其余 T3。各档配额与总上限同时生效。</p></section>
        </el-form>
        <section v-if="preview" class="rule-section preview" aria-label="筛选预览">
          <h3>筛选预览 <small>{{ previewStale ? '条件已修改，请重新预览' : '仅统计，不创建研究任务' }}</small></h3>
          <div class="preview-counts"><span>活跃客户 <b>{{ preview.candidate_count }}</b></span><span>符合规则 <b>{{ preview.eligible_count }}</b></span><span>配额内入选 <b>{{ preview.selected_count }}</b></span><span>其中 Instagram <b>{{ preview.instagram_selected }}</b></span></div>
          <p class="hint">T1 {{ preview.selected_by_tier.T1 }} · T2 {{ preview.selected_by_tier.T2 }} · T3 {{ preview.selected_by_tier.T3 }}。每位客户计入首个未通过条件，排除数不重复。</p>
          <div class="exclusions"><span v-for="reason in preview.exclusions" :key="reason.code">{{ reason.label }} <b>{{ reason.count }}</b></span></div>
        </section>
        <el-alert v-if="batchResult" type="success" :title="`批次已就绪，共选中 ${batchResult.selection_snapshot?.selected_count ?? 0} 位客户。相同日期、规则和输入范围的重复请求复用原批次。`" :closable="false" show-icon />
      </template>
      <el-button v-else-if="!loading" @click="load">重新加载规则</el-button>
    </div>
    <template #footer><div class="footer"><GlassButton variant="ghost" :disabled="busy || !draft" @click="runPreview">预览筛选</GlassButton><GlassButton variant="primary" :loading="saving" :disabled="busy || !draft" @click="save">保存规则</GlassButton><GlassButton variant="success" :loading="creating" :disabled="busy || !version || dirty" @click="createBatch">按已保存规则创建批次</GlassButton></div></template>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { getPublicPoolRules, savePublicPoolRules, previewPublicPoolRules, createConfiguredPublicPoolBatch } from '@/api/customerHub'
import { COUNTRY_OPTIONS, parseRuleDocument, ruleDocument } from './poolRuleEditor'
import { msgSuccess } from '@/utils/feedback'
const visible = defineModel({ type: Boolean })
const emit = defineEmits(['created'])
const draft = ref(null), version = ref(0), savedText = ref(''), mode = ref('visual'), jsonText = ref('')
const loading = ref(false), saving = ref(false), creating = ref(false), previewing = ref(false), error = ref(''), preview = ref(null), previewText = ref(''), batchResult = ref(null)
const busy = computed(() => loading.value || saving.value || creating.value || previewing.value)
function payload() { return parseRuleDocument(mode.value === 'json' ? jsonText.value : JSON.stringify(draft.value)) }
const currentText = computed(() => { try { return JSON.stringify(payload()) } catch { return '' } })
const dirty = computed(() => !currentText.value || currentText.value !== savedText.value)
const previewStale = computed(() => currentText.value !== previewText.value)
function failure(e) { const detail = e?.response?.data?.detail; error.value = typeof detail === 'string' ? detail : e?.message || '操作失败，请重试。' }
async function load() { if (busy.value) return; loading.value = true; error.value = ''; try { const { data } = await getPublicPoolRules(); draft.value = ruleDocument(data); version.value = data.version; savedText.value = JSON.stringify(draft.value); jsonText.value = JSON.stringify(draft.value, null, 2); preview.value = null; batchResult.value = null } catch (e) { failure(e) } finally { loading.value = false } }
function switchMode(next) { try { if (next === 'visual') draft.value = payload(); else jsonText.value = JSON.stringify(draft.value, null, 2); mode.value = next; error.value = '' } catch (e) { failure(e) } }
async function runPreview() { if (busy.value) return; error.value = ''; try { const body = payload(); previewing.value = true; const { data } = await previewPublicPoolRules(body); preview.value = data; previewText.value = JSON.stringify(body) } catch (e) { failure(e) } finally { previewing.value = false } }
async function save() { if (busy.value) return; error.value = ''; try { const body = payload(); saving.value = true; const { data } = await savePublicPoolRules({ ...body, expected_version: version.value }); draft.value = ruleDocument(data); version.value = data.version; savedText.value = JSON.stringify(draft.value); jsonText.value = JSON.stringify(draft.value, null, 2); batchResult.value = null; msgSuccess('公海筛选规则已保存') } catch (e) { failure(e) } finally { saving.value = false } }
async function createBatch() { if (busy.value || dirty.value || !version.value) return; creating.value = true; error.value = ''; try { const { data } = await createConfiguredPublicPoolBatch({ expected_version: version.value }); batchResult.value = data; emit('created'); msgSuccess('公海批次已就绪') } catch (e) { failure(e) } finally { creating.value = false } }
watch(visible, value => { if (value && !draft.value) load() })
</script>

<style scoped>
.rule-panel { display: grid; gap: 16px; min-height: 120px; }.rule-intro,.footer { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }.rule-intro { font-size: 13px; color: var(--text-secondary); }.hint { color: var(--text-secondary); font-size: 13px; line-height: 1.7; margin: 8px 0 0; }.rules-form { display: grid; gap: 16px; }.rule-section { padding: 16px; border: 1px solid var(--border-color); border-radius: 10px; }.rule-section h3 { font-size: 15px; margin: 0 0 16px; }.rule-section small { display: inline-block; font-weight: 400; color: var(--text-secondary); margin-left: 8px; font-size: 12px; }.rule-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }.rule-grid :deep(.el-input-number) { width: 100%; }.rule-section :deep(.el-select) { width: 100%; }.rule-section :deep(.el-checkbox) { white-space: normal; height: auto; min-height: 32px; }.preview-counts,.exclusions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }.preview-counts span,.exclusions span { display: flex; justify-content: space-between; gap: 8px; }.exclusions { margin-top: 16px; font-size: 13px; color: var(--text-secondary); }.footer { justify-content: flex-end; }.json-editor :deep(textarea) { font-family: monospace; }
@media (max-width: 520px) { .rule-grid,.exclusions { grid-template-columns: 1fr; }.rule-section { padding: 12px; }.rule-section small { display: block; margin: 6px 0 0; }.footer { justify-content: stretch; }.footer > * { flex: 1 1 auto; } }
</style>
