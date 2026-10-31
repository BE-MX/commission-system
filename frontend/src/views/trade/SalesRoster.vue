<template>
  <div>
    <div class="page-header">
      <h2>本地业务员名册</h2>
      <p>基于方舟员工维护经营归属与目标。销售部门取自启用的 sales_department 系统字典。</p>
    </div>
    <div ref="panelRef" class="table-card">
      <FilterBar
        class="toolbar"
        @search="appliedKeyword = keyword"
        @reset="keyword = ''; appliedKeyword = ''"
      >
        <el-input v-model="keyword" clearable placeholder="筛选已加载员工姓名 / 英文名" class="filter-w-lg" />
      </FilterBar>
      <div class="action-bar">
        <GlassButton v-permission="'dict:read'" left-icon="Setting" @click="$router.push('/system/dicts')">
          维护销售部门字典
        </GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columns"
          :fullscreen="isFullscreen"
          :loading="resource.loading.value"
          @refresh="refresh"
          @fullscreen="toggleFullscreen"
        />
      </div>
      <ListPageStatus
        :error="departments.errorMessage.value"
        :has-data="departments.hasData.value"
        :paged="false"
        @retry="departments.load()"
      />
      <ListPageStatus
        :error="resource.errorMessage.value"
        :loading="resource.loading.value"
        :has-data="resource.hasData.value"
        :paged="false"
        @retry="resource.load()"
      />
      <el-table
        :data="filteredRows"
        v-loading="resource.loading.value"
        border
        class="list-table"
        :class="densityClass"
        :max-height="isFullscreen ? undefined : 640"
       v-sticky-scrollbar>
        <el-table-column
          v-for="c in columns.filter(c => visibleKeys.includes(c.key))"
          :key="c.key"
          :label="c.label"
          min-width="130"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            <StatusBadge v-if="c.key === 'active'" :type="row.active ? 'success' : 'info'">
              {{ !row.user_active ? '员工已停用' : !row.configured ? '未配置' : row.active ? '启用' : '停用' }}
            </StatusBadge>
            <span v-else-if="c.key === 'department_id'">{{ departmentName(row.department_id) }}</span>
            <span v-else-if="c.key === 'amount_target'">{{ formatRosterAmount(row.amount_target) }}</span>
            <span v-else>{{ row[c.key] ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="100" fixed="right" class-name="table-action-column">
          <template #default="{ row }">
            <GlassButton v-permission="'employee:write'" variant="link" left-icon="Edit" @click="edit(row)">
              编辑名册
            </GlassButton>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty v-if="!resource.error.value" description="已加载员工中没有匹配记录" :image-size="96" />
        </template>
      </el-table>
      <div class="pager">
        <span>
          已加载
          {{ resource.items.value.length }}
          位员工
          {{ resource.hasMore.value ? '，还有更多' : '，已全部加载' }}
        </span>
        <GlassButton
          v-if="resource.hasMore.value"
          left-icon="MoreFilled"
          :loading="resource.loading.value"
          @click="resource.load()"
        >
          加载更多员工
        </GlassButton>
      </div>
    </div>
    <el-dialog
      v-model="open"
      :title="`编辑名册 · ${selected?.name || ''}`"
      width="640px"
      :close-on-click-modal="!saving"
      :close-on-press-escape="!saving"
      :show-close="!saving"
    >
      <el-form ref="formRef" :model="form" label-position="top" :disabled="saving">
        <el-form-item label="英文名">
          <el-input v-model="form.english_name" maxlength="128" />
        </el-form-item>
        <el-form-item label="销售部门">
          <el-select v-model="form.department_id" clearable filterable placeholder="选择启用的销售部门">
            <el-option v-for="d in departments.data.value" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
          <p v-if="form.department_id && !departments.data.value.some(d => d.id === form.department_id)">
            原部门已停用，请重新选择或清空。
          </p>
        </el-form-item>
        <el-form-item label="团队（Team）">
          <el-input v-model="form.team" maxlength="100" />
        </el-form-item>
        <el-form-item label="营（Camp）">
          <el-input v-model="form.camp" maxlength="100" />
        </el-form-item>
        <el-form-item label="新客户目标">
          <el-input-number v-model="form.new_customer_target" :min="0" :max="2147483647" :precision="0" />
        </el-form-item>
        <el-form-item
          label="金额目标"
          prop="amount_target"
          :rules="[{ required: true, message: '请填写金额目标' }, { pattern: /^\d{1,14}(\.\d{1,2})?$/, message: '请输入非负金额，最多两位小数' }]"
        >
          <el-input v-model="form.amount_target" inputmode="decimal" maxlength="17" />
        </el-form-item>
        <el-form-item label="启用名册">
          <el-switch v-model="form.active" :disabled="!selected?.user_active" />
          <span v-if="!selected?.user_active">员工已停用，不能启用统计名册</span>
        </el-form-item>
      </el-form>
      <el-alert v-if="conflict" :title="conflict" type="error" :closable="false" show-icon />
      <p v-if="conflict">当前输入已保留。关闭弹窗并刷新名册，核对最新版本后重新编辑。</p>
      <template #footer>
        <div class="dialog-footer">
          <GlassButton :disabled="saving" @click="open = false">取消</GlassButton>
          <GlassButton variant="primary" :loading="saving" @click="save">保存</GlassButton>
        </div>
      </template>
    </el-dialog>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { getRoster, updateRoster, getDepartments } from '@/api/trade'
import { useCursorResource } from '@/composables/useCursorResource'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import { formatRosterAmount } from './rosterAmount'
import { msgSuccess, msgError, confirmDanger, isFeedbackCancelled } from '@/utils/feedback'
import { errorMessage } from '@/utils/errors'
const resource = useCursorResource(async (_, cursor, { signal }) => { const rows = (await getRoster({ after_id: cursor, limit: 50 }, { signal, suppressToast: true })).data; return { items: rows, nextCursor: rows.at(-1)?.ark_user_id ?? cursor, hasMore: rows.length === 50 } }, { initialCursor: 0, key: row => row.ark_user_id })
const departments = useAsyncResource(async (_, { signal }) => (await getDepartments({ signal, suppressToast: true })).data, { initialData: [] })
const keyword = ref(''), appliedKeyword = ref('')
const filteredRows = computed(() => resource.items.value.filter(r => `${r.name} ${r.english_name || ''}`.toLowerCase().includes(appliedKeyword.value.trim().toLowerCase())))
const columns = [{ key: 'name', label: '员工' }, { key: 'english_name', label: '英文名' }, { key: 'department_id', label: '销售部门' }, { key: 'team', label: '团队' }, { key: 'camp', label: '营' }, { key: 'new_customer_target', label: '新客目标' }, { key: 'amount_target', label: '金额目标' }, { key: 'active', label: '名册状态' }]
const { panelRef, visibleKeys, density, densityClass, isFullscreen, toggleFullscreen } = useTableView('trade-roster', columns)
const departmentName = id => id ? departments.data.value.find(d => d.id === id)?.name || '已停用部门' : '未设置'
const open = ref(false), saving = ref(false), selected = ref(null), form = ref({}), formRef = ref(), conflict = ref('')
function edit(row) { selected.value = row; conflict.value = ''; form.value = { expected_version: row.version, department_id: row.department_id, english_name: row.english_name || '', team: row.team, camp: row.camp, new_customer_target: row.new_customer_target, amount_target: row.amount_target, active: row.active }; open.value = true }
function refresh() { resource.clear(); return resource.load() }
async function save() {
  if (saving.value) return
  saving.value = true
  if (!await formRef.value.validate().catch(() => false)) { saving.value = false; return }
  if (form.value.department_id && !departments.data.value.some(d => d.id === form.value.department_id)) { saving.value = false; msgError('请选择启用的销售部门，或清空部门'); return }
  saving.value = true; conflict.value = ''
  try {
    if (selected.value.active && !form.value.active) await confirmDanger('停用名册', selected.value.name, '历史经营记录保留。')
    const response = await updateRoster(selected.value.ark_user_id, { ...form.value, department_id: form.value.department_id || null })
    const index = resource.data.value.items.findIndex(row => row.ark_user_id === selected.value.ark_user_id)
    if (index >= 0) resource.data.value.items[index] = response.data
    msgSuccess('保存名册'); open.value = false
  } catch (error) { if (!isFeedbackCancelled(error)) { conflict.value = errorMessage(error); msgError('保存名册失败', error) } }
  finally { saving.value = false }
}
onMounted(() => { resource.load(); departments.load() })
</script>
