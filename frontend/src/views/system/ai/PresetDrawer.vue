<template>
  <DetailDrawer
    :model-value="modelValue"
    :title="preset ? `预设详情 · ${preset.preset_name}` : '预设详情'"
    width="560px"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div v-if="preset" class="pdr-body">
      <div class="pdr-crumb">
        <span>{{ preset.nav_group || '待处理' }}</span>
        <span aria-hidden="true">›</span>
        <strong>{{ preset.feature_label || '未归属' }}</strong>
        <el-button
          v-if="preset.route_path"
          link
          type="primary"
          @click="$emit('jump-route', preset.route_path)"
        >打开业务页 ↗</el-button>
      </div>

      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="预设名称">
          <span class="mono-text">{{ preset.preset_name }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <StatusBadge :type="preset.is_enabled ? 'success' : 'info'" size="small" effect="plain">
            {{ preset.is_enabled ? '启用' : '禁用' }}
          </StatusBadge>
        </el-descriptions-item>
        <el-descriptions-item label="绑定提供商">
          {{ preset.provider_name || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="绑定模型">
          <span class="mono-text">{{ preset.model || '-' }}</span>
        </el-descriptions-item>
      </el-descriptions>

      <div class="pdr-sec">
        <h4>用途说明</h4>
        <p class="pdr-text">{{ preset.description || '未填写用途说明' }}</p>
      </div>

      <div v-if="preset.system_prompt" class="pdr-sec">
        <h4>System Prompt（摘要）</h4>
        <pre class="pdr-code">{{ preset.system_prompt }}</pre>
      </div>

      <div class="pdr-sec">
        <h4>调用参数</h4>
        <pre class="pdr-code">{{ formattedParams }}</pre>
      </div>
    </div>

    <template v-if="preset" #footer>
      <el-button v-permission="'ai:admin'" @click="$emit('test', preset)">测试调用</el-button>
      <el-button v-permission="'ai:admin'" @click="$emit('copy', preset)">复制预设</el-button>
      <el-button v-permission="'ai:admin'" @click="$emit('toggle', preset)">
        {{ preset.is_enabled ? '停用' : '启用' }}
      </el-button>
      <el-button v-permission="'ai:admin'" type="danger" plain @click="$emit('delete', preset)">删除</el-button>
      <el-button v-permission="'ai:admin'" type="primary" @click="$emit('edit', preset)">编辑预设</el-button>
    </template>
  </DetailDrawer>
</template>

<script setup>
import { computed } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  preset: { type: Object, default: null },
})

defineEmits(['update:modelValue', 'test', 'copy', 'toggle', 'delete', 'edit', 'jump-route'])

const formattedParams = computed(() => {
  try {
    return JSON.stringify(props.preset?.parameters || {}, null, 2)
  } catch {
    return '{}'
  }
})
</script>

<style scoped>
.pdr-body { display: flex; flex-direction: column; gap: 16px; }
.pdr-crumb { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 13px; color: var(--text-secondary); }
.pdr-sec h4 { margin: 0 0 6px; font-family: var(--font-display); font-size: 13px; font-weight: 700; color: var(--text-primary); }
.pdr-text { margin: 0; font-size: 13px; color: var(--text-secondary); line-height: 1.6; }
.pdr-code {
  margin: 0; padding: 10px 12px; border-radius: 8px;
  background: var(--toolbar-bg); border: 1px solid var(--border-color);
  font-family: var(--font-mono); font-size: 12px; color: var(--text-primary);
  white-space: pre-wrap; word-break: break-word; max-height: 220px; overflow-y: auto;
}
.mono-text { font-family: var(--font-mono); font-size: 12px; }
</style>
