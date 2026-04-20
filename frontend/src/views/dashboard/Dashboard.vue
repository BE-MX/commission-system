<template>
  <div class="dashboard anim-stagger">
    <!-- Hero section: asymmetric layout -->
    <div class="hero">
      <div class="hero-content">
        <div class="hero-tag">COMMISSION SYSTEM</div>
        <h1 class="hero-title">莱莎提成管理</h1>
        <p class="hero-desc">员工属性 / 客户归属 / 回款同步 / 提成计算</p>
      </div>
      <div class="hero-visual">
        <div class="hex hex-1"></div>
        <div class="hex hex-2"></div>
        <div class="hex hex-3"></div>
        <div class="hex hex-ring"></div>
      </div>
    </div>

    <!-- Metric cards -->
    <div class="metrics">
      <div class="metric-card" :class="{ 'metric-alert': incompleteCount > 0 }">
        <div class="metric-header">
          <span class="metric-label">待补充归属</span>
          <div class="metric-dot" :class="incompleteCount > 0 ? 'dot-amber' : 'dot-green'"></div>
        </div>
        <div class="metric-value">{{ incompleteCount }}</div>
        <div class="metric-footer">
          <a v-if="incompleteCount > 0" class="metric-link amber" @click="$router.push('/customer/snapshot')">
            前往补充
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M6 3L11 8L6 13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </a>
          <span v-else class="metric-ok">ALL COMPLETE</span>
        </div>
      </div>

      <div class="metric-card">
        <div class="metric-header">
          <span class="metric-label">最近批次</span>
          <div class="metric-dot dot-blue"></div>
        </div>
        <div class="metric-value" v-if="latestBatch">{{ latestBatch.batch_name }}</div>
        <div class="metric-value muted" v-else>&mdash;</div>
        <div class="metric-footer">
          <el-tag v-if="latestBatch" :type="statusType(latestBatch.status)" size="small" effect="plain">
            {{ statusLabel(latestBatch.status) }}
          </el-tag>
          <span v-else class="metric-sub">暂无批次</span>
        </div>
      </div>

      <div class="metric-card">
        <div class="metric-header">
          <span class="metric-label">员工总数</span>
          <div class="metric-dot dot-teal"></div>
        </div>
        <div class="metric-value">{{ employeeCount }}</div>
        <div class="metric-footer">
          <a class="metric-link teal" @click="$router.push('/employee/attribute')">
            管理属性
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M6 3L11 8L6 13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </a>
        </div>
      </div>
    </div>

    <!-- Quick actions -->
    <div class="section-header">
      <h3>快捷操作</h3>
      <span class="section-line"></span>
    </div>
    <div class="actions-grid">
      <div v-for="item in shortcuts" :key="item.path" class="action-card" @click="$router.push(item.path)">
        <div class="action-icon" :style="{ background: item.bg }">
          <el-icon :size="18"><component :is="item.icon" /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">{{ item.label }}</div>
          <div class="action-desc">{{ item.desc }}</div>
        </div>
        <svg class="action-arrow" width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M6 3L11 8L6 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, markRaw } from 'vue'
import { getSnapshotList } from '@/api/customer'
import { getBatchList } from '@/api/commission'
import { getEmployeeList } from '@/api/employee'
import { UserFilled, Connection, Refresh, List } from '@element-plus/icons-vue'

const incompleteCount = ref(0)
const latestBatch = ref(null)
const employeeCount = ref(0)

const shortcuts = [
  { label: '员工属性管理', desc: '设置开发/分配属性', path: '/employee/attribute', icon: markRaw(UserFilled), bg: 'linear-gradient(135deg, #D4941C, #E5A820)' },
  { label: '主管关系管理', desc: '维护业务主管关系', path: '/supervisor/relation', icon: markRaw(Connection), bg: 'linear-gradient(135deg, #1A1816, #2E2A26)' },
  { label: '回款同步', desc: '拉取业务系统数据', path: '/payment/sync', icon: markRaw(Refresh), bg: 'linear-gradient(135deg, #D4941C, #BB8218)' },
  { label: '提成批次', desc: '计算与确认提成', path: '/commission/batch', icon: markRaw(List), bg: 'linear-gradient(135deg, #1A1816, #2E2A26)' },
]

function statusType(s) {
  return { draft: 'info', calculated: '', confirmed: 'success', voided: 'danger' }[s] || 'info'
}
function statusLabel(s) {
  return { draft: '草稿', calculated: '已计算', confirmed: '已确认', voided: '已作废' }[s] || s
}

onMounted(async () => {
  try {
    const snapRes = await getSnapshotList({ is_complete: 'false', page: 1, page_size: 1 })
    incompleteCount.value = snapRes.data?.total || 0
  } catch { /* ignore */ }

  try {
    const batchRes = await getBatchList({ page: 1, page_size: 1 })
    const items = batchRes.data?.items || []
    if (items.length) latestBatch.value = items[0]
  } catch { /* ignore */ }

  try {
    const empRes = await getEmployeeList({ keyword: '', page: 1, page_size: 1 })
    employeeCount.value = empRes.data?.total || 0
  } catch { /* ignore */ }
})
</script>

<style scoped>
/* ===== Hero ===== */
.hero {
  background: linear-gradient(135deg, #141210 0%, #1E1B18 50%, #141210 100%);
  border-radius: 16px;
  padding: 36px 40px;
  margin-bottom: 24px;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 120px;
}
.hero-content { position: relative; z-index: 1; }
.hero-tag {
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.15em;
  color: var(--color-gold);
  margin-bottom: 8px;
}
.hero-title {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 800;
  color: #F5F2EE;
  margin: 0 0 6px;
  letter-spacing: -0.01em;
}
.hero-desc {
  font-family: var(--font-display);
  font-size: 13px;
  color: #6B6560;
  margin: 0;
  letter-spacing: 0.04em;
}

/* Geometric decorations */
.hero-visual {
  position: absolute;
  right: 40px;
  top: 50%;
  transform: translateY(-50%);
  width: 200px;
  height: 200px;
}
.hex {
  position: absolute;
  border: 1px solid rgba(245,203,92,0.12);
  border-radius: 4px;
  transform: rotate(45deg);
}
.hex-1 { width: 80px; height: 80px; right: 20px; top: 10px; }
.hex-2 { width: 50px; height: 50px; right: 80px; top: 60px; border-color: rgba(245,203,92,0.08); }
.hex-3 { width: 30px; height: 30px; right: 10px; top: 90px; background: rgba(245,203,92,0.05); }
.hex-ring {
  width: 120px;
  height: 120px;
  right: -10px;
  top: -10px;
  border-color: rgba(245,203,92,0.06);
  border-width: 2px;
}

/* ===== Metrics ===== */
.metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 32px;
}
.metric-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--card-radius);
  padding: 20px 22px;
  box-shadow: var(--card-shadow);
  transition: all 0.25s ease;
}
.metric-card:hover {
  box-shadow: var(--card-shadow-hover);
  transform: translateY(-2px);
}
.metric-alert {
  border-left: 3px solid var(--color-gold);
}
.metric-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.metric-label {
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.03em;
  text-transform: uppercase;
}
.metric-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.dot-amber { background: var(--color-gold); box-shadow: 0 0 6px rgba(245,203,92,0.4); }
.dot-green { background: #2D9F6F; box-shadow: 0 0 6px rgba(45,159,111,0.4); }
.dot-blue  { background: var(--color-primary); box-shadow: 0 0 6px rgba(212,148,28,0.4); }
.dot-teal  { background: #1A1816; box-shadow: 0 0 6px rgba(26,24,22,0.3); }
.metric-value {
  font-family: var(--font-display);
  font-size: 30px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.1;
  margin-bottom: 10px;
}
.metric-value.muted {
  color: #cbd5e1;
}
.metric-footer {
  min-height: 22px;
}
.metric-link {
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: opacity 0.2s;
}
.metric-link:hover { opacity: 0.7; }
.metric-link.amber { color: var(--color-primary); }
.metric-link.teal  { color: var(--color-primary); }
.metric-ok {
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: #2D9F6F;
}
.metric-sub {
  font-size: 12px;
  color: var(--text-muted);
}

/* ===== Section header ===== */
.section-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.section-header h3 {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
  white-space: nowrap;
}
.section-line {
  flex: 1;
  height: 1px;
  background: var(--border-color);
}

/* ===== Action cards ===== */
.actions-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
.action-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--card-radius);
  padding: 16px 18px;
  display: flex;
  align-items: center;
  gap: 14px;
  cursor: pointer;
  transition: all 0.25s ease;
  box-shadow: var(--card-shadow);
}
.action-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--card-shadow-hover);
  transform: translateY(-1px);
}.action-card:hover .action-arrow {
  opacity: 1;
  transform: translateX(2px);
}
.action-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}
.action-info { flex: 1; min-width: 0; }
.action-name {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.action-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 1px;
}
.action-arrow {
  color: var(--text-muted);
  opacity: 0;
  transition: all 0.2s ease;
  flex-shrink: 0;
}
</style>
