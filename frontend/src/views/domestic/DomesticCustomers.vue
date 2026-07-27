<template>
  <div class="customers-page">
    <div class="customers-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-row :gutter="16" class="toolbar">
      <el-col :span="6">
        <el-input v-model="searchForm.keyword" placeholder="搜索店名 / 联系人 / 电话" clearable prefix-icon="Search" @keyup.enter="handleSearch" @clear="handleSearch" />
      </el-col>
      <el-col :span="4">
        <el-select v-model="searchForm.status" placeholder="状态" clearable style="width: 100%" @change="handleSearch">
          <el-option label="启用" :value="1" />
          <el-option label="停用" :value="0" />
        </el-select>
      </el-col>
      <el-col :span="8">
        <GlassButton variant="primary" left-icon="Search" @click="handleSearch">查询</GlassButton>
        <GlassButton v-permission="'domestic:write'" variant="ghost" left-icon="Plus" @click="openDialog()">新增客户</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card customers-panel">
      <el-table :data="list" v-loading="loading" border class="list-table" style="width: 100%">
        <el-table-column prop="shop_name" label="客户店名" min-width="160" show-overflow-tooltip />
        <el-table-column prop="contact" label="联系人" min-width="100" show-overflow-tooltip />
        <el-table-column prop="phone" label="电话" min-width="130" show-overflow-tooltip />
        <el-table-column prop="address" label="收货地址" min-width="200" show-overflow-tooltip />
        <el-table-column prop="order_count" label="订单数" min-width="90" />
        <el-table-column label="状态" min-width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status ? 'success' : 'info'" effect="plain">{{ row.status ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="170" fixed="right">
          <template #default="{ row }">
            <GlassButton v-permission="'domestic:write'" variant="link" left-icon="Edit" @click="openDialog(row)">编辑</GlassButton>
            <GlassButton v-permission="'domestic:write'" variant="link" :link-tone="row.status ? '' : 'success'" left-icon="SwitchButton" @click="toggleStatus(row)">
              {{ row.status ? '停用' : '启用' }}
            </GlassButton>
            <GlassButton v-permission="'domestic:admin'" variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>

    <el-dialog v-model="dialog.visible" :title="dialog.id ? '编辑客户' : '新增客户'" width="480px">
      <el-form :model="dialog" label-width="90px">
        <el-form-item label="客户店名" required>
          <el-input v-model="dialog.shop_name" placeholder="如：马姐假发" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="dialog.contact" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="dialog.phone" />
        </el-form-item>
        <el-form-item label="收货地址">
          <el-input v-model="dialog.address" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="dialog.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="dialog.visible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="save">确定</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/** 内贸客户管理。下单页可就地新建客户，这里做集中维护。 */
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createCustomer, deleteCustomer, listCustomers, updateCustomer } from '@/api/domestic'
import { useListPage } from '@/composables/useListPage'
import { confirmDanger, msgSuccess } from '@/utils/feedback'
import GlassButton from '@/components/GlassButton.vue'

const saving = ref(false)

const {
  loading, list, total, page, pageSize, searchForm,
  fetchList, handleSearch, handlePageChange, handleSizeChange,
} = useListPage(
  async ({ page, page_size, ...form }) => {
    const params = { page, page_size }
    if (form.keyword) params.keyword = form.keyword
    if (form.status !== '' && form.status !== null) params.status = form.status
    const res = await listCustomers(params)
    return res.data || {}
  },
  { searchForm: { keyword: '', status: '' } },
)

const dialog = reactive({
  visible: false, id: null, shop_name: '', contact: '', phone: '', address: '', remark: '',
})

function openDialog(row) {
  Object.assign(dialog, {
    visible: true,
    id: row?.id || null,
    shop_name: row?.shop_name || '',
    contact: row?.contact || '',
    phone: row?.phone || '',
    address: row?.address || '',
    remark: row?.remark || '',
  })
}

async function save() {
  if (!dialog.shop_name.trim()) return ElMessage.warning('请填写客户店名')
  const payload = {
    shop_name: dialog.shop_name.trim(),
    contact: dialog.contact || null,
    phone: dialog.phone || null,
    address: dialog.address || null,
    remark: dialog.remark || null,
  }
  saving.value = true
  try {
    if (dialog.id) await updateCustomer(dialog.id, payload)
    else await createCustomer(payload)
    dialog.visible = false
    msgSuccess('保存')
    await fetchList()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function toggleStatus(row) {
  await updateCustomer(row.id, { status: row.status ? 0 : 1 })
  msgSuccess(row.status ? '停用' : '启用')
  await fetchList()
}

async function handleDelete(row) {
  await confirmDanger('删除', `客户「${row.shop_name}」`)
  await deleteCustomer(row.id)
  msgSuccess('删除')
  await fetchList()
}
</script>

<style scoped>
.customers-page { position: relative; }
.customers-aurora { inset: -24px -28px; }
.customers-page .toolbar,
.customers-page .customers-panel { position: relative; z-index: 1; }

.toolbar { margin-bottom: 16px; }

.customers-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

.customers-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

.customers-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.customers-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }

.pager { margin: 12px; justify-content: flex-end; }
</style>
