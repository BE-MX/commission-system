<template>
  <DetailDrawer
    :model-value="modelValue" :title="title" width="min(1080px, 100vw)" :loading="loading && !detail"
    @update:model-value="$emit('update:modelValue', $event)" @closed="onClosed"
  >
    <div v-if="detail" class="dd">
      <header class="dd-head">
        <span class="dd-chip" :style="{ background: chip(detail.stats.avg_lab) }" />
        <div>
          <h3>
            {{ detail.color_code }}
            <span class="tag tag-mute">{{ sizeLabel(detail.size_value, detail.size_unit) }}</span>
            <span class="tag" :class="detail.library_scope === 'public' ? 'tag-gold' : 'tag-info'">
              {{ detail.library_scope === 'public' ? '公库' : '私库' }}
            </span>
          </h3>
          <p>{{ detail.display_name || '—' }}<template v-if="detail.customer_name"> · {{ detail.customer_name }}</template></p>
        </div>
      </header>

      <div class="dd-body">
        <div class="dd-main">
          <section class="card">
            <h4>测量统计 <span class="muted">ΔE00 · 后端按参与组重算</span></h4>
            <div class="kpis">
              <div class="kpi">
                <span>平均 Lab</span>
                <b class="lab">{{ detail.stats.avg_lab ? detail.stats.avg_lab.map((v) => fmt(v)).join(' / ') : '—' }}</b>
                <small>{{ detail.stats.count ? `${detail.stats.count} 组参与平均` : '尚未测量' }}</small>
              </div>
              <div class="kpi hl">
                <span>组内平均 ΔE</span>
                <b>{{ fmt(detail.stats.mean_de) }}</b>
                <small>{{ spreadHint }}</small>
              </div>
              <div class="kpi">
                <span>组内最大 ΔE</span>
                <b>{{ fmt(detail.stats.max_de) }}</b>
                <small>单组偏离均值的最大值</small>
              </div>
              <div class="kpi" :class="{ warn: detail.verdict === 'warn' }">
                <span>对基准 ΔE</span>
                <b :class="detail.verdict === 'warn' ? 't-warn' : detail.stats.base_de != null ? 't-ok' : ''">{{ fmt(detail.stats.base_de) }}</b>
                <small>{{ baseHint }}</small>
              </div>
            </div>
            <div v-if="detail.base?.lab && detail.stats.avg_lab" class="compare">
              <span class="cmp" :style="{ background: chip(detail.base.lab) }"><em>基准 {{ detail.base.color_code }}</em></span>
              <span class="cmp-mid">ΔE00<b>{{ fmt(detail.stats.base_de) }}</b></span>
              <span class="cmp" :style="{ background: chip(detail.stats.avg_lab) }"><em>本色板均值</em></span>
            </div>
          </section>

          <section class="card">
            <h4>
              测量记录
              <el-segmented v-model="view" :options="VIEWS" class="dd-views" />
            </h4>
            <MeasurementTable
              :measurements="detail.measurements" :avg-lab="detail.stats.avg_lab" :view="view"
              :writable="detail.can_write" :fresh-ids="freshIds" @toggle="toggleInclusion"
            />
            <div v-for="(r, i) in meter.lateReadings.value" :key="i" class="late">
              <span class="tag tag-warn">待确认</span>
              <span class="late-txt">
                超时后到达的读数 L {{ fmt(r.lab[0]) }} a {{ fmt(r.lab[1]) }} b {{ fmt(r.lab[2]) }}，未计入平均
              </span>
              <el-button :disabled="!detail.can_write" @click="acceptLate(r)">计入本色板</el-button>
              <el-button @click="meter.takeLate(r)">丢弃</el-button>
            </div>
          </section>
        </div>

        <aside class="dd-side">
          <section class="card">
            <MeasurePanel :meter="meter" :writable="detail.can_write && detail.record_status === 'active'" @measure="measure" />
          </section>
          <section class="card">
            <h4>色板属性</h4>
            <dl class="props">
              <dt>色号</dt><dd>{{ detail.color_code }}</dd>
              <dt>尺寸</dt><dd>{{ detail.size_value }} {{ detail.size_unit }}</dd>
              <dt>名称</dt><dd>{{ detail.display_name || '—' }}</dd>
              <template v-if="detail.customer_name"><dt>客户</dt><dd>{{ detail.customer_name }}</dd></template>
              <dt>对比基准</dt><dd>{{ detail.base ? `公库 ${detail.base.color_code}` : '—' }}</dd>
              <dt>允许色差</dt>
              <dd>
                <template v-if="!editingTol">ΔE ≤ {{ detail.tolerance_de }}
                  <el-button v-if="detail.can_write" link type="primary" @click="startTol">修改</el-button>
                </template>
                <span v-else class="tol-edit">
                  <el-input-number v-model="tolDraft" :min="0.1" :max="20" :step="0.1" :precision="2" controls-position="right" class="tol-input" />
                  <el-button type="primary" @click="saveTol">保存</el-button>
                  <el-button @click="editingTol = false">取消</el-button>
                </span>
              </dd>
            </dl>
            <div v-if="detail.can_write" class="props-actions">
              <el-button
                v-if="detail.library_scope === 'private'"
                :disabled="!detail.stats.count || detail.promotion_status === 'pending' || detail.promotion_status === 'approved'"
                @click="promote"
              >{{ promoteLabel }}</el-button>
              <el-button type="danger" plain @click="archive">归档</el-button>
            </div>
          </section>
        </aside>
      </div>
    </div>
  </DetailDrawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import {
  addSwatchMeasurements, archiveLibrarySwatch, getLibrarySwatch, requestSwatchPromotion,
  setMeasurementInclusion, updateLibrarySwatch,
} from '@/api/colorLibrary'
import { labToRgb, rgbCss } from '@/services/colorimeter/deltaE.js'
import { confirmDanger, msgError, msgSuccess, msgSuccessText, promptAction, isFeedbackCancelled } from '@/utils/feedback'
import MeasurePanel from './MeasurePanel.vue'
import MeasurementTable from './MeasurementTable.vue'
import { fmt, sizeLabel, toMeasurementPayload } from './swatchFormat.js'

const props = defineProps({
  modelValue: Boolean,
  swatchId: { type: Number, default: null },
  meter: { type: Object, required: true },
})
const emit = defineEmits(['update:modelValue', 'changed', 'archived'])

const VIEWS = [
  { label: 'Lab', value: 'lab' },
  { label: 'CMYK / RGB', value: 'cmyk' },
  { label: '全部空间', value: 'all' },
]
const detail = ref(null)
const loading = ref(false)
const view = ref('lab')
const freshIds = ref(new Set())
const editingTol = ref(false)
const tolDraft = ref(1.5)

const title = computed(() => (detail.value ? `色板 ${detail.value.color_code}` : '色板详情'))
const chip = (lab) => (lab ? rgbCss(labToRgb(lab)) : 'var(--button-quiet-hover)')
const spreadHint = computed(() => {
  const v = detail.value?.stats.mean_de
  if (v == null) return '至少 2 组'
  return v > 0.8 ? '离散偏大，建议加测' : '测量一致性良好'
})
const baseHint = computed(() => {
  const d = detail.value
  if (!d.base) return '未设置基准'
  if (!d.stats.count) return '待测量'
  return `${d.verdict === 'warn' ? '超出' : '符合'}阈值 ${d.tolerance_de}`
})
const promoteLabel = computed(() => ({
  pending: '纳入公库审核中', approved: '已纳入公库', rejected: '重新申请纳入公库',
}[detail.value?.promotion_status] || '申请纳入公库'))

function apply(data, { fresh = [] } = {}) {
  detail.value = data
  freshIds.value = new Set(fresh)
  const { measurements, base, ...card } = data
  emit('changed', card)
}

async function load() {
  if (!props.swatchId) return
  loading.value = true
  try {
    const res = await getLibrarySwatch(props.swatchId)
    detail.value = res.data
  } catch (err) {
    msgError(err?.response?.data?.detail || '色板加载失败', err)
    emit('update:modelValue', false)
  } finally {
    loading.value = false
  }
}

watch(() => [props.modelValue, props.swatchId], ([open]) => { if (open) load() }, { immediate: true })

async function persist(swatchId, readings, receiptStatus = 'matched') {
  const before = new Set((detail.value?.measurements || []).map((m) => m.id))
  const res = await addSwatchMeasurements(swatchId, readings.map((r) => toMeasurementPayload(r, { receiptStatus })))
  if (detail.value?.id === swatchId) {
    apply(res.data, { fresh: res.data.measurements.filter((m) => !before.has(m.id)).map((m) => m.id) })
  }
  return res.data
}

async function measure(count) {
  // Snapshot target before the first command so a late swatch switch cannot misfile readings.
  const target = detail.value
  if (!target) return
  const done = await props.meter.measureSeries(count, async (reading) => {
    try {
      await persist(target.id, [reading])
    } catch (err) {
      msgError(err?.response?.data?.detail || '测量值保存失败', err)
      throw err
    }
  }, { simTarget: target.stats.avg_lab || target.base?.lab || [45, 6, 14] })
  if (done) msgSuccessText(`已记录 ${done} 组测量`)
}

async function acceptLate(reading) {
  try {
    await persist(detail.value.id, [reading], 'late')
    props.meter.takeLate(reading)
    msgSuccessText('已计入本色板')
  } catch (err) {
    msgError(err?.response?.data?.detail || '保存失败', err)
  }
}

async function toggleInclusion(m) {
  let reason = null
  if (m.is_included) {
    try {
      const { value } = await promptAction('剔除后原始读数保留，仅不参与平均。请填写原因：', `剔除第 ${m.seq_no} 组`, {
        inputPlaceholder: '如：测量位置偏移、样品褶皱',
        inputValidator: (v) => (v && v.trim() ? true : '请填写原因'),
      })
      reason = value
    } catch (err) {
      if (isFeedbackCancelled(err)) return
      throw err
    }
  }
  try {
    const res = await setMeasurementInclusion(detail.value.id, m.id, { is_included: !m.is_included, reason })
    apply(res.data)
    msgSuccessText(m.is_included ? '已剔除，统计已重算' : '已恢复，统计已重算')
  } catch (err) {
    msgError(err?.response?.data?.detail || '操作失败', err)
  }
}

function startTol() {
  tolDraft.value = detail.value.tolerance_de
  editingTol.value = true
}

async function saveTol() {
  try {
    const res = await updateLibrarySwatch(detail.value.id, { tolerance_de: tolDraft.value })
    apply(res.data)
    editingTol.value = false
    msgSuccess('修改阈值')
  } catch (err) {
    msgError(err?.response?.data?.detail || '修改失败', err)
  }
}

async function promote() {
  try {
    const res = await requestSwatchPromotion(detail.value.id)
    apply(res.data)
    msgSuccessText('已提交纳入公库申请，等待色彩管理员审核')
  } catch (err) {
    msgError(err?.response?.data?.detail || '申请失败', err)
  }
}

async function archive() {
  try {
    await confirmDanger('归档', `色板 ${detail.value.color_code}`, '归档后不再出现在列表中，测量记录保留。')
  } catch (err) {
    if (isFeedbackCancelled(err)) return
    throw err
  }
  try {
    await archiveLibrarySwatch(detail.value.id)
    emit('archived', detail.value.id)
    emit('update:modelValue', false)
    msgSuccess('归档')
  } catch (err) {
    msgError(err?.response?.data?.detail || '归档失败', err)
  }
}

function onClosed() {
  detail.value = null
  editingTol.value = false
  freshIds.value = new Set()
}
</script>

<style scoped>
.dd { display: grid; gap: 14px; }
.dd-head { display: flex; align-items: center; gap: 14px; }
.dd-chip { flex: 0 0 52px; height: 52px; border-radius: var(--card-radius); box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.08); }
.dd-head h3 { margin: 0; display: flex; align-items: center; gap: 8px; font: 700 18px var(--font-display); color: var(--text-primary); }
.dd-head p { margin: 2px 0 0; font-size: 12.5px; color: var(--text-muted); }
.dd-body { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 14px; align-items: start; }
.dd-main, .dd-side { display: grid; gap: 14px; min-width: 0; }
.card {
  background: var(--card-bg); border: 1px solid var(--border-color); border-radius: var(--card-radius);
  box-shadow: var(--card-shadow); padding: 16px 18px; min-width: 0; overflow: hidden;
}
.card h4 { margin: 0 0 12px; display: flex; align-items: center; gap: 8px; font: 700 14px var(--font-display); color: var(--text-primary); }
.muted { font: 500 11.5px var(--font-body); color: var(--text-muted); }
.dd-views { margin-left: auto; }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.kpi { border: 1px solid var(--border-color); border-radius: 10px; padding: 12px 14px; background: var(--card-bg); }
.kpi.hl { background: var(--color-gold-soft); border-color: var(--tag-gold-border); }
.kpi.warn { background: var(--tag-warning-bg); border-color: var(--tag-warning-border); }
.kpi span { font: 600 11.5px var(--font-display); color: var(--text-muted); }
.kpi b { display: block; margin-top: 4px; font: 800 22px var(--font-display); color: var(--text-primary); font-variant-numeric: tabular-nums; }
.kpi b.lab { font-size: 16px; line-height: 1.7; }
.kpi b.t-ok { color: var(--button-success-text); }
.kpi b.t-warn { color: var(--button-warning-text); }
.kpi small { font-size: 11.5px; color: var(--text-secondary); }

.compare { display: flex; align-items: center; gap: 14px; margin-top: 14px; }
.cmp { position: relative; flex: 1; height: 56px; border-radius: 10px; box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.07); }
.cmp em { position: absolute; left: 10px; bottom: 7px; font: 600 11px var(--font-display); font-style: normal; color: var(--text-on-dark); text-shadow: 0 1px 2px rgb(0 0 0 / 0.4); }
.cmp-mid { text-align: center; font: 600 11px var(--font-display); color: var(--text-muted); }
.cmp-mid b { display: block; font: 800 18px var(--font-display); color: var(--text-primary); }

.late {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; padding: 10px 12px;
  border: 1px dashed var(--tag-warning-border); background: var(--tag-warning-bg); border-radius: 10px; font-size: 12.5px;
}
.late-txt { flex: 1; min-width: 180px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }

.props { display: grid; grid-template-columns: auto 1fr; gap: 8px 14px; margin: 0; font-size: 13px; }
.props dt { color: var(--text-muted); }
.props dd { margin: 0; font-weight: 600; color: var(--text-primary); }
.tol-edit { display: inline-flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.tol-input { width: 120px; }
.props-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }

.tag { display: inline-flex; align-items: center; height: 20px; padding: 0 7px; border-radius: var(--radius-sm, 6px); font: 600 11px var(--font-display); }
.tag-gold { background: var(--tag-gold-bg); color: var(--tag-gold-text); }
.tag-info { background: var(--tag-info-bg); color: var(--color-info-text); }
.tag-warn { background: var(--tag-warning-bg); color: var(--tag-warning-text); }
.tag-mute { background: var(--button-quiet-hover); color: var(--text-secondary); }

@media (max-width: 1100px) { .dd-body { grid-template-columns: minmax(0, 1fr); } }
</style>
