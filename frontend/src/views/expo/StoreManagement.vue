<template>
  <div class="stores-page">
    <!-- 金色极光背景（纯装饰；与线索台/工作台同源 styles/liquid-glass.css） -->
    <div class="stores-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-row :gutter="16" class="toolbar">
      <el-col :span="6">
        <el-input v-model="filters.keyword" placeholder="搜索门店名称 / 编码" clearable prefix-icon="Search" @keyup.enter="search" @clear="search" />
      </el-col>
      <el-col :span="4">
        <el-select v-model="filters.status" placeholder="状态" clearable style="width: 100%" @change="search">
          <el-option label="启用" :value="1" />
          <el-option label="停用" :value="0" />
        </el-select>
      </el-col>
      <el-col :span="14" class="toolbar-actions">
        <GlassButton variant="primary" left-icon="Search" @click="search">查询</GlassButton>
        <GlassButton v-permission="'expo_store:admin'" variant="primary" left-icon="Plus" @click="openEdit(null)">新增门店</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card stores-panel">
      <el-table :data="stores" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column prop="name" label="门店名称" min-width="140" show-overflow-tooltip />
        <el-table-column prop="code" label="编码" min-width="100" show-overflow-tooltip />
        <el-table-column label="状态" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 1 ? 'success' : 'info'">{{ row.status === 1 ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="剩余额度" width="110" align="right">
          <template #default="{ row }">
            <span :class="{ 'quota-zero': row.remaining === 0 }">{{ row.remaining }} 张</span>
          </template>
        </el-table-column>
        <el-table-column label="已用 / 累计" width="110" align="right">
          <template #default="{ row }">{{ row.used_quota }} / {{ row.total_quota }}</template>
        </el-table-column>
        <el-table-column label="联系人" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.contact_name || '-' }}<span v-if="row.contact_phone" class="muted">（{{ row.contact_phone }}）</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="150" show-overflow-tooltip />
        <el-table-column label="操作" min-width="220" fixed="right">
          <template #default="{ row }">
            <GlassButton v-any-permission="['expo_store:admin', 'expo_store:recharge']" variant="link" left-icon="Coin" @click="openQuota(row)">额度</GlassButton>
            <GlassButton v-permission="'expo_store:admin'" variant="link" left-icon="User" @click="openUsers(row)">人员</GlassButton>
            <GlassButton v-permission="'expo_store:admin'" variant="link" left-icon="Edit" @click="openEdit(row)">编辑</GlassButton>
            <GlassButton
              v-permission="'expo_store:admin'" variant="link" :link-tone="row.status === 1 ? 'danger' : 'success'"
              left-icon="SwitchButton" @click="handleToggle(row)"
            >{{ row.status === 1 ? '停用' : '启用' }}</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>

    <!-- 新增 / 编辑门店 -->
    <DetailDrawer v-model="editVisible" :title="editForm.id ? '编辑门店' : '新增门店'" :width="480">
      <el-form :model="editForm" label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="editForm.name" maxlength="128" placeholder="如：广州美博城店" />
        </el-form-item>
        <el-form-item label="编码" required>
          <el-input v-model="editForm.code" maxlength="64" placeholder="如：GZMB001" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="editForm.contact_name" maxlength="64" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="editForm.contact_phone" maxlength="32" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton @click="editVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submitEdit">保存</GlassButton>
      </template>
    </DetailDrawer>

    <!-- 人员绑定 -->
    <DetailDrawer v-model="usersVisible" :title="`绑定人员 · ${activeStore?.name || ''}`" :width="560">
      <el-form inline class="bind-form" @submit.prevent>
        <el-form-item label="系统账号">
          <el-select
            v-model="bindForm.user_id" filterable remote clearable :remote-method="searchUsers"
            :loading="userSearching" placeholder="输入姓名 / 账号搜索" style="width: 220px"
          >
            <el-option v-for="u in userOptions" :key="u.id" :label="`${u.real_name || u.username}（${u.username}）`" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="店长">
          <el-checkbox v-model="bindForm.is_primary" />
        </el-form-item>
        <el-form-item>
          <GlassButton variant="primary" :loading="binding" :disabled="!bindForm.user_id" @click="handleBind">绑定</GlassButton>
        </el-form-item>
      </el-form>
      <el-table :data="storeUsers" v-loading="usersLoading" size="small" border style="width: 100%">
        <el-table-column prop="username" label="账号" min-width="100" show-overflow-tooltip />
        <el-table-column prop="real_name" label="姓名" min-width="100" show-overflow-tooltip />
        <el-table-column label="角色" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_primary" size="small" type="warning">店长</el-tag>
            <span v-else class="muted">导购</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <GlassButton variant="link" link-tone="danger" left-icon="Close" @click="handleUnbind(row)">解绑</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </DetailDrawer>

    <!-- 额度充值 / 流水 -->
    <StoreQuotaDrawer
      v-model="quotaVisible" :store-id="activeStore?.id" :store-name="activeStore?.name"
      @changed="fetchStores"
    />
  </div>
</template>

<script setup>
/**
 * 门店管理页（2026-08-06）：门店 CRUD + 启停 + 人员绑定 + 额度入口。
 * 结构照线索台标杆（ExpoLeads.vue）：useListPage + DetailDrawer + feedback.js。
 * 运营（expo_store:admin）管门店与人员；财务（expo_store:recharge）只进额度抽屉。
 */
import { reactive, ref } from 'vue'
import {
  getStores, createStore, updateStore, toggleStore,
  getStoreUsers, bindStoreUser, unbindStoreUser,
} from '@/api/expo'
import { getUserList } from '@/api/userManagement'
import { useListPage } from '@/composables/useListPage'
import { msgSuccess, msgError, confirmDanger } from '@/utils/feedback'
import DetailDrawer from '@/components/DetailDrawer.vue'
import StoreQuotaDrawer from './StoreQuotaDrawer.vue'

const {
  loading, list: stores, total, page, pageSize, searchForm: filters,
  fetchList: fetchStores, handleSearch: search, handlePageChange, handleSizeChange,
} = useListPage(
  async ({ page, page_size, ...form }) => {
    const params = { offset: (page - 1) * page_size, limit: page_size }
    if (form.keyword) params.keyword = form.keyword
    if (form.status !== '' && form.status !== null && form.status !== undefined) params.status = form.status
    const res = await getStores(params)
    const data = res.data || {}
    // useListPage 期望 page 语义，后端门店列表是 offset 语义，这里回填对齐
    return { items: data.items || [], total: data.total || 0, page, page_size }
  },
  { searchForm: { keyword: '', status: '' } },
)

// ── 新增 / 编辑 ──
const editVisible = ref(false)
const saving = ref(false)
const editForm = reactive({ id: null, name: '', code: '', contact_name: '', contact_phone: '' })

function openEdit(row) {
  editForm.id = row?.id ?? null
  editForm.name = row?.name ?? ''
  editForm.code = row?.code ?? ''
  editForm.contact_name = row?.contact_name ?? ''
  editForm.contact_phone = row?.contact_phone ?? ''
  editVisible.value = true
}

async function submitEdit() {
  if (!editForm.name.trim() || !editForm.code.trim()) {
    msgError('名称与编码不能为空')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: editForm.name.trim(),
      code: editForm.code.trim(),
      contact_name: editForm.contact_name.trim() || null,
      contact_phone: editForm.contact_phone.trim() || null,
    }
    if (editForm.id) await updateStore(editForm.id, payload)
    else await createStore(payload)
    msgSuccess('保存')
    editVisible.value = false
    fetchStores()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function handleToggle(row) {
  const action = row.status === 1 ? '停用' : '启用'
  try {
    await confirmDanger(action, `门店 ${row.name}`, row.status === 1 ? '停用后该店账号将无法生成图片。' : '')
  } catch { return }
  try {
    await toggleStore(row.id)
    msgSuccess(action)
    fetchStores()
  } catch { /* 拦截器已提示 */ }
}

// ── 人员绑定 ──
const activeStore = ref(null)
const usersVisible = ref(false)
const usersLoading = ref(false)
const storeUsers = ref([])
const bindForm = reactive({ user_id: null, is_primary: false })
const userOptions = ref([])
const userSearching = ref(false)
const binding = ref(false)

function openUsers(row) {
  activeStore.value = row
  bindForm.user_id = null
  bindForm.is_primary = false
  userOptions.value = []
  usersVisible.value = true
  fetchStoreUsers()
}

async function fetchStoreUsers() {
  usersLoading.value = true
  try {
    const res = await getStoreUsers(activeStore.value.id)
    storeUsers.value = res.data || []
  } finally {
    usersLoading.value = false
  }
}

async function searchUsers(keyword) {
  userSearching.value = true
  try {
    const res = await getUserList({ keyword: keyword || '', page: 1, page_size: 20 })
    userOptions.value = res.data?.items || []
  } finally {
    userSearching.value = false
  }
}

async function handleBind() {
  binding.value = true
  try {
    await bindStoreUser(activeStore.value.id, {
      user_id: bindForm.user_id,
      is_primary: bindForm.is_primary,
    })
    msgSuccess('绑定')
    bindForm.user_id = null
    bindForm.is_primary = false
    fetchStoreUsers()
  } catch { /* 拦截器已提示 */ } finally {
    binding.value = false
  }
}

async function handleUnbind(row) {
  try {
    await confirmDanger('解绑', `账号 ${row.real_name || row.username}`, '解绑后该账号将不能再看本店线索与额度。')
  } catch { return }
  try {
    await unbindStoreUser(activeStore.value.id, row.user_id)
    msgSuccess('解绑')
    fetchStoreUsers()
  } catch { /* 拦截器已提示 */ }
}

// ── 额度抽屉 ──
const quotaVisible = ref(false)

function openQuota(row) {
  activeStore.value = row
  quotaVisible.value = true
}
</script>

<style scoped>
.stores-page { position: relative; }
.stores-aurora { inset: -24px -28px; }
.stores-page .toolbar,
.stores-page .stores-panel { position: relative; z-index: 1; }

.stores-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}
.stores-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}
.stores-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.stores-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.stores-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }

.toolbar { margin-bottom: 16px; }
.toolbar-actions { display: flex; gap: 10px; }
.pager { margin-top: 16px; justify-content: flex-end; }
.muted { color: var(--text-muted); font-size: 12px; }
.quota-zero { color: var(--color-danger-text, #c0392b); font-weight: 700; }
.bind-form { margin-bottom: 12px; }
</style>
