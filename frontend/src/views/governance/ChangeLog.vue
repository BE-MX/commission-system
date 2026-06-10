<template>
  <div class="change-log-page">
    <div class="page-header">
      <h2>数据治理 · 变更历史</h2>
    </div>

    <div class="filter-bar">
      <el-input v-model="filters.concept_id" placeholder="概念ID" clearable style="width: 200px" />
      <el-select v-model="filters.action" placeholder="操作类型" clearable style="width: 140px">
        <el-option v-for="a in actionOptions" :key="a.value" :label="a.label" :value="a.value" />
      </el-select>
      <el-button type="primary" :icon="Search" @click="loadLogs">搜索</el-button>
    </div>

    <el-timeline>
      <el-timeline-item v-for="log in logs" :key="log.id"
        :timestamp="formatDate(log.timestamp)" placement="top"
        :type="actionColor(log.action)">
        <el-card shadow="hover" class="log-card">
          <div class="log-header">
            <el-tag :type="actionTagType(log.action)" size="small">{{ actionLabels[log.action] }}</el-tag>
            <span v-if="log.concept_name_zh" class="log-concept">
              <router-link :to="`/governance/concepts/${log.concept_id}`">
                {{ log.concept_name_zh }}
              </router-link>
            </span>
            <span class="log-operator">操作人: {{ log.operator || '-' }}</span>
          </div>
          <div v-if="log.comment" class="log-comment">{{ log.comment }}</div>
          <div v-if="log.changed_fields?.length" class="log-changes">
            <div v-for="(c, i) in log.changed_fields" :key="i" class="change-item">
              <span class="change-field">{{ fieldLabels[c.field] || c.field }}</span>
              <span class="change-before">{{ formatVal(c.before) }}</span>
              <span class="change-arrow">→</span>
              <span class="change-after">{{ formatVal(c.after) }}</span>
            </div>
          </div>
          <div class="log-actions">
            <el-button v-if="isAdmin" type="primary" link size="small" @click="handleRollback(log)">
              回滚到此版本
            </el-button>
          </div>
        </el-card>
      </el-timeline-item>
    </el-timeline>

    <div class="pagination-wrap">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize"
        :total="total" layout="total, prev, pager, next" @change="loadLogs" />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { listChangeLogs, rollbackToVersion } from '@/api/governance'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.hasAnyPermission(['governance:admin']))

const actionLabels = {
  create: '创建', edit: '编辑', submit: '提交审批',
  approve: '审批通过', reject: '驳回', deprecate: '废弃', rollback: '回滚',
}
const actionOptions = Object.entries(actionLabels).map(([v, l]) => ({ value: v, label: l }))

const actionTagType = (a) => ({
  create: 'success', edit: '', submit: 'warning',
  approve: 'success', reject: 'danger', deprecate: 'info', rollback: 'warning',
}[a] || 'info')

const actionColor = (a) => ({
  create: 'success', approve: 'success', reject: 'danger', deprecate: 'info', rollback: 'warning',
}[a] || 'primary')

const fieldLabels = {
  status: '状态', name_zh: '中文名', name_en: '英文名',
  one_liner: '一句话定义', full_definition: '完整定义',
  boundary_includes: '包含范围', boundary_excludes: '排除范围',
}

const logs = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(30)

const filters = reactive({ concept_id: '', action: '' })

async function loadLogs() {
  try {
    const { data: res } = await listChangeLogs({
      ...filters,
      page: page.value,
      page_size: pageSize.value,
    })
    const payload = res.data ?? res
    logs.value = payload.items || []
    total.value = payload.total || 0
  } catch (e) {
    ElMessage.error('加载变更历史失败')
  }
}

async function handleRollback(log) {
  try {
    await ElMessageBox.confirm(`确认回滚到 ${formatDate(log.timestamp)} 的版本？`, '回滚确认')
    await rollbackToVersion(log.id)
    ElMessage.success('已回滚')
    loadLogs()
  } catch { /* cancel */ }
}

function formatDate(dt) {
  if (!dt) return '-'
  return new Date(dt).toLocaleString('zh-CN', { hour12: false })
}

function formatVal(v) {
  if (v === null || v === undefined) return '-'
  if (Array.isArray(v)) return v.join(', ')
  return String(v)
}

onMounted(() => loadLogs())
</script>

<style scoped>
.change-log-page {
  padding: 20px;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.filter-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.log-card {
  margin-bottom: 0;
}

.log-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.log-concept a {
  color: var(--el-color-primary);
  text-decoration: none;
  font-weight: 500;
}

.log-operator {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.log-comment {
  margin-top: 8px;
  color: var(--el-text-color-regular);
  font-size: 13px;
}

.log-changes {
  margin-top: 8px;
}

.change-item {
  font-size: 13px;
  margin: 4px 0;
}

.change-field {
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.change-before {
  color: var(--el-color-danger);
  text-decoration: line-through;
  margin: 0 4px;
}

.change-arrow {
  color: var(--el-text-color-secondary);
  margin: 0 4px;
}

.change-after {
  color: var(--el-color-success);
  font-weight: 500;
}

.log-actions {
  margin-top: 8px;
  text-align: right;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
