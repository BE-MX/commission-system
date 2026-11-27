<template>
  <section class="preset-board">
    <div v-if="unassignedCount > 0" class="unassigned-alert">
      <span>当前有 <strong>{{ unassignedCount }}</strong> 个存量预设未归属功能（调用不受影响，但无法按功能筛选）。</span>
      <el-button @click="$emit('filter-unassigned')">只看未归属</el-button>
    </div>

    <!-- 三层面包屑标签筛选：功能 → 提供商 → 模型 -->
    <div class="trail-panel lg-card is-static">
      <div class="trail-row">
        <span class="trail-row__label">功能</span>
        <div class="trail-row__chips">
          <button
            v-for="chip in featureChips"
            :key="chip.value"
            type="button"
            class="trail-chip"
            :class="{
              'is-on': selectedFeatures.has(chip.value),
              'is-warn': chip.isUnassigned && !selectedFeatures.has(chip.value),
            }"
            @click="$emit('toggle-chip', 'feature', chip.value)"
          >
            {{ chip.label }}<span class="trail-chip__n">{{ chip.count }}</span>
          </button>
        </div>
      </div>
      <div class="trail-row">
        <span class="trail-row__label">提供商</span>
        <div class="trail-row__chips">
          <button
            v-for="chip in providerChips"
            :key="chip.value"
            type="button"
            class="trail-chip"
            :class="{ 'is-on': selectedProviders.has(chip.value) }"
            @click="$emit('toggle-chip', 'provider', chip.value)"
          >
            {{ chip.label }}<span class="trail-chip__n">{{ chip.count }}</span>
          </button>
        </div>
      </div>
      <div class="trail-row">
        <span class="trail-row__label">模型</span>
        <div class="trail-row__chips">
          <button
            v-for="chip in modelChips"
            :key="chip.value"
            type="button"
            class="trail-chip trail-chip--mono"
            :class="{ 'is-on': selectedModels.has(chip.value) }"
            @click="$emit('toggle-chip', 'model', chip.value)"
          >
            {{ chip.label }}<span class="trail-chip__n">{{ chip.count }}</span>
          </button>
        </div>
      </div>
    </div>

    <div class="preset-bar">
      <el-input
        :model-value="search"
        placeholder="搜索预设名称、模型或描述"
        clearable
        class="preset-search"
        @update:model-value="$emit('update:search', $event)"
      />
      <span class="preset-count">显示 {{ filteredCount }} / {{ totalCount }} 个预设</span>
      <span class="preset-spacer" />
      <el-button v-if="hasActiveFilters" @click="$emit('clear-all')">清除全部筛选</el-button>
      <GlassButton v-permission="'ai:admin'" variant="primary" left-icon="Plus" @click="$emit('add')">
        新增预设
      </GlassButton>
    </div>

    <ListPageStatus v-if="errorMessage" :error="errorMessage" :loading="loading" :has-data="totalCount > 0" @retry="$emit('refresh')" />

    <div v-loading="loading" class="preset-groups lg-card is-static">
      <div class="preset-head-row">
        <div>功能 › 预设名称</div>
        <div>绑定提供商</div>
        <div>模型</div>
        <div>状态</div>
        <div>操作</div>
      </div>

      <template v-if="groups.length">
        <div v-for="group in groups" :key="group.key" class="preset-group">
          <div class="preset-group__head">
            <span :class="{ 'is-unassigned': group.isUnassigned }">
              {{ group.isUnassigned ? '⚠ ' : '' }}{{ group.label }}
            </span>
            <span class="nav-pill">{{ group.navGroup }}</span>
            <el-button
              v-if="group.routePath"
              link
              type="primary"
              @click="$emit('jump-route', group.routePath)"
            >进入功能 ↗</el-button>
            <span class="preset-group__count">{{ group.items.length }} 个</span>
          </div>

          <div
            v-for="row in group.items"
            :key="row.id"
            class="preset-row"
            tabindex="0"
            @click="$emit('inspect', row)"
            @keydown.enter.prevent="$emit('inspect', row)"
          >
            <div class="col-main">
              <PresetFeatureTrail :preset="row" />
              <div v-if="row.description" class="row-desc">{{ row.description }}</div>
            </div>
            <div class="col-prov">
              <span class="prov-badge" :class="{ 'is-off': row.provider_is_enabled === false }">
                {{ row.provider_name || '-' }}
              </span>
            </div>
            <div class="col-model">
              <span class="model-pill" :title="row.model">{{ row.model || '-' }}</span>
            </div>
            <div class="col-status">
              <StatusBadge :type="row.is_enabled ? 'success' : 'info'" size="small" effect="plain">
                {{ row.is_enabled ? '启用' : '禁用' }}
              </StatusBadge>
            </div>
            <div class="col-actions" @click.stop>
              <el-button link type="primary" @click="$emit('test', row)">测试</el-button>
              <el-button link type="primary" @click="$emit('edit', row)">编辑</el-button>
              <el-button link type="primary" @click="$emit('copy', row)">复制</el-button>
              <el-button link type="danger" @click="$emit('delete', row)">删除</el-button>
            </div>
          </div>
        </div>
      </template>

      <el-empty v-else-if="!loading" description="没有符合条件的预设，清除部分标签试试" :image-size="88" />
    </div>
  </section>
</template>

<script setup>
import ListPageStatus from '@/components/ListPageStatus.vue'
import PresetFeatureTrail from './PresetFeatureTrail.vue'

defineProps({
  groups: { type: Array, required: true },
  featureChips: { type: Array, required: true },
  providerChips: { type: Array, required: true },
  modelChips: { type: Array, required: true },
  selectedFeatures: { type: Object, required: true },
  selectedProviders: { type: Object, required: true },
  selectedModels: { type: Object, required: true },
  search: { type: String, default: '' },
  filteredCount: { type: Number, default: 0 },
  totalCount: { type: Number, default: 0 },
  unassignedCount: { type: Number, default: 0 },
  hasActiveFilters: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
})

defineEmits([
  'update:search', 'toggle-chip', 'clear-all', 'filter-unassigned',
  'add', 'refresh', 'inspect', 'test', 'edit', 'copy', 'delete', 'jump-route',
])
</script>

<style scoped>
.preset-board { display: flex; flex-direction: column; gap: 12px; }
.unassigned-alert {
  display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap;
  padding: 10px 14px; border-radius: 10px; font-size: 13px;
  background: var(--tag-danger-bg); border: 1px solid var(--tag-danger-border); color: var(--tag-danger-text);
}
.trail-panel { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.trail-row { display: flex; gap: 10px; align-items: flex-start; }
.trail-row__label { width: 52px; flex: none; font-size: 12px; font-weight: 600; color: var(--text-muted); padding-top: 6px; }
.trail-row__chips { display: flex; flex-wrap: wrap; gap: 6px; flex: 1; }
.trail-chip {
  border: 1px solid var(--border-color); background: var(--card-bg);
  border-radius: 999px; padding: 4px 11px; font-size: 12px; cursor: pointer;
  color: var(--text-primary); white-space: nowrap;
  transition: background-color var(--motion-fast) ease, border-color var(--motion-fast) ease;
}
.trail-chip--mono { font-family: var(--font-mono); }
.trail-chip__n { margin-left: 4px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.trail-chip.is-on { background: var(--tag-gold-bg); border-color: var(--tag-gold-solid); color: var(--tag-gold-text); font-weight: 600; }
.trail-chip.is-on .trail-chip__n { color: var(--tag-gold-text); }
.trail-chip.is-warn { border-color: var(--tag-danger-border); color: var(--tag-danger-text); }
.preset-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.preset-search { width: 240px; }
.preset-count { font-size: 12px; color: var(--text-muted); }
.preset-spacer { flex: 1; }
.preset-groups { overflow: hidden; }
.preset-head-row,
.preset-row {
  display: grid;
  grid-template-columns: minmax(260px, 1.5fr) 140px 180px 84px 190px;
  gap: 12px;
  align-items: center;
  padding: 10px 14px;
}
.preset-head-row {
  font-size: 12px; font-weight: 600; color: var(--text-muted);
  background: var(--table-header-bg); border-bottom: 1px solid var(--border-color);
}
.preset-group__head {
  display: flex; align-items: center; gap: 8px; padding: 9px 14px;
  background: var(--toolbar-bg); border-bottom: 1px solid var(--border-color);
  font-family: var(--font-display); font-weight: 700; font-size: 13px; color: var(--text-secondary);
}
.preset-group__head .is-unassigned { color: var(--tag-danger-text); }
.nav-pill {
  font-size: 11px; font-weight: 500; color: var(--text-muted);
  background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 5px; padding: 0 6px;
}
.preset-group__count { margin-left: auto; font-size: 12px; font-weight: 500; color: var(--text-muted); }
.preset-row {
  border-bottom: 1px solid var(--border-color); cursor: pointer;
  transition: background-color var(--motion-fast) ease;
}
.preset-row:last-child { border-bottom: 0; }
@media (hover: hover) and (pointer: fine) {
  .preset-row:hover { background: var(--table-row-hover); }
}
.row-desc { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
.prov-badge {
  display: inline-block; font-size: 12px; font-weight: 600; border-radius: 6px; padding: 2px 8px;
  background: var(--tag-gold-bg); color: var(--tag-gold-text); border: 1px solid var(--tag-gold-border);
}
.prov-badge.is-off { background: var(--tag-neutral-bg); color: var(--tag-neutral-text); border-color: var(--tag-neutral-border); }
.model-pill {
  display: inline-block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-family: var(--font-mono); font-size: 12px;
  background: var(--tag-neutral-bg); border: 1px solid var(--tag-neutral-border);
  border-radius: 5px; padding: 2px 7px; color: var(--text-secondary);
}
.col-actions { display: flex; gap: 4px; flex-wrap: wrap; }

/* 窄屏自适应：永远保留模型名，杜绝列错位 */
@media (max-width: 960px) {
  .preset-head-row { display: none; }
  .preset-row { display: flex; flex-wrap: wrap; gap: 8px 10px; padding: 12px 14px; }
  .col-main { flex: 1 1 70%; min-width: 0; }
  .col-status { order: 2; margin-left: auto; }
  .col-prov { order: 3; }
  .col-model { order: 4; max-width: 100%; }
  .col-actions { order: 5; width: 100%; padding-top: 4px; border-top: 1px dashed var(--border-color); }
}
@media (max-width: 640px) {
  .trail-row { flex-direction: column; gap: 4px; }
  .trail-row__label { width: auto; padding-top: 0; }
  .preset-search { width: 100%; }
}
</style>
