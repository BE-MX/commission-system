<template>
  <div class="swatch-page">
    <!-- 金色极光背景（纯装饰；与工作台/发票页同源 styles/liquid-glass.css） -->
    <div class="swatch-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="generator-layout">
      <!-- 左侧：选择色号 -->
      <div class="selector-panel lg-card is-static">
        <h3>选择色号</h3>
        <el-select-v2
          v-model="selectedColorId"
          :options="colorOptions"
          placeholder="搜索色号..."
          filterable
          clearable
          style="width: 100%;"
        />
        <el-divider>或</el-divider>
        <el-input v-model="manualHex" placeholder="手动输入 HEX #6B5A52">
          <template #append>
            <el-color-picker v-model="manualHex" show-alpha="false" />
          </template>
        </el-input>

        <h3 style="margin-top: 24px;">生成设置</h3>
        <el-form label-width="80px">
          <el-form-item label="风格">
            <el-radio-group v-model="style">
              <el-radio-button label="swatch_card">色块卡片</el-radio-button>
              <el-radio-button label="hair_strand">发丝特写</el-radio-button>
              <el-radio-button label="model_preview">模特预览</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="背景">
            <el-radio-group v-model="background">
              <el-radio-button label="white">白色</el-radio-button>
              <el-radio-button label="grey">灰色</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-form>

        <GlassButton variant="primary" size="lg" full-width :loading="generating" :left-icon="MagicStick" style="margin-top: 16px;" @click="generate">
          生成色板图
        </GlassButton>
      </div>

      <!-- 右侧：预览区 -->
      <div class="preview-panel lg-card is-static">
        <div v-if="!currentTask" class="preview-placeholder">
          <el-icon :size="48" color="#c0c4cc"><Picture /></el-icon>
          <p>选择色号并点击生成</p>
        </div>
        <div v-else class="preview-content">
          <el-result
            v-if="currentTask.status === 'pending'"
            icon="info"
            title="任务已创建"
            :sub-title="`任务ID: ${currentTask.id}`"
          />
          <el-result
            v-else-if="currentTask.status === 'generating'"
            icon="info"
            title="生成中..."
          >
            <template #extra>
              <el-progress :percentage="50" indeterminate />
            </template>
          </el-result>
          <template v-else-if="currentTask.status === 'completed'">
            <img v-if="currentTask.image_url" :src="currentTask.image_url" class="preview-image" />
            <div class="verify-info">
              <span>目标色: {{ currentTask.target_hex }}</span>
              <span>实际色: {{ currentTask.actual_hex }}</span>
              <el-tag :type="currentTask.pass_check ? 'success' : 'warning'">
                ΔE = {{ currentTask.delta_e }} {{ currentTask.pass_check ? '✅ 通过' : '⚠️ 偏差' }}
              </el-tag>
            </div>
            <div class="preview-actions">
              <GlassButton variant="primary" :left-icon="Download">下载</GlassButton>
              <GlassButton variant="secondary">入素材库</GlassButton>
            </div>
          </template>
          <el-result
            v-else-if="currentTask.status === 'failed'"
            icon="error"
            title="生成失败"
          />
        </div>
      </div>
    </div>

    <!-- 历史记录 -->
    <div class="history-section">
      <h3>历史生成记录</h3>
      <el-table :data="historyList" size="small" @sort-change="orderSort.onSortChange" border class="list-table">
        <el-table-column prop="id" label="ID" min-width="60" />
        <el-table-column label="色号" min-width="100">
          <template #default="{ row }">
            <span v-if="row.palette_id">#{{ row.palette_id }}</span>
            <span v-else-if="row.blend_id">混#{{ row.blend_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="target_hex" label="目标色" min-width="100" />
        <el-table-column prop="model_used" label="模型" min-width="120" />
        <el-table-column label="ΔE" min-width="100">
          <template #default="{ row }">
            <el-tag v-if="row.delta_e !== null" :type="row.pass_check ? 'success' : 'warning'" size="small">
              {{ row.delta_e }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" min-width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" sortable="custom" />
      </el-table>
      <el-pagination
        v-if="historyTotal > 0"
        v-model:current-page="historyPage"
        v-model:page-size="historyPageSize"
        :total="historyTotal"
        layout="total, prev, pager, next"
      />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, MagicStick, Picture } from '@element-plus/icons-vue'
import { useTableSort } from '@/composables/useTableSort'
import { generateSwatch, getColors, getSwatches, getSwatchStatus } from '@/api/color'

const colorOptions = ref([])
const selectedColorId = ref(null)
const manualHex = ref('')
const style = ref('swatch_card')
const background = ref('white')
const generating = ref(false)
const orderSort = useTableSort()
const currentTask = ref(null)

const historyList = ref([])
const historyPage = ref(1)
const historyPageSize = ref(20)
const historyTotal = ref(0)

onMounted(() => {
  loadColorOptions()
  loadHistory()
})

async function loadColorOptions() {
  try {
    const res = await getColors({ page_size: 1000 })
    if (res.data?.code === 200) {
      colorOptions.value = (res.data.data.items || []).map(p => ({
        value: p.id,
        label: `${p.industry_code} ${p.display_name}`,
      }))
    }
  } catch { /* ignore */ }
}

async function loadHistory() {
  try {
    const res = await getSwatches({ page: historyPage.value, page_size: historyPageSize.value, ...orderSort.sortParams.value })
    if (res.data?.code === 200) {
      historyList.value = res.data.data.items || []
      historyTotal.value = res.data.data.total || 0
    }
  } catch { /* ignore */ }
}

async function generate() {
  if (!selectedColorId.value && !manualHex.value) {
    ElMessage.warning('请选择色号或输入 HEX')
    return
  }

  generating.value = true
  try {
    const data = { style: style.value, background: background.value }
    if (selectedColorId.value) {
      data.color_id = selectedColorId.value
    }
    const res = await generateSwatch(data)
    if (res.data?.code === 201) {
      ElMessage.success('生成任务已创建')
      // 轮询状态
      pollStatus(res.data.data.task_id)
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '创建失败')
  } finally {
    generating.value = false
  }
}

async function pollStatus(taskId) {
  const interval = setInterval(async () => {
    try {
      const res = await getSwatchStatus(taskId)
      if (res.data?.code === 200) {
        currentTask.value = res.data.data
        if (['completed', 'failed', 'rejected'].includes(currentTask.value.status)) {
          clearInterval(interval)
          loadHistory()
        }
      }
    } catch {
      clearInterval(interval)
    }
  }, 3000)

  // 5分钟后停止轮询
  setTimeout(() => clearInterval(interval), 300000)
}

function statusType(s) {
  const map = { pending: 'info', generating: 'warning', completed: 'success', failed: 'danger', rejected: 'danger' }
  return map[s] || 'info'
}

function statusLabel(s) {
  const map = { pending: '待生成', generating: '生成中', completed: '已完成', failed: '失败', rejected: '已拒绝' }
  return map[s] || s
}
</script>

<style scoped>
.swatch-page {
  padding: 20px;
  /* 极光层（.lg-aurora，与工作台同源）定位上下文 */
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 padding 环（同工作台/发票页） */
.swatch-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上。必须点名内容块，不能用 > :not(.lg-aurora) 通配 */
.swatch-page .generator-layout,
.swatch-page .history-section {
  position: relative;
  z-index: 1;
}

.generator-layout { display: flex; gap: 24px; margin-bottom: 32px; }
/* 玻璃质感由 .lg-card 提供（渐变磨砂 + 暖金彩色阴影），这里只留布局 */
.selector-panel { width: 360px; flex-shrink: 0; padding: 20px; }
.preview-panel { flex: 1; padding: 20px; min-height: 400px; display: flex; align-items: center; justify-content: center; }
.preview-placeholder { text-align: center; color: var(--el-text-color-placeholder); }
.preview-image { max-width: 100%; max-height: 360px; border-radius: 8px; }
.verify-info { margin-top: 16px; display: flex; gap: 16px; align-items: center; justify-content: center; }
.preview-actions { margin-top: 16px; display: flex; gap: 12px; justify-content: center; }

/* 历史记录表格面板：同款渐变玻璃 */
.history-section {
  padding: 20px;
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.history-section :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}
</style>
