<template>
  <div ref="panelRef" class="table-card">
    <div class="action-bar">
      <GlassButton
        v-permission="'inventory:admin'"
        variant="primary"
        left-icon="Plus"
        @click="form = { code: '', name: '' }; open = true"
      >
        新增仓库
      </GlassButton>
      <TableTools
        v-model:visible-keys="visibleKeys"
        v-model:density="density"
        :columns="columns"
        :fullscreen="isFullscreen"
        :loading="resource.loading.value"
        @refresh="resource.load()"
        @fullscreen="toggleFullscreen"
      />
    </div>
    <ListPageStatus
      :error="resource.errorMessage.value"
      :loading="resource.loading.value"
      :has-data="resource.hasData.value"
      @retry="resource.load()"
    />
    <el-table
      :data="resource.data.value"
      v-loading="resource.loading.value"
      border
      class="list-table"
      :class="densityClass"
     v-sticky-scrollbar>
      <el-table-column v-if="visibleKeys.includes('code')" prop="code" label="仓库编码" min-width="160" />
      <el-table-column v-if="visibleKeys.includes('name')" prop="name" label="仓库名称" min-width="180" />
      <el-table-column v-if="visibleKeys.includes('active')" label="状态" min-width="100">
        <template #default="{ row }">
          <StatusBadge :type="row.active ? 'success' : 'info'">{{ row.active ? '启用' : '停用' }}</StatusBadge>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty v-if="!resource.error.value" description="暂无仓库" :image-size="96" />
      </template>
    </el-table>
    <el-dialog
      v-model="open"
      title="新增仓库"
      width="480px"
      :close-on-click-modal="!saving"
      :close-on-press-escape="!saving"
      :show-close="!saving"
    >
      <el-form ref="formRef" :model="form" label-position="top" :disabled="saving">
        <el-form-item
          label="仓库编码"
          prop="code"
          :rules="[{ required: true, whitespace: true, message: '请输入仓库编码' }]"
        >
          <el-input v-model="form.code" maxlength="64" />
        </el-form-item>
        <el-form-item
          label="仓库名称"
          prop="name"
          :rules="[{ required: true, whitespace: true, message: '请输入仓库名称' }]"
        >
          <el-input v-model="form.name" maxlength="128" />
        </el-form-item>
      </el-form>
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
import { onMounted, ref } from 'vue'
import { getWarehouses, createWarehouse } from '@/api/inventory'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import { msgSuccess, msgError } from '@/utils/feedback'
const resource = useAsyncResource(async (_, { signal }) => (await getWarehouses({ signal, suppressToast: true })).data, { initialData: [] })
const columns = [{ key: 'code', label: '仓库编码' }, { key: 'name', label: '仓库名称' }, { key: 'active', label: '状态' }]
const { panelRef, visibleKeys, density, densityClass, isFullscreen, toggleFullscreen } = useTableView('inventory-warehouses', columns)
const open = ref(false), saving = ref(false), formRef = ref(), form = ref({ code: '', name: '' })
async function save() { if (saving.value) return; saving.value = true; if (!await formRef.value.validate().catch(() => false)) { saving.value = false; return } try { await createWarehouse(form.value); msgSuccess('新增仓库'); open.value = false; await resource.load() } catch (error) { msgError('新增仓库失败', error) } finally { saving.value = false } }
onMounted(() => resource.load())
</script>
