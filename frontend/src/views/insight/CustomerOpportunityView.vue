<template>
  <div class="customer-opportunity">
    <!-- 顶部统计 -->
    <div class="co-stats">
      <div class="co-stat red clickable" @click="filters.status='pending'; applyFilters()">
        <div class="stat-icon"><el-icon><AlarmClock /></el-icon></div>
        <div>
          <div class="stat-label">今天还要跟进</div>
          <div class="stat-value"><strong>{{ stats.pending }}</strong><span>条 · 其中 {{ stats.overdue }} 条已超时</span></div>
          <div class="stat-hint danger-hint">↑ 先处理超时的</div>
        </div>
      </div>
      <div class="co-stat gold clickable" @click="filters.priority_level='A'; applyFilters()">
        <div class="stat-icon"><el-icon><Medal /></el-icon></div>
        <div>
          <div class="stat-label">高价值客户等你回复</div>
          <div class="stat-value"><strong>{{ stats.a_count }}</strong><span>条 A 类</span></div>
          <div class="stat-hint gold-hint">点击查看 →</div>
        </div>
      </div>
      <div class="co-stat orange clickable" @click="filters.status='pending'; applyFilters()">
        <div class="stat-icon"><el-icon><Timer /></el-icon></div>
        <div>
          <div class="stat-label">已超过最佳回复窗口</div>
          <div class="stat-value"><strong>{{ stats.overdue }}</strong><span>条待处理</span></div>
          <div class="stat-hint orange-hint">点击快速处理 →</div>
        </div>
      </div>
      <div class="co-stat green">
        <div class="stat-icon"><el-icon><Phone /></el-icon></div>
        <div>
          <div class="stat-label">今天你已处理</div>
          <div class="stat-value"><strong>{{ stats.today_contacted }}</strong><span>条</span></div>
          <div class="stat-hint green-hint">✓ 继续保持</div>
        </div>
      </div>
    </div>

    <!-- 工具栏 -->
    <div class="co-toolbar">
      <div class="co-segments">
        <el-button
          v-for="g in gradeOptions" :key="g.value"
          :type="filters.priority_level === g.value ? 'warning' : 'default'"
          size="small" @click="filters.priority_level = g.value; applyFilters()"
        >{{ g.label }}</el-button>
      </div>
      <el-input
        v-model="filters.keyword" placeholder="搜索客户、产品..."
        clearable size="small" style="width: 240px; margin-left: 12px"
        @clear="applyFilters" @keyup.enter="applyFilters"
      />
    </div>

    <!-- 三栏布局 -->
    <div class="co-workspace">
      <!-- 左: 筛选面板 -->
      <div class="co-filter-panel">
        <div class="panel-header">机会状态</div>
        <div class="filter-group">
          <div
            v-for="s in statusOptions" :key="s.value"
            class="filter-option" :class="{ active: filters.status === s.value }"
            @click="filters.status = s.value; applyFilters()"
          >
            <span>{{ s.label }}</span>
            <span class="count">{{ s.count }}</span>
          </div>
        </div>

        <div class="panel-header" style="margin-top: 12px">来源</div>
        <div class="filter-group">
          <div
            v-for="src in sourceOptions" :key="src.value"
            class="filter-option" :class="{ active: filters.source === src.value }"
            @click="filters.source = src.value; applyFilters()"
          >
            <span>{{ src.label }}</span>
          </div>
        </div>
      </div>

      <!-- 中: 机会队列 -->
      <div class="co-queue-panel">
        <el-table
          :data="opportunities" v-loading="loading"
          border class="list-table"
          highlight-current-row
          @current-change="row => selectOpportunity(row?.id)"
          :row-class-name="({ row }) => row.id === selectedId ? 'co-active-row' : ''"
          style="width: 100%"
        >
          <el-table-column label="客户信息" min-width="120" max-width="180">
            <template #default="{ row }">
              <div class="customer-name">
                {{ row.customer_name }}
                <el-tag v-if="row.status === 'pending' && row.urgency === 'urgent'" size="small" type="danger" effect="plain">新</el-tag>
              </div>
              <div class="customer-meta">{{ row.customer_region || '-' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="等级" min-width="60" max-width="90">
            <template #default="{ row }">
              <span class="co-grade" :class="row.priority_level?.toLowerCase()">{{ row.priority_level }}</span>
            </template>
          </el-table-column>
          <el-table-column label="紧急度" min-width="80" max-width="120">
            <template #default="{ row }">
              <span class="co-urgency" :class="row.urgency">{{ urgencyLabel(row.urgency) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="截止" min-width="120" max-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="co-due" :class="{ danger: isOverdue(row) }">{{ formatDue(row.due_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="90" max-width="135">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small" effect="plain">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="关键信号" min-width="140" max-width="210">
            <template #default="{ row }">
              <div class="co-tags">
                <el-tag v-for="t in (row.key_signals_json || []).slice(0, 3)" :key="t" size="small" type="info" effect="plain">{{ t }}</el-tag>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          v-if="total > pageSize"
          :current-page="page" :page-size="pageSize" :total="total"
          layout="prev, pager, next" small
          @current-change="handlePageChange"
          style="margin-top: 12px; justify-content: center"
        />
      </div>

      <!-- 右: 详情面板 -->
      <div class="co-detail-panel" v-loading="detailLoading">
        <template v-if="selectedOpp">
          <div class="detail-header">
            <h3>{{ selectedOpp.title }}</h3>
            <div class="detail-meta">
              <span>{{ selectedOpp.customer_name }}</span>
              <span>{{ selectedOpp.customer_region }}</span>
              <span>置信度 {{ selectedOpp.confidence_score }}%</span>
            </div>
          </div>

          <div class="detail-scroll">
            <!-- ① AI 结论 -->
            <div class="detail-section">
              <div class="section-title"><el-icon><Promotion /></el-icon> AI 结论</div>
              <ul class="verdict-list" v-if="selectedOpp.key_signals_json?.length">
                <li v-for="(v, i) in selectedOpp.key_signals_json.slice(0, 3)" :key="i">
                  <el-icon class="vi"><CircleCheck /></el-icon>
                  <span>{{ v }}</span>
                </li>
              </ul>
              <p v-else class="section-text">{{ selectedOpp.summary || '暂无结论' }}</p>
            </div>

            <!-- ② 关键指标 4格 -->
            <div class="detail-section">
              <div class="section-title"><el-icon><DataLine /></el-icon> 关键指标</div>
              <div class="kpi-row">
                <div class="kpi-card" :class="{ accent: selectedOpp.priority_level === 'A' }">
                  <div class="kpi-label">LEAD 评级</div>
                  <div class="kpi-value" :class="{ gold: selectedOpp.priority_level === 'A' }">{{ selectedOpp.priority_level || '-' }}</div>
                </div>
                <div class="kpi-card" :class="{ accent: selectedOpp.confidence_score >= 80 }">
                  <div class="kpi-label">置信度</div>
                  <div class="kpi-value" :class="{ gold: selectedOpp.confidence_score >= 80 }">{{ selectedOpp.confidence_score || 0 }}%</div>
                </div>
                <div class="kpi-card">
                  <div class="kpi-label">采购能力</div>
                  <div class="kpi-value">{{ selectedOpp.background_check_json?.purchase_capacity || '待确认' }}</div>
                </div>
                <div class="kpi-card">
                  <div class="kpi-label">建议跟进</div>
                  <div class="kpi-value" :class="{ green: selectedOpp.due_at && !isOverdue(selectedOpp) }">{{ formatDue(selectedOpp.due_at) }}</div>
                </div>
              </div>
            </div>

            <!-- ③ 推荐话术（上移） -->
            <div class="detail-section" v-if="selectedOpp.opening_message_en">
              <div class="section-title"><el-icon><ChatDotRound /></el-icon> 推荐回复话术</div>
              <div class="message-box">
                <div class="message-head">
                  <span>首回复（英文）</span>
                  <el-button size="small" @click="copyText(selectedOpp.opening_message_en)">复制</el-button>
                </div>
                <div class="message-body">{{ selectedOpp.opening_message_en }}</div>
              </div>
              <div class="message-box" v-if="selectedOpp.follow_up_message_en">
                <div class="message-head">
                  <span>二次追问（英文）</span>
                  <el-button size="small" @click="copyText(selectedOpp.follow_up_message_en)">复制</el-button>
                </div>
                <div class="message-body">{{ selectedOpp.follow_up_message_en }}</div>
              </div>
              <div class="feedback-row">
                <el-button size="small" @click="submitFeedback('useful', '有帮助')"><el-icon><Top /></el-icon> 有帮助</el-button>
                <el-button size="small" @click="feedbackReasonVisible = !feedbackReasonVisible"><el-icon><Bottom /></el-icon> 不准确</el-button>
              </div>
              <div class="feedback-reasons" v-if="feedbackReasonVisible">
                <div class="feedback-reasons-title">哪里不准确？</div>
                <div class="feedback-reasons-options">
                  <el-button
                    v-for="reason in feedbackReasons" :key="reason"
                    size="small" @click="handleFeedbackReason(reason)"
                  >{{ reason }}</el-button>
                </div>
              </div>
            </div>

            <!-- ④ AI 推荐策略 -->
            <div class="detail-section" v-if="selectedOpp.recommended_strategy">
              <div class="section-title"><el-icon><Guide /></el-icon> AI 推荐策略</div>
              <p class="section-text">{{ selectedOpp.recommended_strategy }}</p>
            </div>

            <!-- ⑤ 完整背调报告（折叠） -->
            <div class="detail-section">
              <button class="full-report-toggle" :class="{ open: showFullReport }" @click="showFullReport = !showFullReport">
                <span>📄 查看完整背调报告</span>
                <el-icon class="toggle-arrow"><ArrowDown /></el-icon>
              </button>
              <div class="full-report-body" :class="{ open: showFullReport }">
                <template v-if="selectedOpp.full_report_html" v-html="selectedOpp.full_report_html" />
                <template v-else>
                  <h4>背调信息</h4>
                  <table v-if="selectedOpp.background_check_json">
                    <tr v-for="(val, key) in filteredBackground" :key="key">
                      <td>{{ formatBgKey(key) }}</td>
                      <td>{{ val }}</td>
                    </tr>
                  </table>
                  <h4 v-if="selectedOpp.evidence_json">AI 评分依据</h4>
                  <template v-if="selectedOpp.evidence_json">
                    <div v-for="(val, key) in selectedOpp.evidence_json" :key="key">
                      <strong>{{ formatBgKey(key) }}：</strong>{{ val }}
                    </div>
                  </template>
                  <p v-else style="color: var(--text-muted);">暂无完整背调报告</p>
                </template>
              </div>
            </div>
          </div>

          <!-- 底部操作栏 -->
          <div class="detail-actions">
            <div class="detail-actions-primary">
              <el-button type="warning" size="default" @click="changeStatusAndNext('contacted')">✓ 标记已联系，处理下一条</el-button>
            </div>
            <div class="detail-actions-secondary">
              <el-button size="small" @click="changeStatus('replied')">有回复</el-button>
              <el-button size="small" @click="changeStatus('quoted')">已报价</el-button>
              <el-button size="small" @click="changeStatus('won')">已成交</el-button>
            </div>
            <div class="detail-actions-edge">
              <el-button size="small" @click="changeStatus('dismissed')"><el-icon><Close /></el-icon>忽略此机会</el-button>
              <el-button size="small" @click="changeStatus('lost')"><el-icon><User /></el-icon>已流失</el-button>
            </div>
          </div>
        </template>
        <template v-else>
          <div class="detail-empty">
            <el-empty description="选择一个机会查看详情" :image-size="80" />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { AlarmClock, Medal, Timer, Phone, CircleCheck, Search, Guide, ChatDotRound, Top, Bottom, Close, User, QuestionFilled, Promotion, DataLine, ArrowDown } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useCustomerOpportunity } from './composables/useCustomerOpportunity'

const {
  loading, opportunities, total, page, pageSize,
  selectedId, selectedOpp, detailLoading, stats, filters,
  isAdmin,
  reload, selectOpportunity, changeStatus, changeStatusAndNext,
  submitFeedback, handlePageChange, applyFilters,
} = useCustomerOpportunity()

// ── 配置数据 ──────────────────────────────────────────
const gradeOptions = [
  { value: null, label: '全部' },
  { value: 'A', label: 'A 类' },
  { value: 'B', label: 'B 类' },
  { value: 'C', label: 'C 类' },
  { value: 'D', label: 'D 类' },
]

const statusOptions = [
  { value: null, label: '全部', count: stats.value.total },
  { value: 'pending', label: '待处理', count: stats.value.pending },
  { value: 'contacted', label: '已联系', count: stats.value.contacted },
  { value: 'replied', label: '有回复', count: stats.value.replied },
  { value: 'quoted', label: '已报价', count: stats.value.quoted },
  { value: 'won', label: '已成交', count: stats.value.won },
]

const sourceOptions = [
  { value: null, label: '全部来源' },
  { value: 'alibaba_international', label: '阿里询盘' },
]

// ── 格式化 helpers ──────────────────────────────────────
const showEvidence = ref(false)
const showFullReport = ref(false)
const feedbackReasonVisible = ref(false)
const feedbackReasons = ['客户类型判断有误', '产品方向不匹配', '不归我负责', '话术风格不合适']

const filteredBackground = computed(() => {
  if (!selectedOpp.value?.background_check_json) return {}
  const result = {}
  for (const [k, v] of Object.entries(selectedOpp.value.background_check_json)) {
    if (typeof v === 'string' || typeof v === 'number') result[k] = v
  }
  return result
})

async function handleFeedbackReason(reason) {
  await submitFeedback('not_useful', reason)
  feedbackReasonVisible.value = false
  ElMessage.success(`已反馈：${reason}，下次会更准`)
}

function urgencyLabel(u) {
  return { urgent: '紧急', high: '高', normal: '中', low: '低' }[u] || u
}

function statusLabel(s) {
  return {
    pending: '待处理', contacted: '已联系', replied: '有回复',
    quoted: '已报价', won: '已成交', lost: '已流失', dismissed: '无价值',
  }[s] || s
}

function statusTagType(s) {
  return {
    pending: 'warning', contacted: 'success', replied: '',
    quoted: 'info', won: 'success', lost: 'danger', dismissed: 'info',
  }[s] || 'info'
}

function formatDue(d) {
  if (!d) return '-'
  const date = new Date(d)
  const now = new Date()
  const diff = (date - now) / 3600000
  if (diff < 0) return '已超时'
  if (diff < 2) return `${Math.round(diff * 60)}分钟`
  if (diff < 24) return `${Math.round(diff)}小时`
  return `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:00`
}

function isOverdue(row) {
  if (!row.due_at || row.status !== 'pending') return false
  return new Date(row.due_at) < new Date()
}

function formatBgKey(key) {
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}
</script>

<style scoped>
.customer-opportunity { padding: 24px 28px; display: flex; flex-direction: column; gap: 16px; height: 100%; }

/* 统计卡 */
.co-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.co-stat {
  background: var(--card-bg); border: 1px solid var(--border-color);
  border-radius: var(--card-radius); padding: 14px 16px; display: flex; align-items: center; gap: 12px;
  box-shadow: var(--card-shadow);
}
.co-stat.clickable { cursor: pointer; transition: box-shadow .16s, transform .16s; }
.co-stat.clickable:hover { box-shadow: 0 4px 12px rgba(0,0,0,.08); transform: translateY(-1px); }
.stat-icon { width: 38px; height: 38px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0; }
.stat-icon .el-icon { font-size: 18px; }
.co-stat.red .stat-icon { color: var(--el-color-danger); background: rgba(245,108,108,.08); }
.co-stat.gold .stat-icon { color: var(--color-primary); background: var(--primary-light); }
.co-stat.orange .stat-icon { color: #b87800; background: rgba(184,120,0,.08); }
.co-stat.green .stat-icon { color: var(--el-color-success); background: rgba(103,194,58,.08); }
.stat-label { color: var(--text-secondary); font-size: 12px; font-weight: 600; }
.stat-value strong { font-size: 22px; font-family: var(--font-display); color: var(--text-primary); }
.stat-value span { color: var(--text-muted); font-size: 12px; margin-left: 4px; }
.stat-hint { font-size: 11px; margin-top: 3px; font-weight: 600; }
.stat-hint.danger-hint { color: var(--el-color-danger); }
.stat-hint.gold-hint { color: var(--color-primary); }
.stat-hint.orange-hint { color: #b87800; }
.stat-hint.green-hint { color: var(--el-color-success); }

/* 工具栏 */
.co-toolbar { display: flex; align-items: center; gap: 8px; }
.co-segments { display: inline-flex; gap: 4px; }

/* 三栏 */
.co-workspace { display: grid; grid-template-columns: 190px 1fr 480px; gap: 12px; flex: 1; min-height: 0; }

/* 左: 筛选 */
.co-filter-panel {
  background: var(--card-bg); border: 1px solid var(--border-color);
  border-radius: var(--card-radius); padding: 10px; overflow: auto;
}
.panel-header { font-weight: 700; font-size: 13px; padding: 6px 4px; color: var(--text-secondary); border-bottom: 1px solid var(--border-color); margin-bottom: 6px; }
.filter-group { display: flex; flex-direction: column; gap: 2px; }
.filter-option {
  height: 32px; display: flex; align-items: center; justify-content: space-between;
  padding: 0 9px; border-radius: 8px; cursor: pointer; font-size: 13px; color: var(--text-secondary);
}
.filter-option:hover { background: var(--toolbar-bg); }
.filter-option.active { background: var(--primary-light); color: #a66b0b; font-weight: 700; }
.filter-option .count { color: var(--text-muted); font-weight: 600; }

/* 中: 队列 */
.co-queue-panel {
  background: var(--card-bg); border: 1px solid var(--border-color);
  border-radius: var(--card-radius); padding: 12px; overflow: auto; display: flex; flex-direction: column;
  box-shadow: var(--card-shadow);
}
.customer-name { font-weight: 700; font-size: 13px; color: var(--text-primary); }
.customer-meta { color: var(--text-muted); font-size: 12px; margin-top: 2px; }
.co-grade {
  display: inline-block; width: 28px; height: 28px; line-height: 28px;
  border-radius: 50%; text-align: center; font-weight: 800; font-size: 14px; color: #fff;
  font-family: var(--font-display);
}
.co-grade.a { background: #e92f3c; }
.co-grade.b { background: #f08a19; }
.co-grade.c { background: #2d9f6f; }
.co-grade.d { background: #6b8cba; }
.co-urgency { font-size: 12px; font-weight: 700; }
.co-urgency.urgent { color: var(--el-color-danger); }
.co-urgency.high { color: #b87800; }
.co-urgency.normal { color: var(--el-color-primary); }
.co-due { font-size: 12px; color: var(--text-secondary); }
.co-due.danger { color: var(--el-color-danger); font-weight: 700; }
.co-tags { display: flex; flex-wrap: wrap; gap: 4px; }

/* 右: 详情 */
.co-detail-panel {
  background: var(--card-bg); border: 1px solid var(--border-color);
  border-radius: var(--card-radius); display: flex; flex-direction: column; min-height: 0; overflow: hidden;
  box-shadow: var(--card-shadow);
}
.detail-header { padding: 15px 16px; border-bottom: 1px solid var(--border-color); }
.detail-header h3 { margin: 0; font-size: 17px; font-family: var(--font-display); line-height: 1.3; color: var(--text-primary); }
.detail-meta { margin-top: 6px; color: var(--text-muted); font-size: 12px; display: flex; gap: 10px; }
.detail-scroll { overflow: auto; padding: 12px 14px; flex: 1; display: flex; flex-direction: column; gap: 10px; }
.detail-section {
  border: 1px solid var(--border-color); border-radius: 8px;
  background: var(--card-bg); padding: 12px;
}
.section-title { display: flex; align-items: center; gap: 7px; font-weight: 800; font-size: 13px; margin-bottom: 8px; color: var(--text-primary); }
.section-title .el-icon { color: var(--color-primary); }
.section-text { color: var(--text-secondary); line-height: 1.6; margin: 0; font-size: 13px; }

/* AI 结论 */
.verdict-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 7px; }
.verdict-list li {
  display: flex; align-items: flex-start; gap: 9px;
  background: linear-gradient(135deg, #fffbf0 0%, #fff8e8 100%);
  border: 1px solid #f0d8a8; border-radius: 8px; padding: 9px 12px;
  font-size: 13px; color: var(--text-primary); font-weight: 500; line-height: 1.5;
}
.verdict-list li .vi { color: var(--color-primary); flex-shrink: 0; margin-top: 1px; }

/* KPI 4格 */
.kpi-row { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.kpi-card {
  background: var(--toolbar-bg); border: 1px solid var(--border-color);
  border-radius: 8px; padding: 10px 12px; display: flex; flex-direction: column; gap: 3px;
}
.kpi-card.accent {
  background: linear-gradient(135deg, #fffbf0 0%, #fff5e0 100%);
  border-color: #f0d8a8;
}
.kpi-label { font-size: 11px; color: var(--text-muted); font-weight: 600; letter-spacing: 0.05em; }
.kpi-value { font-size: 15px; font-weight: 700; color: var(--text-primary); }
.kpi-value.gold { color: var(--color-primary); }
.kpi-value.green { color: var(--el-color-success); }

/* 完整背调折叠 */
.full-report-toggle {
  width: 100%; padding: 9px 14px; background: var(--toolbar-bg);
  border: 1px dashed var(--border-color); border-radius: 8px; cursor: pointer;
  display: flex; align-items: center; justify-content: space-between;
  font-size: 12px; color: var(--text-secondary); font-weight: 600;
}
.full-report-toggle:hover { background: #f5f7ff; border-color: #c5cce0; }
.full-report-toggle .toggle-arrow { transition: transform 0.2s; }
.full-report-toggle.open .toggle-arrow { transform: rotate(180deg); }
.full-report-body {
  display: none; margin-top: 8px; background: var(--toolbar-bg);
  border: 1px solid var(--border-color); border-radius: 8px; padding: 14px;
  font-size: 12px; color: var(--text-secondary); line-height: 1.7;
}
.full-report-body.open { display: block; }
.full-report-body :deep(h4) { font-size: 12px; font-weight: 700; color: var(--text-primary); margin: 12px 0 5px; }
.full-report-body :deep(h4:first-child) { margin-top: 0; }
.full-report-body :deep(table) { width: 100%; border-collapse: collapse; font-size: 12px; }
.full-report-body :deep(td) { padding: 4px 8px; border-bottom: 1px solid #eef0f8; vertical-align: top; }
.full-report-body :deep(td:first-child) { font-weight: 600; color: var(--text-primary); width: 40%; white-space: nowrap; }
.full-report-body :deep(ul) { margin: 4px 0 0 0; padding-left: 16px; }
.full-report-body :deep(li) { margin-bottom: 3px; }

/* 话术 */
.message-box { border: 1px solid #f0d8a8; border-radius: 8px; overflow: hidden; margin-top: 8px; background: #fffdf9; }
.message-head {
  height: 32px; background: #fff7e5; border-bottom: 1px solid #f0d8a8;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 9px; color: #9a650b; font-weight: 700; font-size: 12px;
}
.message-body { padding: 10px; color: var(--text-primary); line-height: 1.55; font-size: 13px; white-space: pre-wrap; }
.feedback-row { display: flex; gap: 8px; margin-top: 9px; }

/* 底部操作 */
.detail-actions {
  display: flex; flex-direction: column; gap: 8px;
  padding: 12px 14px; border-top: 1px solid var(--border-color);
}
.detail-actions-primary .el-button { width: 100%; height: 38px; font-size: 14px; }
.detail-actions-secondary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.detail-actions-secondary .el-button { justify-content: center; }
.detail-actions-edge { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; }
.detail-actions-edge .el-button { justify-content: center; color: var(--text-muted); border-style: dashed; }
.detail-actions-edge .el-button:hover { color: var(--text-secondary); border-style: solid; }

/* 反馈原因 */
.feedback-reasons {
  margin-top: 9px; padding: 10px; background: #fffaf0;
  border: 1px solid #f0d8a8; border-radius: 8px;
}
.feedback-reasons-title { font-size: 12px; color: #9a650b; font-weight: 700; margin-bottom: 7px; }
.feedback-reasons-options { display: flex; flex-wrap: wrap; gap: 6px; }
.detail-empty { display: grid; place-items: center; flex: 1; }
</style>
