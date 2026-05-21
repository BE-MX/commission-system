<template>
  <el-dialog
    v-model="visible"
    :title="title"
    width="600px"
    destroy-on-close
  >
    <div class="color-detail">
      <!-- 大色块预览 -->
      <div class="preview-section">
        <div class="big-color-block" :style="{ backgroundColor: hex }">
          <span class="hex-label">{{ hex }}</span>
        </div>
        <div v-if="isBlend && blendComponents.length" class="blend-breakdown">
          <div class="blend-bar-wrapper">
            <GradientBar :components="blendComponents" :blend-type="blendType" />
          </div>
          <div class="component-list">
            <div
              v-for="c in blendComponents"
              :key="c.id"
              class="component-item"
            >
              <span class="dot" :style="{ backgroundColor: c.palette?.hex_code }"></span>
              <span>{{ c.palette?.industry_code }} {{ c.palette?.display_name }}</span>
              <span class="weight">{{ Math.round((c.weight || 0) * 100) }}%</span>
              <el-tag size="small" class="position-tag">{{ positionLabel(c.position) }}</el-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- 全格式数值 -->
      <el-descriptions :column="2" border>
        <el-descriptions-item label="HEX">{{ hex }}</el-descriptions-item>
        <el-descriptions-item label="RGB">rgb({{ rgb }})</el-descriptions-item>
        <el-descriptions-item label="LAB">L*{{ lab?.[0] }} a*{{ lab?.[1] }} b*{{ lab?.[2] }}</el-descriptions-item>
        <el-descriptions-item label="HSL">H{{ hsl?.[0] }}° S{{ hsl?.[1] }}% L{{ hsl?.[2] }}%</el-descriptions-item>
      </el-descriptions>

      <!-- 属性标签 -->
      <div class="tag-section">
        <el-tag v-if="undertone" :type="undertoneTagType">{{ undertoneLabel }}</el-tag>
        <el-tag>{{ colorFamilyLabel }}</el-tag>
        <el-tag v-if="luminanceLevel">{{ luminanceLevel }}</el-tag>
        <el-tag v-if="isLeshineStock" type="success">莱莎库存</el-tag>
        <el-tag v-if="peakSeason" type="info">{{ peakSeason }}</el-tag>
      </div>

      <!-- Pantone 匹配 -->
      <div v-if="pantoneTcx" class="pantone-section">
        <el-divider />
        <div class="pantone-info">
          <span class="label">最近 Pantone:</span>
          <span class="code">{{ pantoneTcx }}</span>
          <span class="delta">ΔE = {{ pantoneDeltaE }}</span>
          <el-tag v-if="pantoneDeltaE < 3" type="success" size="small">视觉无差异</el-tag>
          <el-tag v-else-if="pantoneDeltaE < 5" type="warning" size="small">可接受</el-tag>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="actions">
        <el-button type="primary" @click="$emit('generate-swatch')">生成色板图</el-button>
        <el-button v-if="canEdit" @click="$emit('edit')">编辑</el-button>
        <el-button v-if="canDelete" type="danger" @click="$emit('delete')">删除</el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'
import GradientBar from './GradientBar.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '色号详情' },
  hex: { type: String, default: '' },
  rgb: { type: Array, default: () => [] },
  lab: { type: Array, default: () => [] },
  hsl: { type: Array, default: () => [] },
  undertone: { type: String, default: '' },
  colorFamily: { type: String, default: '' },
  luminanceLevel: { type: String, default: '' },
  isLeshineStock: { type: Boolean, default: false },
  peakSeason: { type: String, default: '' },
  pantoneTcx: { type: String, default: '' },
  pantoneDeltaE: { type: Number, default: null },
  isBlend: { type: Boolean, default: false },
  blendType: { type: String, default: '' },
  blendComponents: { type: Array, default: () => [] },
  canEdit: { type: Boolean, default: false },
  canDelete: { type: Boolean, default: false },
})

defineEmits(['update:modelValue', 'edit', 'delete', 'generate-swatch'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const undertoneLabel = computed(() => {
  const map = { warm: '暖调', cool: '冷调', neutral: '中性' }
  return map[props.undertone] || props.undertone
})

const undertoneTagType = computed(() => {
  const map = { warm: 'danger', cool: 'primary', neutral: 'info' }
  return map[props.undertone] || ''
})

const colorFamilyLabel = computed(() => {
  const map = {
    black: '黑色系', brown: '棕色系', blonde: '金色系',
    red: '红色系', silver: '银色系', vibrant: ' vibrant 系',
  }
  return map[props.colorFamily] || props.colorFamily
})

function positionLabel(pos) {
  const map = { root: '发根', mid: '发中', end: '发尾', highlight: '高光', even: '均匀' }
  return map[pos] || pos
}
</script>

<style scoped>
.color-detail {
  padding: 0 8px;
}
.preview-section {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
}
.big-color-block {
  width: 160px;
  height: 160px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid var(--el-border-color-lighter);
}
.hex-label {
  background: rgba(255,255,255,0.9);
  padding: 4px 12px;
  border-radius: 4px;
  font-family: monospace;
  font-weight: 600;
  font-size: 14px;
}
.blend-breakdown {
  flex: 1;
}
.blend-bar-wrapper {
  height: 40px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  margin-bottom: 12px;
}
.component-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.component-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.component-item .dot {
  width: 14px;
  height: 14px;
  border-radius: 3px;
  flex-shrink: 0;
}
.component-item .weight {
  color: var(--el-text-color-secondary);
  font-weight: 500;
}
.position-tag {
  margin-left: auto;
}
.tag-section {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.pantone-section {
  margin-top: 8px;
}
.pantone-info {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
}
.pantone-info .label {
  color: var(--el-text-color-secondary);
}
.pantone-info .code {
  font-weight: 600;
  font-family: monospace;
}
.pantone-info .delta {
  color: var(--el-text-color-secondary);
}
.actions {
  margin-top: 24px;
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
</style>
