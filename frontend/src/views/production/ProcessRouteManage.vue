<template>
  <div class="process-route-manage">
    <div class="split-layout">
      <!-- 左侧：路线列表 -->
      <div class="route-list-panel">
        <div class="panel-header">
          <span class="panel-title">工序路线</span>
          <el-button type="primary" size="small" @click="openRouteForm()">
            <el-icon><Plus /></el-icon> 新建
          </el-button>
        </div>
        <div class="route-list" v-loading="routeLoading">
          <div
            v-for="r in routes" :key="r.id"
            class="route-item"
            :class="{ active: selectedRoute?.id === r.id }"
            @click="selectRoute(r)"
          >
            <div class="route-item-name">{{ r.name }}</div>
            <div class="route-item-meta">
              <span>{{ r.step_count }} 道工序</span>
              <span>· {{ r.product_count }} 个产品</span>
            </div>
            <div class="route-item-actions">
              <el-button link size="small" @click.stop="openRouteForm(r)">编辑</el-button>
              <el-button link size="small" type="danger" @click.stop="deleteRoute(r)">删除</el-button>
            </div>
          </div>
          <el-empty v-if="!routeLoading && routes.length === 0" description="暂无路线" />
        </div>
      </div>

      <!-- 右侧：步骤配置 -->
      <div class="route-detail-panel">
        <template v-if="selectedRoute">
          <div class="panel-header">
            <span class="panel-title">{{ selectedRoute.name }}</span>
            <div>
              <el-button size="small" @click="addStep">添加工序</el-button>
              <el-button type="primary" size="small" :loading="savingSteps" @click="saveSteps">保存顺序</el-button>
            </div>
          </div>
          <div class="step-list">
            <draggable v-model="editableSteps" item-key="process_id" handle=".drag-handle" animation="200">
              <template #item="{ element, index }">
                <div class="step-row">
                  <span class="drag-handle">≡</span>
                  <span class="step-order">{{ index + 1 }}</span>
                  <span class="step-name">{{ element.process_name }}</span>
                  <el-button link type="danger" size="small" @click="removeStep(index)">×</el-button>
                </div>
              </template>
            </draggable>
            <el-empty v-if="editableSteps.length === 0" description="请添加工序" />
          </div>
        </template>
        <el-empty v-else description="请从左侧选择一条路线" />
      </div>
    </div>

    <!-- 新建/编辑路线弹窗 -->
    <el-dialog v-model="routeFormVisible" :title="routeForm.id ? '编辑路线' : '新建路线'" width="480" destroy-on-close>
      <el-form ref="routeFormRef" :model="routeForm" :rules="routeFormRules" label-width="80px">
        <el-form-item label="路线名称" prop="name">
          <el-input v-model="routeForm.name" maxlength="100" />
        </el-form-item>
        <el-form-item label="路线描述">
          <el-input v-model="routeForm.description" type="textarea" :rows="3" maxlength="500" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="routeFormVisible = false">取消</el-button>
        <el-button type="primary" :loading="submittingRoute" @click="handleRouteSubmit">确认</el-button>
      </template>
    </el-dialog>

    <!-- 添加工序弹窗 -->
    <el-dialog v-model="addStepVisible" title="选择工序" width="400" destroy-on-close>
      <div v-if="availableProcesses.length === 0" style="color: #909399; text-align: center;">没有可添加的工序</div>
      <el-checkbox-group v-model="selectedNewSteps">
        <div v-for="p in availableProcesses" :key="p.id" style="padding: 4px 0;">
          <el-checkbox :value="p.id">{{ p.name }}</el-checkbox>
        </div>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="addStepVisible = false">取消</el-button>
        <el-button type="primary" :disabled="selectedNewSteps.length === 0" @click="confirmAddStep">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import draggable from 'vuedraggable'
import * as api from '@/api/production'

const routeLoading = ref(false)
const routes = ref([])
const selectedRoute = ref(null)
const editableSteps = ref([])
const savingSteps = ref(false)
const hasUnsavedChanges = ref(false)

// 路线表单
const routeFormVisible = ref(false)
const submittingRoute = ref(false)
const routeForm = ref({ name: '', description: '' })
const routeFormRef = ref(null)
const routeFormRules = {
  name: [{ required: true, message: '请输入路线名称', trigger: 'blur' }, { min: 2, max: 100, message: '2-100字', trigger: 'blur' }],
}

// 添加工序
const addStepVisible = ref(false)
const allProcesses = ref([])
const selectedNewSteps = ref([])

const availableProcesses = computed(() => {
  const existing = new Set(editableSteps.value.map(s => s.process_id))
  return allProcesses.value.filter(p => !existing.has(p.id))
})

watch(editableSteps, () => { hasUnsavedChanges.value = true }, { deep: true })

async function loadRoutes() {
  routeLoading.value = true
  try {
    const res = await api.getProcessRoutes({ page_size: 200 })
    routes.value = res.items || []
  } finally {
    routeLoading.value = false
  }
}

async function loadAllProcesses() {
  const res = await api.getActiveProcesses()
  allProcesses.value = res || []
}

function selectRoute(route) {
  if (hasUnsavedChanges.value) {
    ElMessageBox.confirm('当前步骤有未保存变更，是否放弃？', '提示', { type: 'warning' })
      .then(() => doSelectRoute(route))
      .catch(() => {})
  } else {
    doSelectRoute(route)
  }
}

async function doSelectRoute(route) {
  selectedRoute.value = route
  hasUnsavedChanges.value = false
  const res = await api.getRouteSteps(route.id)
  editableSteps.value = (res.steps || []).map(s => ({ process_id: s.process_id, process_name: s.process_name }))
}

function openRouteForm(row) {
  if (row) {
    routeForm.value = { id: row.id, name: row.name, description: row.description || '' }
  } else {
    routeForm.value = { name: '', description: '' }
  }
  routeFormVisible.value = true
}

async function handleRouteSubmit() {
  await routeFormRef.value.validate()
  submittingRoute.value = true
  try {
    if (routeForm.value.id) {
      await api.updateProcessRoute(routeForm.value.id, routeForm.value)
    } else {
      await api.createProcessRoute(routeForm.value)
    }
    ElMessage.success('已保存')
    routeFormVisible.value = false
    loadRoutes()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    submittingRoute.value = false
  }
}

async function deleteRoute(row) {
  try {
    await ElMessageBox.confirm('确认删除该路线？已绑定的产品不会被影响。', '提示', { type: 'warning' })
    await api.deleteProcessRoute(row.id)
    ElMessage.success('已删除')
    if (selectedRoute.value?.id === row.id) selectedRoute.value = null
    loadRoutes()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

function addStep() {
  selectedNewSteps.value = []
  addStepVisible.value = true
}

function confirmAddStep() {
  const newSteps = selectedNewSteps.value.map(pid => {
    const proc = allProcesses.value.find(p => p.id === pid)
    return { process_id: pid, process_name: proc?.name || '' }
  })
  editableSteps.value.push(...newSteps)
  addStepVisible.value = false
}

function removeStep(index) {
  editableSteps.value.splice(index, 1)
}

async function saveSteps() {
  if (!selectedRoute.value) return
  savingSteps.value = true
  try {
    const steps = editableSteps.value.map(s => ({ process_id: s.process_id }))
    await api.saveRouteSteps(selectedRoute.value.id, steps)
    ElMessage.success('步骤已保存')
    hasUnsavedChanges.value = false
    loadRoutes()
    doSelectRoute({ ...selectedRoute.value })
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    savingSteps.value = false
  }
}

onMounted(() => {
  loadRoutes()
  loadAllProcesses()
})
</script>

<style scoped>
.process-route-manage { padding: 20px; height: calc(100vh - 120px); }
.split-layout { display: flex; gap: 16px; height: 100%; }
.route-list-panel { width: 320px; flex-shrink: 0; border: 1px solid #ebeef5; border-radius: 4px; display: flex; flex-direction: column; }
.route-detail-panel { flex: 1; border: 1px solid #ebeef5; border-radius: 4px; display: flex; flex-direction: column; }
.panel-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid #ebeef5; }
.panel-title { font-weight: 600; font-size: 15px; }
.route-list { flex: 1; overflow-y: auto; padding: 8px; }
.route-item { padding: 10px 12px; border-radius: 4px; cursor: pointer; margin-bottom: 4px; transition: background 0.2s; position: relative; }
.route-item:hover { background: #f5f7fa; }
.route-item.active { background: #ecf5ff; }
.route-item-name { font-weight: 500; font-size: 14px; }
.route-item-meta { font-size: 12px; color: #909399; margin-top: 4px; }
.route-item-actions { position: absolute; right: 8px; top: 8px; display: none; }
.route-item:hover .route-item-actions { display: flex; gap: 4px; }
.step-list { flex: 1; overflow-y: auto; padding: 12px 16px; }
.step-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.drag-handle { cursor: grab; color: #c0c4cc; font-size: 18px; }
.step-order { width: 24px; height: 24px; background: #409eff; color: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; }
.step-name { flex: 1; font-weight: 500; }
</style>
