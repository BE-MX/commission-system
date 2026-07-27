<template>
  <div class="products-page">
    <div class="products-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-tabs v-model="activeTab" class="products-tabs">
      <!-- 映射放第一个 Tab：先配好映射，产品才会自动带路线 -->
      <el-tab-pane label="工艺路线映射" name="mapping">
        <div class="panel">
          <el-alert
            type="info" show-icon :closable="false" class="tips"
            title="配好这里，下单就不用选工艺路线"
            description="每种「产品类型 + 工艺」配一条默认工艺路线。下单选完属性后系统自动按这张表配路线；新配的映射会自动补给此前漏配的同工艺产品。"
          />
          <div class="panel-actions">
            <GlassButton v-permission="'domestic:admin'" variant="primary" left-icon="Plus" @click="openMapping()">新增映射</GlassButton>
          </div>
          <el-table :data="craftRoutes" v-loading="mappingLoading" border class="list-table" style="width: 100%">
            <el-table-column prop="product_type_label" label="产品类型" min-width="100" />
            <el-table-column prop="craft" label="工艺" min-width="150" show-overflow-tooltip />
            <el-table-column prop="route_name" label="工艺路线" min-width="160" show-overflow-tooltip />
            <el-table-column prop="product_count" label="已沉淀产品" min-width="110" />
            <el-table-column prop="updated_at" label="更新时间" min-width="160" show-overflow-tooltip />
            <el-table-column label="操作" min-width="140" fixed="right">
              <template #default="{ row }">
                <GlassButton v-permission="'domestic:admin'" variant="link" left-icon="Edit" @click="openMapping(row)">改路线</GlassButton>
                <GlassButton v-permission="'domestic:admin'" variant="link" link-tone="danger" left-icon="Delete" @click="removeMapping(row)">删除</GlassButton>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="产品" name="products">
        <div class="panel">
          <el-alert
            type="info" show-icon :closable="false" class="tips"
            title="产品不用手工建"
            description="下单选完属性后系统自动沉淀产品；同一组属性永远只对应一个产品。这里只做查看和个别产品的路线改绑。"
          />
          <el-row :gutter="16" class="toolbar">
            <el-col :span="6">
              <el-input v-model="searchForm.keyword" placeholder="搜索产品名" clearable prefix-icon="Search" @keyup.enter="handleSearch" @clear="handleSearch" />
            </el-col>
            <el-col :span="4">
              <el-select v-model="searchForm.product_type" placeholder="产品类型" clearable style="width: 100%" @change="handleSearch">
                <el-option label="头套" value="cap" />
                <el-option label="发片" value="piece" />
              </el-select>
            </el-col>
            <el-col :span="4">
              <el-select v-model="searchForm.route_bound" placeholder="路线绑定" clearable style="width: 100%" @change="handleSearch">
                <el-option label="已绑路线" value="bound" />
                <el-option label="未绑路线" value="unbound" />
              </el-select>
            </el-col>
            <el-col :span="4">
              <GlassButton variant="primary" left-icon="Search" @click="handleSearch">查询</GlassButton>
            </el-col>
          </el-row>

          <el-table :data="list" v-loading="loading" border class="list-table" style="width: 100%">
            <el-table-column prop="name" label="产品" min-width="240" show-overflow-tooltip />
            <el-table-column prop="product_type_label" label="类型" min-width="80" />
            <el-table-column prop="craft" label="工艺" min-width="130" show-overflow-tooltip />
            <el-table-column label="工艺路线" min-width="150">
              <template #default="{ row }">
                <span v-if="row.route_name">{{ row.route_name }}</span>
                <el-tag v-else size="small" type="warning" effect="plain">未绑路线</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="use_count" label="下单次数" min-width="100" sortable />
            <el-table-column label="操作" min-width="110" fixed="right">
              <template #default="{ row }">
                <GlassButton v-permission="'domestic:admin'" variant="link" left-icon="Connection" @click="openRebind(row)">改绑路线</GlassButton>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="page" v-model:page-size="pageSize" :total="total"
            :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
            class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="mappingDialog.visible" :title="mappingDialog.isEdit ? '修改映射' : '新增映射'" width="460px">
      <el-form label-width="90px">
        <el-form-item label="产品类型">
          <el-radio-group v-model="mappingDialog.product_type" :disabled="mappingDialog.isEdit" @change="mappingDialog.craft = ''">
            <el-radio-button value="cap">头套</el-radio-button>
            <el-radio-button value="piece">发片</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="工艺">
          <el-select v-model="mappingDialog.craft" :disabled="mappingDialog.isEdit" placeholder="选择工艺" filterable style="width: 100%">
            <el-option v-for="v in craftOptions" :key="v" :label="v" :value="v" />
          </el-select>
        </el-form-item>
        <el-form-item label="工艺路线">
          <el-select v-model="mappingDialog.route_id" placeholder="选择路线" style="width: 100%">
            <el-option v-for="r in routes" :key="r.id" :label="`${r.name}（${r.step_count} 道：${r.steps.join(' → ')}）`" :value="r.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="mappingDialog.visible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="saveMapping">确定</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="rebindDialog.visible" title="改绑产品工艺路线" width="460px">
      <el-alert type="warning" show-icon :closable="false" class="tips"
        title="只对之后的新明细生效" description="在制明细用的是下单时快照的路线，改绑不会打乱正在做的货。" />
      <el-form label-width="90px">
        <el-form-item label="产品">
          <span>{{ rebindDialog.product?.name }}</span>
        </el-form-item>
        <el-form-item label="工艺路线">
          <el-select v-model="rebindDialog.route_id" placeholder="留空 = 解绑" clearable style="width: 100%">
            <el-option v-for="r in routes" :key="r.id" :label="`${r.name}（${r.step_count} 道）`" :value="r.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="rebindDialog.visible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="saveRebind">确定</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 内贸产品与工艺路线映射。映射是「下单人零操作」的支点：
 * 配好一次，之后所有同工艺的新产品都自动带路线。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  deleteCraftRoute, getOptions, getProcessRoutes, listCraftRoutes,
  listProducts, rebindProductRoute, upsertCraftRoute,
} from '@/api/domestic'
import { useListPage } from '@/composables/useListPage'
import { confirmDanger, msgSuccess } from '@/utils/feedback'
import GlassButton from '@/components/GlassButton.vue'

const activeTab = ref('mapping')
const saving = ref(false)
const routes = ref([])
const craftRoutes = ref([])
const mappingLoading = ref(false)
const options = ref({ attr_dicts: {}, values: {} })

const {
  loading, list, total, page, pageSize, searchForm,
  fetchList, handleSearch, handlePageChange, handleSizeChange,
} = useListPage(
  async ({ page, page_size, ...form }) => {
    const params = { page, page_size }
    for (const key of ['keyword', 'product_type', 'route_bound']) {
      if (form[key]) params[key] = form[key]
    }
    const res = await listProducts(params)
    return res.data || {}
  },
  { searchForm: { keyword: '', product_type: '', route_bound: '' } },
)

const mappingDialog = reactive({ visible: false, isEdit: false, id: null, product_type: 'cap', craft: '', route_id: null })
const rebindDialog = reactive({ visible: false, product: null, route_id: null })

const craftOptions = computed(() => {
  const dictType = options.value.attr_dicts?.[mappingDialog.product_type]?.craft
  return dictType ? (options.value.values?.[dictType] || []) : []
})

async function loadMappings() {
  mappingLoading.value = true
  try {
    const res = await listCraftRoutes()
    craftRoutes.value = res.data || []
  } finally {
    mappingLoading.value = false
  }
}

function openMapping(row) {
  Object.assign(mappingDialog, {
    visible: true,
    isEdit: Boolean(row),
    id: row?.id || null,
    product_type: row?.product_type || 'cap',
    craft: row?.craft || '',
    route_id: row?.route_id || null,
  })
}

async function saveMapping() {
  if (!mappingDialog.craft) return ElMessage.warning('请选择工艺')
  if (!mappingDialog.route_id) return ElMessage.warning('请选择工艺路线')
  saving.value = true
  try {
    const res = await upsertCraftRoute({
      product_type: mappingDialog.product_type,
      craft: mappingDialog.craft,
      route_id: mappingDialog.route_id,
    })
    mappingDialog.visible = false
    ElMessage.success(res.message || '已保存')
    await Promise.all([loadMappings(), fetchList()])
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function removeMapping(row) {
  await confirmDanger('删除', `「${row.craft}」的路线映射`, '删除后新产品不会再自动配这条路线。')
  await deleteCraftRoute(row.id)
  msgSuccess('删除')
  await loadMappings()
}

function openRebind(row) {
  Object.assign(rebindDialog, { visible: true, product: row, route_id: row.route_id })
}

async function saveRebind() {
  saving.value = true
  try {
    const res = await rebindProductRoute(rebindDialog.product.id, rebindDialog.route_id || null)
    rebindDialog.visible = false
    ElMessage.success(res.message || '已保存')
    await fetchList()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

onMounted(async () => {
  const [optRes, routeRes] = await Promise.all([getOptions(), getProcessRoutes()])
  options.value = optRes.data || options.value
  routes.value = routeRes.data || []
  await loadMappings()
})
</script>

<style scoped>
.products-page { position: relative; }
.products-aurora { inset: -24px -28px; }
.products-page .products-tabs { position: relative; z-index: 1; }

.panel {
  padding: 16px;
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

.panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

.panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }

.tips { margin-bottom: 12px; }
.toolbar { margin-bottom: 12px; }
.panel-actions { margin-bottom: 12px; }
.pager { margin-top: 12px; justify-content: flex-end; }
</style>
