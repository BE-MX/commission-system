<template>
  <div class="leads-page">
    <el-row :gutter="16" class="toolbar">
      <el-col :span="6">
        <el-input v-model="filters.keyword" placeholder="搜索姓名 / 电话 / 微信" clearable prefix-icon="Search" @keyup.enter="search" @clear="search" />
      </el-col>
      <el-col :span="4">
        <el-select v-model="filters.intent_level" placeholder="意向等级" clearable style="width: 100%" @change="search">
          <el-option v-for="l in ['A', 'B', 'C', 'D']" :key="l" :label="`${l} 级`" :value="l" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-input v-model="filters.expo_code" placeholder="展会编码" clearable @keyup.enter="search" @clear="search" />
      </el-col>
      <el-col :span="10">
        <GlassButton variant="primary" left-icon="Search" @click="search">查询</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card">
      <el-table :data="leads" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column prop="name" label="姓名" min-width="100" show-overflow-tooltip />
        <el-table-column prop="phone" label="电话" min-width="120" show-overflow-tooltip />
        <el-table-column label="核心需求" min-width="100">
          <template #default="{ row }">{{ NEED_LABELS[row.primary_need] || row.primary_need || '-' }}</template>
        </el-table-column>
        <el-table-column label="体验 / 生成" min-width="100">
          <template #default="{ row }">{{ row.session_count }} 次 / {{ row.result_count }} 张</template>
        </el-table-column>
        <el-table-column label="意向等级" min-width="90">
          <template #default="{ row }">
            <el-tag v-if="row.intent_level" size="small" :class="'intent-' + row.intent_level">{{ row.intent_level }} 级</el-tag>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="next_action" label="下一步动作" min-width="150" show-overflow-tooltip />
        <el-table-column prop="created_at" label="登记时间" min-width="150" show-overflow-tooltip />
        <el-table-column label="操作" min-width="140" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click="openDetail(row)">详情</GlassButton>
            <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>

    <DetailDrawer v-model="detailVisible" title="线索详情 · 会话回放" :width="720" :loading="detailLoading">
      <template v-if="detail">
          <div class="info-card">
            <div class="info-name">{{ detail.customer?.name }}</div>
            <div class="info-grid">
              <span>电话：{{ detail.customer?.phone || '-' }}</span>
              <span>微信：{{ detail.customer?.wechat_id || '-' }}</span>
              <span>核心需求：{{ NEED_LABELS[detail.customer?.primary_need] || detail.customer?.primary_need || '-' }}</span>
              <span>风格偏好：{{ detail.customer?.style_pref || '-' }}</span>
              <span>展会：{{ detail.customer?.expo_code || '-' }}</span>
            </div>
          </div>

          <div v-for="(s, si) in detail.sessions || []" :key="s.id" class="session-block">
            <div class="session-head">第 {{ si + 1 }} 次试戴 <el-tag size="small" effect="plain">{{ s.status }}</el-tag></div>
            <div v-if="s.analysis" class="tag-row">
              <el-tag v-if="s.analysis.face_shape" size="small" effect="plain">脸型：{{ FACE_LABELS[s.analysis.face_shape] || s.analysis.face_shape }}</el-tag>
              <el-tag v-if="s.analysis.skin_tone" size="small" effect="plain">
                肤色：{{ DEPTH_LABELS[s.analysis.skin_tone.depth] || s.analysis.skin_tone.depth }} · {{ TONE_LABELS[s.analysis.skin_tone.undertone] || s.analysis.skin_tone.undertone }}
              </el-tag>
              <el-tag v-if="s.analysis.temperament" size="small" effect="plain">气质：{{ s.analysis.temperament }}</el-tag>
              <el-tag v-if="s.analysis.suit_length" size="small" effect="plain">适合长度：{{ LENGTH_LABELS[s.analysis.suit_length] || s.analysis.suit_length }}</el-tag>
            </div>
            <div v-if="s.analysis?.display_notes" class="notes-line">{{ s.analysis.display_notes }}</div>
            <div v-if="s.analysis_internal" class="tag-row internal-row">
              <el-tag size="small" type="warning">仅内部</el-tag>
              <el-tag v-if="s.analysis_internal.hair_condition" size="small" type="warning" effect="plain">发况：{{ s.analysis_internal.hair_condition }}</el-tag>
              <el-tag v-if="s.analysis_internal.sales_note" size="small" type="warning" effect="plain">销售备注：{{ s.analysis_internal.sales_note }}</el-tag>
            </div>

            <div v-if="s.results?.length" class="result-grid">
              <div v-for="r in s.results" :key="r.id" class="result-item">
                <el-image :src="r.image_url" fit="cover" :preview-src-list="[r.image_url]" preview-teleported class="result-img" />
                <span v-if="r.reaction === 'loved'" class="loved-badge">♥ 心动</span>
                <!-- scene_json 双语义：无 wig 才是场景大片；tryon 结果的 scene 是可选生成场景 -->
                <div class="result-name">{{ r.wig_name }} <span class="muted">{{ !r.wig_id ? '场景大片' : (r.series === 'zhizhen' ? '至臻' : '经典') + (r.scene ? ' · ' + r.scene.label : '') }}</span></div>
              </div>
            </div>

            <div v-if="s.strategy" class="strategy-card">
              <div v-if="s.strategy.opener" class="strategy-row"><span class="strategy-label">开场</span>{{ s.strategy.opener }}</div>
              <div v-if="s.strategy.followup" class="strategy-row"><span class="strategy-label">跟进</span>{{ s.strategy.followup }}</div>
              <div v-for="(ob, oi) in s.strategy.objections || []" :key="oi" class="strategy-row">
                <span class="strategy-label">异议</span>
                <div class="qa"><div class="qa-q">Q：{{ ob.q }}</div><div class="qa-a">A：{{ ob.a }}</div></div>
              </div>
            </div>
          </div>

          <div v-if="detail.feedbacks?.length" class="feedback-block">
            <div class="session-head">跟进反馈</div>
            <el-timeline>
              <el-timeline-item v-for="(f, fi) in detail.feedbacks" :key="fi" :timestamp="f.created_at" placement="top">
                <el-tag v-if="f.intent_level" size="small" :class="'intent-' + f.intent_level">{{ f.intent_level }} 级</el-tag>
                <div v-if="f.notes" class="notes-line">{{ f.notes }}</div>
                <div v-if="f.next_action" class="notes-line">下一步：{{ f.next_action }}</div>
              </el-timeline-item>
            </el-timeline>
          </div>
        </template>
    </DetailDrawer>
  </div>
</template>

<script setup>
/**
 * 分页列表页标杆用例（2026-07-03 治理 F-2）：
 * useListPage（分页/搜索/loading 编排）+ feedback.js（统一提示与危险确认）+ DetailDrawer（抽屉骨架）。
 * 新的服务端分页列表页照此结构写；标记语言/样式规范仍参照 system/DictManagement.vue。
 */
import { onBeforeUnmount, ref, watch } from 'vue'
import { getLeads, getLeadDetail, deleteCustomer } from '@/api/expo'
import { useListPage } from '@/composables/useListPage'
import { msgSuccess, confirmDanger } from '@/utils/feedback'
import DetailDrawer from '@/components/DetailDrawer.vue'

const NEED_LABELS = { volume: '发量丰盈', gray_cover: '白发遮盖', style_change: '造型变换' }
const FACE_LABELS = { oval: '鹅蛋脸', round: '圆脸', square: '方脸', heart: '心形脸', long: '长脸', diamond: '菱形脸' }
const DEPTH_LABELS = { fair: '白皙', light: '偏白', medium: '自然', tan: '小麦' }
const TONE_LABELS = { cool: '冷调', warm: '暖调', neutral: '中性' }
const LENGTH_LABELS = { short: '短发', bob: '波波头', shoulder: '及肩', long: '长发' }

const {
  loading, list: leads, total, page, pageSize, searchForm: filters,
  fetchList: fetchLeads, handleSearch: search, handlePageChange, handleSizeChange,
} = useListPage(
  async ({ page, page_size, ...form }) => {
    const params = { page, page_size }
    for (const key of ['keyword', 'intent_level', 'expo_code']) {
      if (form[key]) params[key] = form[key]
    }
    const res = await getLeads(params)
    return res.data || {}
  },
  { searchForm: { keyword: '', intent_level: '', expo_code: '' } },
)

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)

// 展会现场节奏：话术在合成启动时并行生成，顾问等图期间就会打开详情——
// 话术/效果图未就绪时静默轮询，就绪或超时即停，不用反复关开抽屉
const DETAIL_POLL_MS = 5000
const DETAIL_POLL_MAX = 24 // 最多轮 2 分钟，防旧数据（永远无话术的历史会话）空转
let detailTimer = null
let detailCustomerId = null

// 只盯"话术真的在路上"的会话：generating=合成中（话术并行生成中）、
// done 且无话术=生成收尾的窗口期；analyzed/pending 是客户中途离开的死会话，不轮
function strategyPending(d) {
  return (d?.sessions || []).some(
    s => s.mode !== 'scene' && !s.strategy && ['generating', 'done'].includes(s.status),
  )
}

function stopDetailPolling() {
  if (detailTimer) clearInterval(detailTimer)
  detailTimer = null
}

function armDetailPolling() {
  stopDetailPolling()
  if (!strategyPending(detail.value)) return
  let ticks = 0
  detailTimer = setInterval(async () => {
    if (!detailVisible.value || ++ticks > DETAIL_POLL_MAX) {
      stopDetailPolling()
      return
    }
    try {
      const res = await getLeadDetail(detailCustomerId, { silent: true })
      detail.value = res.data
    } catch { /* 单次失败下一轮继续 */ }
    if (!strategyPending(detail.value)) stopDetailPolling()
  }, DETAIL_POLL_MS)
}

async function openDetail(row) {
  detailCustomerId = row.id
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const res = await getLeadDetail(row.id)
    detail.value = res.data
  } finally {
    detailLoading.value = false
  }
  armDetailPolling()
}

watch(detailVisible, v => { if (!v) stopDetailPolling() })
onBeforeUnmount(stopDetailPolling)

async function handleDelete(row) {
  try {
    await confirmDanger('删除', `线索 ${row.name}`, '将物理删除客户照片与全部试戴记录，不可恢复。')
  } catch { return }
  try {
    await deleteCustomer(row.id)
    msgSuccess('删除')
    fetchLeads()
  } catch { /* 拦截器已提示 */ }
}
</script>

<style scoped>
.toolbar { margin-bottom: 16px; }
.pager { margin-top: 16px; justify-content: flex-end; }
.muted { color: var(--text-muted); font-size: 12px; }

/* 意向等级 tag */
.intent-A { background: var(--color-danger-bg); border-color: var(--color-primary); color: var(--color-danger-text); font-weight: 700; }
.intent-B { background: var(--color-warning-bg); border-color: var(--color-gold-muted); color: var(--color-gold-muted, #b8860b); }
.intent-C { background: var(--toolbar-bg); border-color: var(--border-color); color: var(--text-secondary); }
.intent-D { background: var(--toolbar-bg); border-color: var(--border-color); color: var(--text-muted); }

/* 详情抽屉 */
.detail-body { min-height: 200px; }
.info-card {
  background: var(--toolbar-bg); border: 1px solid var(--border-color);
  border-radius: var(--card-radius); padding: 14px 16px; margin-bottom: 16px;
}
.info-name { font-size: 16px; font-weight: 700; color: var(--text-primary); margin-bottom: 8px; }
.info-grid { display: flex; flex-wrap: wrap; gap: 6px 20px; color: var(--text-secondary); font-size: 13px; }
.session-block, .feedback-block {
  border: 1px solid var(--border-color); border-radius: var(--card-radius);
  padding: 14px 16px; margin-bottom: 16px;
}
.session-head { font-weight: 600; color: var(--text-primary); margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.internal-row { padding: 6px 8px; border-radius: 6px; background: var(--color-warning-bg); }
.notes-line { color: var(--text-secondary); font-size: 13px; line-height: 1.6; margin-bottom: 6px; }
.result-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; margin: 10px 0; }
.result-item { position: relative; }
.result-img { width: 100%; aspect-ratio: 3 / 4; border-radius: 8px; display: block; }
.loved-badge {
  position: absolute; top: 6px; right: 6px; padding: 1px 8px; border-radius: 10px;
  background: var(--color-primary); color: #fff; font-size: 12px; font-weight: 600;
}
.result-name { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }
.strategy-card {
  background: var(--color-gold-soft); border-radius: 8px; padding: 10px 12px; margin-top: 8px;
}
.strategy-row { display: flex; gap: 8px; font-size: 13px; color: var(--text-primary); line-height: 1.6; margin-bottom: 6px; }
.strategy-row:last-child { margin-bottom: 0; }
.strategy-label {
  flex-shrink: 0; padding: 0 8px; height: 22px; line-height: 20px; border-radius: 4px;
  border: 1px solid var(--color-gold-muted); color: var(--color-gold-muted, #b8860b); font-size: 12px;
}
.qa-q { font-weight: 600; }
.qa-a { color: var(--text-secondary); }
</style>
