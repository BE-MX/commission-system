<template>
  <div class="swatch-library">
    <header class="sl-head">
      <h1 class="sl-title">色板库</h1>
      <div class="sl-seg" role="tablist" aria-label="色板库范围">
        <button
          v-for="tab in tabs" :key="tab.value" type="button" role="tab"
          :aria-selected="lib.scope.value === tab.value"
          :class="{ on: lib.scope.value === tab.value }"
          @click="lib.scope.value = tab.value"
        >{{ tab.label }}</button>
      </div>
      <span class="sl-spacer" />
      <DeviceStatusPill :device="meter.device" :state-enum="meter.STATE" />
      <el-button
        v-if="canCreate" type="primary" :icon="Plus"
        :disabled="lib.scope.value === 'private' && !lib.customerId.value"
        @click="createOpen = true"
      >新建色板</el-button>
    </header>

    <div class="sl-layout" :class="{ 'is-public': lib.scope.value === 'public' }">
      <CustomerRail
        v-if="lib.scope.value === 'private'"
        v-model:keyword="lib.customerKeyword.value"
        v-model:selected="lib.customerId.value"
        :customers="lib.customers.value"
        :loading="lib.customersLoading.value"
        :error="lib.customersError.value"
        @retry="lib.loadCustomers"
      />

      <section class="sl-panel">
        <div class="sl-ctx">
          <template v-if="lib.scope.value === 'public'">
            <h2>公库 · 公司标准色板</h2>
            <p>全员可查看，色彩管理员维护；私库色板以此作为对比基准</p>
          </template>
          <template v-else-if="lib.currentCustomer.value">
            <h2>{{ lib.currentCustomer.value.display_name }}</h2>
            <p>
              私库 · {{ lib.total.value }} 个色板
              <span v-if="lib.warnCount.value" class="sl-warn">· {{ lib.warnCount.value }} 个偏差</span>
              <span v-if="lib.currentCustomer.value.assignment_role === 'collaborator'"> · 你是协作人</span>
            </p>
          </template>
          <template v-else>
            <h2>我的私库</h2>
            <p>私库色板必须绑定客户；你当前没有主负责或协作的客户</p>
          </template>
        </div>

        <div class="sl-toolbar">
          <el-input v-model="lib.filters.keyword" placeholder="色号 / 名称" clearable :prefix-icon="Search" class="sl-search" />
          <el-select v-model="lib.filters.size" placeholder="全部尺寸" clearable class="sl-select">
            <el-option v-for="opt in lib.sizeOptions.value" :key="opt.key" :label="opt.label" :value="opt.key" />
          </el-select>
          <el-select v-model="lib.filters.verdict" placeholder="全部状态" clearable class="sl-select">
            <el-option label="符合" value="ok" />
            <el-option label="偏差" value="warn" />
            <el-option label="未测量" value="none" />
          </el-select>
        </div>

        <ListPageStatus
          v-if="lib.error.value" :paged="false" :error="lib.error.value" :loading="lib.loading.value"
          :has-data="lib.swatches.value.length > 0" @retry="lib.loadSwatches"
        />

        <div v-loading="lib.loading.value" class="sl-grid">
          <SwatchCard v-for="item in lib.visibleSwatches.value" :key="item.id" :swatch="item" @open="openDetail(item.id)" />
          <button
            v-if="canCreate && lib.scope.value === 'private' && lib.customerId.value"
            type="button" class="sl-add" @click="createOpen = true"
          >
            <el-icon :size="22"><Plus /></el-icon>
            <span>为该客户新建色板</span>
          </button>
        </div>
        <el-empty
          v-if="!lib.loading.value && !lib.error.value && !lib.visibleSwatches.value.length && lib.scope.value === 'public'"
          description="公库暂无色板"
        />
      </section>
    </div>

    <SwatchCreateDialog
      v-model="createOpen"
      :scope="lib.scope.value"
      :customers="lib.customers.value"
      :customer-id="lib.customerId.value"
      :can-public="canAdmin"
      @created="onCreated"
    />

    <SwatchDetailDrawer
      v-model="detailOpen"
      :swatch-id="detailId"
      :meter="meter"
      @changed="lib.patchSwatch"
      @archived="lib.removeSwatch"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Plus, Search } from '@element-plus/icons-vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import { useAuthStore } from '@/stores/auth'
import CustomerRail from './swatch-library/CustomerRail.vue'
import DeviceStatusPill from './swatch-library/DeviceStatusPill.vue'
import SwatchCard from './swatch-library/SwatchCard.vue'
import SwatchCreateDialog from './swatch-library/SwatchCreateDialog.vue'
import SwatchDetailDrawer from './swatch-library/SwatchDetailDrawer.vue'
import { useColorimeter } from './composables/useColorimeter'
import { useSwatchLibrary } from './composables/useSwatchLibrary'

const auth = useAuthStore()
const lib = useSwatchLibrary()
const meter = useColorimeter()

const tabs = [
  { value: 'private', label: '我的私库' },
  { value: 'public', label: '公库' },
]
const canAdmin = computed(() => auth.hasPermission('color_library:admin'))
const canCreate = computed(() => (lib.scope.value === 'public'
  ? canAdmin.value
  : auth.hasAnyPermission(['color_library:write', 'color_library:admin'])))

const createOpen = ref(false)
const detailOpen = ref(false)
const detailId = ref(null)

function openDetail(id) {
  detailId.value = id
  detailOpen.value = true
}

function onCreated({ swatch, measure }) {
  if (swatch.library_scope !== lib.scope.value) lib.scope.value = swatch.library_scope
  if (swatch.customer_id && swatch.customer_id !== lib.customerId.value) lib.customerId.value = swatch.customer_id
  else lib.patchSwatch(swatch)
  lib.loadSwatches()
  if (measure) openDetail(swatch.id)
}

onMounted(lib.init)
</script>

<style scoped>
.swatch-library {
  padding: 20px 24px 32px;
  min-height: 100%;
  background:
    radial-gradient(1200px 400px at 85% -10%, var(--color-gold-soft), transparent 60%),
    var(--page-bg);
}
.sl-head { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
.sl-title { font: 700 17px var(--font-display); color: var(--text-primary); margin: 0; }
.sl-spacer { flex: 1; }
.sl-seg { display: inline-flex; padding: 3px; border-radius: 10px; background: var(--button-quiet-hover); }
.sl-seg button {
  border: 0; background: transparent; cursor: pointer; padding: 6px 16px; border-radius: var(--radius-md, 8px);
  font: 600 13px var(--font-display); color: var(--text-secondary);
  transition: background-color 160ms ease, color 160ms ease, transform 120ms ease-out;
}
.sl-seg button.on { background: var(--card-bg); color: var(--text-primary); box-shadow: var(--card-shadow); }
.sl-seg button:active { transform: scale(0.97); }
.sl-seg button:focus-visible { outline: 2px solid var(--button-focus); outline-offset: 1px; }

.sl-layout { display: grid; grid-template-columns: 264px minmax(0, 1fr); gap: 16px; align-items: start; }
.sl-layout.is-public { grid-template-columns: minmax(0, 1fr); }

.sl-panel {
  background: var(--card-bg); border-radius: var(--card-radius); box-shadow: var(--card-shadow);
  border: 1px solid var(--border-color); padding: 16px 18px 20px; min-width: 0;
}
.sl-ctx { padding-bottom: 12px; margin-bottom: 14px; border-bottom: 1px solid var(--border-color); }
.sl-ctx h2 { margin: 0; font: 700 15px var(--font-display); color: var(--text-primary); }
.sl-ctx p { margin: 2px 0 0; font-size: 12px; color: var(--text-muted); }
.sl-warn { color: var(--button-warning-text); }

.sl-toolbar { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.sl-search { width: 220px; }
.sl-select { width: 130px; }

.sl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(208px, 1fr)); gap: 14px; min-height: 120px; }
.sl-add {
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
  min-height: 200px; border-radius: var(--card-radius); border: 1.5px dashed var(--border-hover);
  background: transparent; color: var(--text-secondary); font: 600 13px var(--font-display); cursor: pointer;
  transition: border-color 160ms ease, background-color 160ms ease, color 160ms ease, transform 120ms ease-out;
}
.sl-add:active { transform: scale(0.98); }
@media (hover: hover) and (pointer: fine) {
  .sl-add:hover { border-color: var(--color-primary); background: var(--color-primary-light); color: var(--button-primary-text); }
}

@media (max-width: 860px) {
  .swatch-library { padding: 14px; }
  .sl-layout { grid-template-columns: minmax(0, 1fr); }
  .sl-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .sl-search { width: 100%; }
  .sl-select { flex: 1; }
}
</style>
