<!--
  名片管家：业务员电子名片（leshine.work/card/<slug>/）的管理端。
  标记语言/样式规范照 system/DictManagement.vue；编排照 views/expo/ExpoLeads.vue
  （useListPage + utils/feedback + DetailDrawer + AppUpload）；逻辑在 composables/useCardButler.js。
-->
<template>
  <div class="page-container">
    <h2 class="page-title">名片管家</h2>

    <el-tabs v-model="activeTab">
      <!-- ── 客户档案 ─────────────────────────── -->
      <el-tab-pane label="客户档案" name="customers">
        <div ref="customerPanelRef" class="table-card">
          <div class="toolbar">
            <el-input v-model="customerPage.searchForm.keyword" placeholder="称呼 / 邮箱 / WhatsApp"
                      clearable class="filter-w-md" @keyup.enter="customerPage.handleSearch" />
            <el-select v-model="customerPage.searchForm.salesperson_id" clearable placeholder="业务员（全部）"
                       class="filter-w-sm" @change="customerPage.handleSearch">
              <el-option v-for="sp in salespersons" :key="sp.id" :label="sp.name" :value="sp.id" />
            </el-select>
            <GlassButton variant="primary" left-icon="Search" @click="customerPage.handleSearch">查询</GlassButton>
            <GlassButton left-icon="RefreshLeft" @click="customerPage.handleReset">重置</GlassButton>
          </div>
          <div class="action-bar">
            <GlassButton v-permission="'card:write'" variant="primary" left-icon="Plus" @click="openCustomerDialog(null)">新建客户</GlassButton>
            <TableTools
              v-model:visible-keys="customerVisibleKeys"
              v-model:density="customerDensity"
              :columns="customerColumnDefs"
              :fullscreen="customerIsFullscreen"
              @refresh="customerPage.handleSearch"
              @fullscreen="toggleCustomerFullscreen"
            />
          </div>
          <el-table :data="customerPage.list.value" v-loading="customerPage.loading.value" border class="list-table" :class="customerDensityClass" :max-height="customerIsFullscreen ? undefined : 640" style="width: 100%">
            <el-table-column v-if="customerVisibleKeys.includes('display-name')" prop="display_name" label="客户称呼" min-width="130" show-overflow-tooltip />
            <el-table-column v-if="customerVisibleKeys.includes('email')" label="口令（邮箱）" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ row.email_norm || '—' }}</template>
            </el-table-column>
            <el-table-column v-if="customerVisibleKeys.includes('whatsapp')" label="口令（WhatsApp）" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">{{ row.whatsapp_norm || '—' }}</template>
            </el-table-column>
            <el-table-column v-if="customerVisibleKeys.includes('expo-code')" prop="expo_code" label="届次" min-width="100" show-overflow-tooltip />
            <el-table-column v-if="customerVisibleKeys.includes('entries')" label="纪要" min-width="80">
              <template #default="{ row }">
                <el-tag effect="plain" :type="row.entry_count ? 'success' : 'info'">{{ row.entry_count }} 条</el-tag>
              </template>
            </el-table-column>
            <el-table-column v-if="customerVisibleKeys.includes('created-at')" prop="created_at" label="建档时间" min-width="140" />
            <el-table-column class-name="table-action-column" label="操作" min-width="220" fixed="right">
              <template #default="{ row }">
                <GlassButton v-permission="'card:write'" variant="link" left-icon="Notebook" @click="openEntries(row)">纪要</GlassButton>
                <GlassButton v-permission="'card:write'" variant="link" left-icon="Edit" @click="openCustomerDialog(row)">编辑</GlassButton>
                <GlassButton v-permission="'card:write'" variant="link" link-tone="danger" left-icon="Delete" @click="removeCustomer(row)">删除</GlassButton>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="customerPage.page.value"
            v-model:page-size="customerPage.pageSize.value"
            :total="customerPage.total.value"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            class="pager"
            @current-change="customerPage.handlePageChange"
            @size-change="customerPage.handleSizeChange"
          />
        </div>
      </el-tab-pane>

      <!-- ── 询盘 ─────────────────────────────── -->
      <el-tab-pane label="客户询盘" name="inquiries">
        <div ref="inquiryPanelRef" class="table-card">
          <div class="toolbar">
            <el-select v-model="inquiryPage.searchForm.status" clearable placeholder="状态（全部）"
                       class="filter-w-sm" @change="inquiryPage.handleSearch">
              <el-option label="未处理" value="new" />
              <el-option label="已处理" value="handled" />
            </el-select>
            <el-select v-model="inquiryPage.searchForm.salesperson_id" clearable placeholder="业务员（全部）"
                       class="filter-w-sm" @change="inquiryPage.handleSearch">
              <el-option v-for="sp in salespersons" :key="sp.id" :label="sp.name" :value="sp.id" />
            </el-select>
            <GlassButton variant="primary" left-icon="Search" @click="inquiryPage.handleSearch">查询</GlassButton>
            <GlassButton left-icon="RefreshLeft" @click="inquiryPage.handleReset">重置</GlassButton>
          </div>
          <div class="action-bar">
            <TableTools
              v-model:visible-keys="inquiryVisibleKeys"
              v-model:density="inquiryDensity"
              :columns="inquiryColumnDefs"
              :fullscreen="inquiryIsFullscreen"
              @refresh="inquiryPage.handleSearch"
              @fullscreen="toggleInquiryFullscreen"
            />
          </div>
          <el-table :data="inquiryPage.list.value" v-loading="inquiryPage.loading.value" border class="list-table" :class="inquiryDensityClass" :max-height="inquiryIsFullscreen ? undefined : 640" style="width: 100%">
            <el-table-column v-if="inquiryVisibleKeys.includes('salesperson')" prop="salesperson" label="业务员" min-width="100" />
            <el-table-column v-if="inquiryVisibleKeys.includes('contact')" prop="contact" label="客户联系方式" min-width="180" show-overflow-tooltip />
            <el-table-column v-if="inquiryVisibleKeys.includes('message')" prop="message" label="内容" min-width="320" show-overflow-tooltip />
            <el-table-column v-if="inquiryVisibleKeys.includes('customer')" label="建档客户" min-width="100">
              <template #default="{ row }">
                <el-tag v-if="row.customer_id" effect="plain" type="success">已命中</el-tag>
                <el-tag v-else effect="plain" type="info">未建档</el-tag>
              </template>
            </el-table-column>
            <el-table-column v-if="inquiryVisibleKeys.includes('created-at')" prop="created_at" label="提交时间" min-width="140" />
            <el-table-column v-if="inquiryVisibleKeys.includes('status')" label="状态" min-width="90">
              <template #default="{ row }">
                <el-tag effect="plain" :type="row.status === 'new' ? 'warning' : 'success'">
                  {{ row.status === 'new' ? '未处理' : '已处理' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column class-name="table-action-column" label="操作" min-width="110" fixed="right">
              <template #default="{ row }">
                <GlassButton v-permission="'card:write'" variant="link" left-icon="Check" @click="markHandled(row)">
                  {{ row.status === 'new' ? '标记已处理' : '标记未处理' }}
                </GlassButton>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="inquiryPage.page.value"
            v-model:page-size="inquiryPage.pageSize.value"
            :total="inquiryPage.total.value"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            class="pager"
            @current-change="inquiryPage.handlePageChange"
            @size-change="inquiryPage.handleSizeChange"
          />
        </div>
      </el-tab-pane>

      <!-- ── 业务员档案 ───────────────────────── -->
      <el-tab-pane label="业务员档案" name="salespersons">
        <div ref="salespersonPanelRef" class="table-card">
          <div class="action-bar">
            <TableTools v-model:visible-keys="salespersonVisibleKeys" v-model:density="salespersonDensity" :columns="salespersonColumnDefs" :fullscreen="salespersonIsFullscreen" @refresh="fetchSalespersons" @fullscreen="toggleSalespersonFullscreen" />
          </div>
          <el-table :data="salespersons" border class="list-table" :class="salespersonDensityClass" :max-height="salespersonIsFullscreen ? undefined : 640" style="width: 100%">
            <el-table-column v-if="salespersonVisibleKeys.includes('slug')" prop="slug" label="主页地址" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">leshine.work/card/{{ row.slug }}/</template>
            </el-table-column>
            <el-table-column v-if="salespersonVisibleKeys.includes('name')" prop="name" label="英文名" min-width="110" />
            <el-table-column v-if="salespersonVisibleKeys.includes('title')" prop="title" label="职位" min-width="130" show-overflow-tooltip />
            <el-table-column v-if="salespersonVisibleKeys.includes('email')" prop="email" label="邮箱" min-width="200" show-overflow-tooltip />
            <el-table-column v-if="salespersonVisibleKeys.includes('whatsapp')" label="WhatsApp" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">{{ row.whatsapp || '—' }}</template>
            </el-table-column>
            <el-table-column v-if="salespersonVisibleKeys.includes('status')" label="状态" min-width="80">
              <template #default="{ row }">
                <el-tag effect="plain" :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column class-name="table-action-column" label="操作" min-width="100" fixed="right">
              <template #default="{ row }">
                <GlassButton v-permission="'card:write'" variant="link" left-icon="Edit" @click="openSpDialog(row)">编辑</GlassButton>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <p class="tip-line">静态主页内容（介绍/FAQ/链接）改动需重跑 scripts/card_suite/build_pages.py 并上云；此处档案供口令与询盘归属。</p>
      </el-tab-pane>
    </el-tabs>

    <!-- 客户档案编辑弹窗 -->
    <el-dialog v-model="customerDialogVisible" :title="customerForm.id ? '编辑客户' : '新建客户'" width="520px">
      <el-form label-width="110px">
        <el-form-item v-if="!customerForm.id" label="归属业务员" required>
          <el-select v-model="customerForm.salesperson_id" style="width: 100%">
            <el-option v-for="sp in salespersons" :key="sp.id" :label="sp.name" :value="sp.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="客户称呼" required>
          <el-input v-model="customerForm.display_name" placeholder="解锁页问候语用，如 Maria" />
        </el-form-item>
        <el-form-item label="邮箱口令">
          <el-input v-model="customerForm.email" placeholder="客户邮箱（与 WhatsApp 至少一个）" />
        </el-form-item>
        <el-form-item label="WhatsApp 口令">
          <el-input v-model="customerForm.whatsapp" placeholder="客户 WhatsApp 号，存纯数字" />
        </el-form-item>
        <el-form-item label="届次">
          <el-input v-model="customerForm.expo_code" />
        </el-form-item>
        <el-form-item label="内部备注">
          <el-input v-model="customerForm.remark" type="textarea" :rows="2" placeholder="客户看不到" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="customerDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="customerSaving" @click="saveCustomer">保存</GlassButton>
      </template>
    </el-dialog>

    <!-- 业务员档案编辑弹窗 -->
    <el-dialog v-model="spDialogVisible" title="业务员档案" width="520px">
      <el-form label-width="100px">
        <el-form-item label="slug">
          <el-input v-model="spForm.slug" disabled />
          <div class="field-tip">已印在名片二维码里，不可修改</div>
        </el-form-item>
        <el-form-item label="英文名" required><el-input v-model="spForm.name" /></el-form-item>
        <el-form-item label="职位"><el-input v-model="spForm.title" /></el-form-item>
        <el-form-item label="邮箱" required><el-input v-model="spForm.email" /></el-form-item>
        <el-form-item label="WhatsApp"><el-input v-model="spForm.whatsapp" placeholder="到齐后补，主页按钮自动出现" /></el-form-item>
        <el-form-item label="介绍"><el-input v-model="spForm.intro" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="spForm.is_active" :active-value="1" :inactive-value="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="spDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="spSaving" @click="saveSalesperson">保存</GlassButton>
      </template>
    </el-dialog>

    <!-- 纪要抽屉 -->
    <DetailDrawer v-model="entriesVisible" :title="`沟通纪要 · ${currentCustomer?.display_name ?? ''}`" :width="560" :loading="entriesLoading">
      <div class="entry-list">
        <div v-for="entry in entries" :key="entry.id" class="entry-item">
          <div class="entry-head">
            <span class="entry-title">{{ entry.title || (entry.entry_type === 'image' ? '图片' : '纪要') }}</span>
            <span class="entry-date">{{ entry.created_at }}</span>
            <GlassButton v-permission="'card:write'" variant="link" link-tone="danger" left-icon="Delete" @click="removeEntry(entry)">删</GlassButton>
          </div>
          <p v-if="entry.content" class="entry-content">{{ entry.content }}</p>
          <el-image v-if="entry.attachment_url" :src="entry.attachment_url" :preview-src-list="[entry.attachment_url]" fit="cover" class="entry-img" />
        </div>
        <el-empty v-if="!entries.length" description="还没有纪要——录第一条，客户凭口令即可看到" :image-size="72" />
      </div>

      <div v-permission="'card:write'" class="entry-form">
        <el-input v-model="entryForm.title" placeholder="标题（可选），如 Quotation / 展会合影" />
        <el-input v-model="entryForm.content" type="textarea" :rows="3" placeholder="沟通要点、报价说明……客户解锁后可见（英文面向客户）" />
        <!-- max-size-mb 放宽到 30：原片先进来由 uploadFn 端上压缩（长边1600 JPEG），默认 10MB 闸门会把手机原片挡在压缩之前 -->
        <AppUpload v-model="entryFiles" :upload-fn="uploadAttachment" accept="image/*" :max-size-mb="30" :multiple="true" :limit="6" button-text="选择图片（客户照片/资料图）" />
        <GlassButton variant="primary" :loading="entrySaving" style="width: 100%; margin-top: 10px" @click="saveEntry">录入纪要</GlassButton>
      </div>
    </DetailDrawer>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import AppUpload from '@/components/AppUpload.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import TableTools from '@/components/TableTools.vue'
import { uploadAttachment } from '@/api/card'
import { useTableView } from '@/composables/useTableView'
import { useCardButler } from './composables/useCardButler'

const activeTab = ref('customers')

// 表格视图状态（Action Bar Spec）：客户档案与客户询盘各一套列显隐/密度/全屏
const customerColumnDefs = [
  { key: 'display-name', label: '客户称呼' },
  { key: 'email', label: '口令（邮箱）' },
  { key: 'whatsapp', label: '口令（WhatsApp）' },
  { key: 'expo-code', label: '届次' },
  { key: 'entries', label: '纪要' },
  { key: 'created-at', label: '建档时间' },
]
const inquiryColumnDefs = [
  { key: 'salesperson', label: '业务员' },
  { key: 'contact', label: '客户联系方式' },
  { key: 'message', label: '内容' },
  { key: 'customer', label: '建档客户' },
  { key: 'created-at', label: '提交时间' },
  { key: 'status', label: '状态' },
]
const salespersonColumnDefs = [
  { key: 'slug', label: '主页地址' }, { key: 'name', label: '英文名' },
  { key: 'title', label: '职位' }, { key: 'email', label: '邮箱' },
  { key: 'whatsapp', label: 'WhatsApp' }, { key: 'status', label: '状态' },
]
const {
  density: customerDensity, densityClass: customerDensityClass, visibleKeys: customerVisibleKeys,
  panelRef: customerPanelRef, isFullscreen: customerIsFullscreen, toggleFullscreen: toggleCustomerFullscreen,
} = useTableView('card-butler-customers', customerColumnDefs)
const {
  density: inquiryDensity, densityClass: inquiryDensityClass, visibleKeys: inquiryVisibleKeys,
  panelRef: inquiryPanelRef, isFullscreen: inquiryIsFullscreen, toggleFullscreen: toggleInquiryFullscreen,
} = useTableView('card-butler-inquiries', inquiryColumnDefs)
const {
  density: salespersonDensity, densityClass: salespersonDensityClass,
  visibleKeys: salespersonVisibleKeys, panelRef: salespersonPanelRef,
  isFullscreen: salespersonIsFullscreen, toggleFullscreen: toggleSalespersonFullscreen,
} = useTableView('card-butler-salespersons', salespersonColumnDefs)

const {
  salespersons, fetchSalespersons,
  spDialogVisible, spSaving, spForm, openSpDialog, saveSalesperson,
  customerPage, customerDialogVisible, customerSaving, customerForm,
  openCustomerDialog, saveCustomer, removeCustomer,
  entriesVisible, entriesLoading, entrySaving, entries, currentCustomer,
  entryForm, entryFiles, openEntries, saveEntry, removeEntry,
  inquiryPage, markHandled,
} = useCardButler()
</script>

<style scoped>
.tip-line { margin-top: 10px; font-size: 12px; color: var(--color-text-secondary, #909399); }
.field-tip { font-size: 12px; color: var(--color-text-secondary, #909399); }
.entry-list { margin-bottom: 16px; }
.entry-item { padding: 10px 0; border-bottom: 1px solid var(--color-border-light, #ebeef5); }
.entry-head { display: flex; align-items: center; gap: 8px; }
.entry-title { font-weight: 600; }
.entry-date { flex: 1; font-size: 12px; color: var(--color-text-secondary, #909399); }
.entry-content { margin: 6px 0 0; white-space: pre-wrap; }
.entry-img { margin-top: 8px; width: 120px; height: 120px; border-radius: 8px; }
.entry-form { display: flex; flex-direction: column; gap: 10px; }
</style>
