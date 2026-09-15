<template>
  <div class="settings-page">
    <el-tabs v-model="active">
      <el-tab-pane label="生图提示词" name="generation" />
      <el-tab-pane label="美颜提示词" name="beautify" />
    </el-tabs>
    <PromptVersions v-if="active === 'generation'" />
    <BeautifyPromptVersions v-else />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import PromptVersions from './PromptVersions.vue'
import BeautifyPromptVersions from './BeautifyPromptVersions.vue'

const active = ref('generation')
</script>

<style scoped>
.settings-page { display: flex; flex-direction: column; gap: 14px; }
</style>
