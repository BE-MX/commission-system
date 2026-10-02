<template>
  <section aria-label="操作按钮状态对照" class="button-states">
    <h2>共享组件 · 语义与状态</h2>
    <div v-for="tone in tones" :key="tone" class="state-row">
      <template v-for="state in states" :key="state">
        <GlassButton :id="`gb-${tone}-${state}`" variant="link" :link-tone="tone === 'default' ? '' : tone"
          left-icon="Edit" :disabled="state.startsWith('disabled')" :loading="state.includes('loading')">{{ tone }}</GlassButton>
        <el-button :id="`ep-${tone}-${state}`" link :type="tone === 'default' ? '' : tone"
          :disabled="state.startsWith('disabled')" :loading="state.includes('loading')"><el-icon><Edit /></el-icon>{{ tone }}</el-button>
      </template>
    </div>
    <h2>实心与次操作 · 文字对比度</h2>
    <div class="state-row">
      <GlassButton v-for="variant in variants" :id="`solid-gb-${variant}`" :key="variant" :variant="variant">{{ variant }}</GlassButton>
      <el-button id="solid-ep-default">default</el-button>
      <el-button v-for="tone in tones.filter(t => t !== 'default')" :id="`solid-ep-${tone}`" :key="tone" :type="tone">{{ tone }}</el-button>
    </div>
  </section>
</template>
<script setup>
const tones = ['default', 'primary', 'success', 'warning', 'danger']
const states = ['base', 'disabled', 'loading', 'disabled-loading']
const variants = ['primary', 'success', 'danger', 'warning', 'secondary', 'outline', 'white', 'soft']
</script>
<style scoped>
.button-states { margin-bottom: 24px; }
.state-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 8px; }
</style>
