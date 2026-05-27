<template>
  <div class="ai-manager-page">
    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="12" :sm="6" v-for="s in stats" :key="s.label">
        <div class="stat-card">
          <div class="stat-main">
            <div>
              <p class="stat-label">{{ s.label }}</p>
              <p class="stat-value" :style="{ color: s.color }">{{ s.value }}</p>
              <p class="stat-sub">{{ s.sub }}</p>
            </div>
            <div class="stat-icon-wrap" :style="{ background: s.bg }">
              <el-icon :size="20" :color="s.color"><component :is="s.icon" /></el-icon>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- Tab 导航 -->
    <el-tabs v-model="activeTab" type="border-card" class="ai-tabs">
      <!-- Provider Tab -->
      <el-tab-pane label="提供商管理" name="providers">
        <div class="tab-toolbar">
          <div class="toolbar-left">
            <el-input v-model="providerSearch" placeholder="搜索名称 / API Base" clearable style="width: 220px" />
            <el-select v-model="providerTypeFilter" placeholder="全部类型" clearable style="width: 140px">
              <el-option label="直连大模型" value="direct" />
              <el-option label="ACCIO WORK" value="accio_work" />
            </el-select>
            <el-select v-model="providerStatusFilter" placeholder="全部状态" clearable style="width: 120px">
              <el-option label="已启用" :value="true" />
              <el-option label="已禁用" :value="false" />
            </el-select>
          </div>
          <GlassButton variant="primary" left-icon="Plus" @click="openProviderDialog()">新增提供商</GlassButton>
        </div>

        <el-table :data="filteredProviders" border class="list-table" v-loading="providerLoading">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column label="名称" min-width="160">
            <template #default="{ row }">
              <div class="cell-with-icon">
                <el-icon :size="16" :color="row.provider_type === 'direct' ? '#2563eb' : '#059669'">
                  <component :is="row.provider_type === 'direct' ? 'Globe' : 'Monitor'" />
                </el-icon>
                <span class="cell-title">{{ row.name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-tag :type="row.provider_type === 'direct' ? 'primary' : 'success'" size="small" effect="plain">
                {{ row.provider_type === 'direct' ? '直连' : 'ACCIO' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="API Base / Key" min-width="220">
            <template #default="{ row }">
              <div class="mono-text">{{ row.api_base }}</div>
              <div class="key-row">
                <span class="mono-text key-mask">{{ showKeyMap[row.id] ? row.api_key : (row.api_key ? '****' : '-') }}</span>
                <el-button v-if="row.api_key" link size="small" @click="toggleKey(row.id)">
                  <el-icon><component :is="showKeyMap[row.id] ? 'Hide' : 'View'" /></el-icon>
                </el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="timeout_sec" label="超时" width="70" align="center" />
          <el-table-column prop="remark" label="备注" min-width="120" show-overflow-tooltip />
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-switch v-model="row.is_enabled" @change="toggleProvider(row)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" :loading="testingId === row.id" @click="handleTestProvider(row)">
                <el-icon><Lightning /></el-icon> 测试
              </el-button>
              <el-button link type="primary" size="small" @click="openProviderDialog(row)">
                <el-icon><Edit /></el-icon> 编辑
              </el-button>
              <el-button link type="danger" size="small" @click="handleDeleteProvider(row)">
                <el-icon><Delete /></el-icon> 删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Preset Tab -->
      <el-tab-pane label="预设管理" name="presets">
        <div class="tab-toolbar">
          <div class="toolbar-left">
            <el-input v-model="presetSearch" placeholder="搜索预设名称 / 描述" clearable style="width: 220px" />
            <el-select v-model="presetProviderFilter" placeholder="全部提供商" clearable style="width: 160px">
              <el-option v-for="p in providerOptions" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
          </div>
          <GlassButton variant="primary" left-icon="Plus" @click="openPresetDialog()">新增预设</GlassButton>
        </div>

        <el-table :data="filteredPresets" border class="list-table" v-loading="presetLoading">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column label="预设名称" min-width="180">
            <template #default="{ row }">
              <div>
                <span class="cell-title">{{ row.preset_name }}</span>
                <p class="cell-desc">{{ row.description }}</p>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="绑定提供商" min-width="140">
            <template #default="{ row }">
              <div class="cell-with-icon">
                <el-icon :size="14" color="#2563eb"><Position /></el-icon>
                <span>{{ row.provider_name || '-' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="model" label="模型" min-width="140">
            <template #default="{ row }">
              <span class="mono-text">{{ row.model || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.is_enabled ? 'success' : 'info'" size="small" effect="plain">
                {{ row.is_enabled ? '启用' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="240" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openTestPreset(row)">
                <el-icon><VideoPlay /></el-icon> 测试
              </el-button>
              <el-button link type="primary" size="small" @click="openPresetDialog(row)">
                <el-icon><Edit /></el-icon> 编辑
              </el-button>
              <el-button link type="primary" size="small" @click="handleCopyPreset(row)">
                <el-icon><DocumentCopy /></el-icon> 复制
              </el-button>
              <el-button link type="danger" size="small" @click="handleDeletePreset(row)">
                <el-icon><Delete /></el-icon> 删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Logs Tab -->
      <el-tab-pane label="调用日志" name="logs">
        <!-- 汇总卡片 -->
        <el-row :gutter="12" class="log-summary-row">
          <el-col :xs="8" :sm="4" v-for="s in logSummary" :key="s.label">
            <div class="log-summary-card">
              <div class="log-summary-header">
                <el-icon :size="14" :color="s.color"><component :is="s.icon" /></el-icon>
                <span class="log-summary-label">{{ s.label }}</span>
              </div>
              <p class="log-summary-value" :style="{ color: s.color }">{{ s.value }}</p>
            </div>
          </el-col>
        </el-row>

        <div class="tab-toolbar">
          <div class="toolbar-left">
            <el-input v-model="logSearch" placeholder="搜索预设 / 模块" clearable style="width: 180px" />
            <el-select v-model="logModuleFilter" placeholder="全部模块" clearable style="width: 130px">
              <el-option label="物流跟踪" value="logistics" />
              <el-option label="设计预约" value="design_booking" />
              <el-option label="提成管理" value="commission" />
            </el-select>
            <el-select v-model="logStatusFilter" placeholder="全部状态" clearable style="width: 120px">
              <el-option label="成功" value="success" />
              <el-option label="错误" value="error" />
              <el-option label="超时" value="timeout" />
              <el-option label="进行中" value="pending" />
            </el-select>
            <el-date-picker v-model="logDateRange" type="daterange" range-separator="~" start-placeholder="开始" end-placeholder="结束" value-format="YYYY-MM-DD" style="width: 240px" />
          </div>
        </div>

        <el-table :data="logsData" border class="list-table" v-loading="logsLoading" @expand-change="onLogExpand" @sort-change="logSort.onSortChange">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="log-detail">
                <el-descriptions :column="2" size="small" border>
                  <el-descriptions-item label="任务 ID">{{ row.task_id || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="调用用户">{{ row.caller_user_id || '系统' }}</el-descriptions-item>
                  <el-descriptions-item label="输入 Token">{{ row.tokens_prompt || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="输出 Token">{{ row.tokens_completion || '-' }}</el-descriptions-item>
                </el-descriptions>
                <div v-if="row.error_message" class="log-error-box">
                  <p class="log-error-code">{{ row.error_code }}</p>
                  <p class="log-error-msg">{{ row.error_message }}</p>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column label="模块 / Preset" min-width="160">
            <template #default="{ row }">
              <div>
                <span>{{ moduleLabel(row.caller_module) }}</span>
                <p class="cell-desc">{{ row.preset_name }}</p>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="80">
            <template #default="{ row }">
              <el-tag :type="row.provider_type === 'direct' ? 'primary' : 'success'" size="small" effect="plain">
                {{ row.provider_type === 'direct' ? '直连' : 'ACCIO' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="model" label="模型" min-width="120" sortable="custom">
            <template #default="{ row }"><span class="mono-text">{{ row.model || '-' }}</span></template>
          </el-table-column>
          <el-table-column prop="tokens_used" label="Token" width="80" align="right">
            <template #default="{ row }">
              <span class="mono-text">{{ row.tokens_used != null ? row.tokens_used.toLocaleString() : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="duration_ms" label="耗时" width="90" align="right">
            <template #default="{ row }">
              <span class="mono-text">{{ row.duration_ms != null ? formatDuration(row.duration_ms) : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small" effect="plain">
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="时间" width="150" sortable="custom" />
        </el-table>

        <el-pagination v-model:current-page="logPage" v-model:page-size="logPageSize" :page-sizes="[20, 50, 100]" :total="logTotal" layout="total, sizes, prev, pager, next" class="pagination" @change="fetchLogs" />
      </el-tab-pane>
    </el-tabs>

    <!-- Provider Dialog -->
    <el-dialog v-model="providerDialogVisible" :title="providerEditId ? '编辑提供商' : '新增提供商'" width="520px" destroy-on-close>
      <el-form ref="providerFormRef" :model="providerForm" :rules="providerRules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="providerForm.name" placeholder="如 OpenAI-生产" />
        </el-form-item>
        <el-form-item label="类型" prop="provider_type">
          <el-radio-group v-model="providerForm.provider_type" @change="onProviderTypeChange">
            <el-radio-button label="direct">直连大模型</el-radio-button>
            <el-radio-button label="accio_work">ACCIO WORK</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="API Base" prop="api_base">
          <el-input v-model="providerForm.api_base" :placeholder="providerForm.provider_type === 'accio_work' ? 'http://119.28.107.92:3100' : 'https://api.openai.com/v1'" />
        </el-form-item>
        <el-form-item label="API Key" v-if="providerForm.provider_type !== 'accio_work'">
          <el-input v-model="providerForm.api_key" type="password" show-password :placeholder="providerEditId ? '留空表示不修改' : 'sk-xxxxxxxxxxxxxxxx'" />
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="providerForm.timeout_sec" :min="1" :max="3600" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="providerForm.remark" type="textarea" :rows="2" placeholder="用途说明" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="providerDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="providerSaving" @click="submitProvider">保存</el-button>
      </template>
    </el-dialog>

    <!-- Preset Dialog -->
    <el-dialog v-model="presetDialogVisible" :title="presetEditId ? '编辑预设' : '新增预设'" width="560px" destroy-on-close>
      <el-form ref="presetFormRef" :model="presetForm" :rules="presetRules" label-width="110px">
        <el-form-item label="预设名称" prop="preset_name">
          <el-input v-model="presetForm.preset_name" placeholder="customer_analysis" />
          <div class="form-hint">只允许字母、数字、下划线</div>
        </el-form-item>
        <el-form-item label="绑定提供商" prop="provider_id">
          <el-select v-model="presetForm.provider_id" placeholder="选择提供商" style="width: 100%" @change="onPresetProviderChange">
            <el-option v-for="p in providerOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="presetForm.model" placeholder="gpt-4o" :disabled="isAccioProvider" />
        </el-form-item>
        <el-form-item label="System Prompt">
          <el-input v-model="presetForm.system_prompt" type="textarea" :rows="3" placeholder="输入系统提示词..." />
        </el-form-item>
        <el-form-item label="调用参数">
          <el-input v-model="presetForm.parameters" type="textarea" :rows="2" placeholder='{"temperature": 0.3}' class="mono-input" />
        </el-form-item>
        <el-form-item label="用途说明">
          <el-input v-model="presetForm.description" placeholder="描述此预设的用途" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="presetDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="presetSaving" @click="submitPreset">保存</el-button>
      </template>
    </el-dialog>

    <!-- Preset Test Dialog -->
    <el-dialog v-model="testDialogVisible" :title="`测试预设：${testPresetName}`" width="560px" destroy-on-close>
      <el-form>
        <el-form-item label="发送消息">
          <el-input v-model="testMessage" type="textarea" :rows="4" placeholder="输入测试消息..." />
        </el-form-item>
      </el-form>
      <div class="test-dialog-footer">
        <el-button type="primary" :loading="testing" @click="sendTest">
          <el-icon><VideoPlay /></el-icon> 发送测试
        </el-button>
      </div>
      <div v-if="testResult" class="test-result">
        <div class="test-result-header">
          <el-icon :size="16" color="#7c3aed"><ChatDotRound /></el-icon>
          <span>回复</span>
          <div class="test-result-meta">
            <span>Token: {{ testResult.tokens_used || 'N/A' }}</span>
            <span>{{ testResult.duration_ms }}ms</span>
          </div>
        </div>
        <pre class="test-result-content">{{ testResult.response }}</pre>
      </div>
    </el-dialog>

    <!-- Test Result Popover -->
    <el-dialog v-model="testResultVisible" title="连通性测试结果" width="360px" :show-close="true">
      <div class="test-popover-body">
        <div class="test-status-row">
          <div class="status-dot" :class="testResultData?.status === 'ok' ? 'ok' : 'error'" />
          <span class="test-status-text">{{ testResultData?.status === 'ok' ? '连接成功' : '连接失败' }}</span>
        </div>
        <p class="test-latency">延迟: {{ testResultData?.latency_ms }}ms</p>
        <p class="test-detail">{{ testResultData?.detail }}</p>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import {
  Cpu, Monitor, Position, Lightning, Edit, Delete,
  VideoPlay, DocumentCopy, ChatDotRound,
  View, Hide, SuccessFilled, CircleCloseFilled, WarningFilled, Loading,
  Histogram,
} from '@element-plus/icons-vue'

import { useAiManager } from './composables/useAiManager'

const {
  activeTab,
  // Provider
  providers, providerLoading, providerSearch, providerTypeFilter, providerStatusFilter,
  showKeyMap, testingId, testResultVisible, testResultData,
  providerDialogVisible, providerEditId, providerFormRef, providerSaving,
  providerForm, providerRules,
  openProviderDialog, onProviderTypeChange, submitProvider,
  toggleProvider, handleTestProvider, handleDeleteProvider, toggleKey,
  filteredProviders,
  // Preset
  presets, presetLoading, presetSearch, presetProviderFilter, providerOptions,
  presetDialogVisible, presetFormRef, presetSaving,
  presetForm, presetRules, isAccioProvider,
  testDialogVisible, testPresetName, testMessage, testing, testResult,
  openPresetDialog, onPresetProviderChange, submitPreset,
  handleDeletePreset, handleCopyPreset, openTestPreset, sendTest,
  filteredPresets,
  // Logs
  logsData, logsLoading, logModuleFilter, logStatusFilter, logDateRange,
  logPage, logPageSize, logTotal,
  onLogExpand, logSort,
  logSummary,
  // shared
  stats,
  moduleLabel, statusLabel, statusTagType, formatDuration,
} = useAiManager()
</script>

<style scoped>
.ai-manager-page {
  padding-bottom: 40px;
}

/* Stats */
.stats-row {
  margin-bottom: 20px;
}
.stat-card {
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 16px;
}
.stat-main {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.stat-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0 0 6px;
}
.stat-value {
  font-size: 24px;
  font-weight: 700;
  font-family: var(--font-mono);
  margin: 0;
  line-height: 1;
}
.stat-sub {
  font-size: 11px;
  color: var(--text-secondary);
  margin: 6px 0 0;
}
.stat-icon-wrap {
  padding: 8px;
  border-radius: 8px;
}

/* Tabs */
.ai-tabs {
  background: #fff;
  border-radius: 12px;
}
.ai-tabs :deep(.el-tabs__header) {
  border-radius: 12px 12px 0 0;
  margin: 0;
}
.ai-tabs :deep(.el-tabs__content) {
  padding: 20px;
}

/* Toolbar */
.tab-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  gap: 12px;
  flex-wrap: wrap;
}
.toolbar-left {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* Table */
.list-table {
  font-size: 13px;
}
.cell-with-icon {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cell-title {
  font-weight: 600;
  color: var(--text-primary);
}
.cell-desc {
  font-size: 11px;
  color: var(--text-secondary);
  margin: 2px 0 0;
}
.mono-text {
  font-family: var(--font-mono);
  font-size: 12px;
}
.key-row {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 2px;
}
.key-mask {
  color: var(--text-secondary);
}

/* Log Summary */
.log-summary-row {
  margin-bottom: 16px;
}
.log-summary-card {
  background: #fafbfe;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.log-summary-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.log-summary-label {
  font-size: 11px;
  color: var(--text-secondary);
}
.log-summary-value {
  font-size: 18px;
  font-weight: 700;
  font-family: var(--font-mono);
  margin: 0;
}

/* Log Detail */
.log-detail {
  padding: 12px 24px;
  background: #fafbfe;
}
.log-error-box {
  margin-top: 12px;
  padding: 10px 12px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
}
.log-error-code {
  font-size: 11px;
  font-family: var(--font-mono);
  color: #dc2626;
  margin: 0;
}
.log-error-msg {
  font-size: 12px;
  color: #b91c1c;
  margin: 4px 0 0;
}

/* Test Dialog */
.test-dialog-footer {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 16px;
}
.test-result {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: #fafbfe;
  padding: 12px;
}
.test-result-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
}
.test-result-meta {
  margin-left: auto;
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-secondary);
}
.test-result-content {
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  margin: 0;
  color: var(--text-primary);
}

/* Test Popover */
.test-popover-body {
  padding: 8px 4px;
}
.test-status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.status-dot.ok { background: #16a34a; }
.status-dot.error { background: #dc2626; }
.test-status-text {
  font-weight: 600;
  font-size: 15px;
}
.test-latency {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 4px 0;
}
.test-detail {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 4px 0 0;
}

/* Form hints */
.form-hint {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 4px;
}
.mono-input :deep(textarea) {
  font-family: var(--font-mono);
}

/* Pagination */
.pagination {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
