<template>
  <el-empty :description="description" :image-size="imageSize">
    <slot><GlassButton v-if="actionLabel" :left-icon="RefreshLeft" @click="$emit('action')">{{ actionLabel }}</GlassButton></slot>
  </el-empty>
</template>
<script setup>
import { RefreshLeft } from '@element-plus/icons-vue'
import GlassButton from './GlassButton.vue'
defineProps({ description: { type: String, default: '暂无数据' }, imageSize: { type: Number, default: 80 }, actionLabel: String })
defineEmits(['action'])
</script>
