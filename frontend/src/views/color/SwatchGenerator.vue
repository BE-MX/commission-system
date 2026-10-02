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
        <ListPageStatus :paged="false" :error="colorResource.errorMessage.value" :loading="colorResource.loading.value" :has-data="colorResource.hasData.value" @retry="loadColorOptions"><el-empty v-if="!colorOptions.length" description="暂无可选色号，可手动输入 HEX" :image-size="96" /></ListPageStatus>
        <el-select-v2
          v-model="selectedColorId"
          :options="colorOptions"
          :loading="colorResource.loading.value"
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
        <el-form label-position="top">
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
              <StatusBadge :type="currentTask.pass_check ? 'success' : 'warning'">
                ΔE = {{ currentTask.delta_e }} {{ currentTask.pass_check ? '✅ 通过' : '⚠️ 偏差' }}
              </StatusBadge>
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
    <div ref="historyPanelRef" class="history-section table-card">
      <div class="action-bar">
        <h3>历史生成记录</h3>
        <TableTools v-model:visible-keys="historyVisibleKeys" v-model:density="historyDensity" :columns="historyColumnDefs" :fullscreen="historyIsFullscreen" @refresh="loadHistory" @fullscreen="toggleHistoryFullscreen" />
      </div>
      <ListPageStatus v-if="historyState.hasData.value" :error="historyState.errorMessage.value" :loading="historyLoading" :has-data="true" :data-page="historyState.dataPage.value" @retry="loadHistory" />
      <el-table :data="historyList" v-loading="historyLoading" @sort-change="handleHistorySort" border class="list-table" :class="historyDensityClass" :max-height="historyIsFullscreen ? undefined : 640">
        <el-table-column v-if="historyVisibleKeys.includes('id')" prop="id" label="ID" min-width="60" />
        <el-table-column v-if="historyVisibleKeys.includes('color')" label="色号" min-width="100">
          <template #default="{ row }">
            <span v-if="row.palette_id">#{{ row.palette_id }}</span>
            <span v-else-if="row.blend_id">混#{{ row.blend_id }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="historyVisibleKeys.includes('target')" prop="target_hex" label="目标色" min-width="100" />
        <el-table-column v-if="historyVisibleKeys.includes('model')" prop="model_used" label="模型" min-width="120" />
        <el-table-column v-if="historyVisibleKeys.includes('delta')" label="ΔE" min-width="100">
          <template #default="{ row }">
            <StatusBadge v-if="row.delta_e !== null" :type="row.pass_check ? 'success' : 'warning'" size="small">
              {{ row.delta_e }}
            </StatusBadge>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="historyVisibleKeys.includes('status')" prop="status" label="状态" min-width="110">
          <template #default="{ row }">
            <StatusBadge :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="historyVisibleKeys.includes('created')" prop="created_at" label="创建时间" min-width="160" sortable="custom" />
        <template #empty><ListPageStatus :error="historyState.errorMessage.value" :loading="historyLoading" :has-data="false" @retry="loadHistory"><el-empty description="暂无数据" /></ListPageStatus></template>
      </el-table>
      <el-pagination
        v-if="historyTotal > 0"
        v-model:current-page="historyPage"
        v-model:page-size="historyPageSize"
        :total="historyTotal"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @current-change="historyState.handlePageChange"
        @size-change="handleHistorySizeChange"
      />
    </div>
  </div>
</template>

<script setup>import { msgWarning, msgSuccessText, msgError } from '@/utils/feedback'
import { onMounted, ref } from 'vue'

import { Download, MagicStick, Picture } from '@element-plus/icons-vue'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useListPage } from '@/composables/useListPage'
import { useTableSort } from '@/composables/useTableSort'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import { generateSwatch, getAllColorsForSelection, getSwatches, getSwatchStatus } from '@/api/color'

const colorResource = useAsyncResource(async (_, { signal }) =>
  (await getAllColorsForSelection({ signal, suppressToast: true })).map(p => ({ value: p.id, label: `${p.industry_code} ${p.display_name}` })), { initialData: [] })
const colorOptions = colorResource.data
const selectedColorId = ref(null)
const manualHex = ref('')
const style = ref('swatch_card')
const background = ref('white')
const generating = ref(false)
const orderSort = useTableSort()
const currentTask = ref(null)

const historyState = useListPage(async (params, { signal }) => (await getSwatches(params, { signal, suppressToast: true })).data, { searchForm: { sort_field: '', sort_order: '' } })
const { list: historyList, loading: historyLoading, page: historyPage, pageSize: historyPageSize, total: historyTotal, fetchList: loadHistory, handleSizeChange: handleHistorySizeChange } = historyState
const historyColumnDefs = [
  { key: 'id', label: 'ID' }, { key: 'color', label: '色号' },
  { key: 'target', label: '目标色' }, { key: 'model', label: '模型' },
  { key: 'delta', label: 'ΔE' }, { key: 'status', label: '状态' },
  { key: 'created', label: '创建时间' },
]
const {
  density: historyDensity, densityClass: historyDensityClass,
  visibleKeys: historyVisibleKeys, panelRef: historyPanelRef,
  isFullscreen: historyIsFullscreen, toggleFullscreen: toggleHistoryFullscreen,
} = useTableView('swatch-history', historyColumnDefs)

function handleHistorySort(event) {
  orderSort.onSortChange(event)
  return historyState.handleSortChange({ sort_field: orderSort.sortField.value, sort_order: orderSort.sortOrder.value })
}



onMounted(() => {
  loadColorOptions()
})

function loadColorOptions() { return colorResource.load() }



async function generate() {
  if (!selectedColorId.value && !manualHex.value) {
    msgWarning('请选择色号或输入 HEX')
    return
  }

  generating.value = true
  try {
    const data = { style: style.value, background: background.value }
    if (selectedColorId.value) {
      data.color_id = selectedColorId.value
    }
    const res = await generateSwatch(data)
    if (res.code === 201) {
      msgSuccessText('生成任务已创建')
      // 轮询状态
      pollStatus(res.data.task_id)
    }
  } catch (e) {
    msgError(e.response?.data?.message || '创建失败', e)
  } finally {
    generating.value = false
  }
}

async function pollStatus(taskId) {
  const interval = setInterval(async () => {
    try {
      const res = await getSwatchStatus(taskId)
      if (res.code === 200) {
        currentTask.value = res.data
        if (['completed', 'failed', 'rejected'].includes(currentTask.value.status)) {
          clearInterval(interval)
          historyState.refreshCreate()
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
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}
.history-section .action-bar h3 { margin: 0; }

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.history-section :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

@media (max-width: 768px) {
  .generator-layout { flex-direction: column; }
  .selector-panel, .preview-panel { width: 100%; min-width: 0; box-sizing: border-box; }
}
</style>
