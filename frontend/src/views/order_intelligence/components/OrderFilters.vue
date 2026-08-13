<template>
  <section class="oi-toolbar lg-card is-static">
    <div class="oi-filter oi-filter--date">
      <span>分析周期</span>
      <el-date-picker v-model="filters.dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" />
    </div>
    <template v-if="options.can_read_all">
      <div class="oi-filter">
        <span>团队</span>
        <el-select v-model="filters.team" clearable placeholder="全部团队" @change="$emit('team-change')">
          <el-option v-for="team in options.teams" :key="team" :label="team" :value="team" />
        </el-select>
      </div>
      <div class="oi-filter">
        <span>业务员</span>
        <el-select v-model="filters.user_id" clearable filterable placeholder="全部人员">
          <el-option v-for="user in scopedUsers" :key="user.user_id" :label="`${user.user_name} · ${user.team || '未分组'}`" :value="user.user_id" />
        </el-select>
      </div>
    </template>
    <div class="oi-filter">
      <span>国家（大洲 / 国家）</span>
      <el-cascader
        v-model="filters.countryPaths"
        :options="options.country_tree"
        :props="countryProps"
        clearable
        collapse-tags
        collapse-tags-tooltip
        filterable
        placeholder="全部国家"
      />
    </div>
    <div class="oi-filter">
      <span>产品型号</span>
      <el-select v-model="filters.models" multiple clearable collapse-tags collapse-tags-tooltip filterable placeholder="全部型号">
        <el-option v-for="model in options.models" :key="model" :label="model" :value="model" />
      </el-select>
    </div>
    <div class="oi-filter">
      <span>颜色</span>
      <el-select v-model="filters.colors" multiple clearable collapse-tags collapse-tags-tooltip filterable placeholder="全部颜色">
        <el-option v-for="color in options.colors" :key="color" :label="color" :value="color" />
      </el-select>
    </div>
    <div class="oi-filter">
      <span>订单来源渠道</span>
      <el-select v-model="filters.sources" multiple clearable collapse-tags collapse-tags-tooltip placeholder="全部渠道">
        <el-option v-for="source in options.source_categories" :key="source.code" :label="source.label" :value="source.code" />
      </el-select>
    </div>
    <GlassButton variant="secondary" @click="$emit('apply')"><el-icon><Refresh /></el-icon> 更新分析</GlassButton>
    <small>有效订单口径 · 截至 {{ filters.dateRange?.[1] }}</small>
  </section>
</template>

<script setup>
import { Refresh } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'

defineProps({
  filters: { type: Object, required: true },
  options: { type: Object, required: true },
  scopedUsers: { type: Array, default: () => [] },
})
defineEmits(['apply', 'team-change'])

const countryProps = {
  multiple: true,
  emitPath: true,
  checkStrictly: false,
  value: 'value',
  label: 'label',
  children: 'children',
}
</script>

<style scoped>
.oi-toolbar { display: flex; align-items: flex-end; flex-wrap: wrap; gap: 14px; padding: 14px 16px; margin-bottom: 18px; }
.oi-toolbar small { margin-left: auto; align-self: center; color: var(--text-muted-blue); }
.oi-filter { display: grid; gap: 6px; }
.oi-filter > span { color: var(--text-secondary); font-size: 11px; font-weight: 700; }
.oi-filter :deep(.el-select), .oi-filter :deep(.el-cascader) { width: 190px; }
.oi-filter--date :deep(.el-date-editor) { width: 270px; }
@media (max-width: 1250px) { .oi-toolbar small { width: 100%; margin-left: 0; } }
@media (max-width: 820px) {
  .oi-toolbar { align-items: stretch; flex-direction: column; }
  .oi-filter :deep(.el-select), .oi-filter :deep(.el-cascader), .oi-filter :deep(.el-date-editor) { width: 100%; }
}
</style>
