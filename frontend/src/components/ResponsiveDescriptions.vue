<template>
  <div ref="container" class="responsive-descriptions">
    <el-descriptions v-bind="$attrs" :column="columns">
      <template v-for="(_, name) in $slots" #[name]="scope"><slot :name="name" v-bind="scope || {}" /></template>
    </el-descriptions>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { descriptionColumns } from '../utils/responsiveDescriptions'
defineOptions({ inheritAttrs: false })
const props = defineProps({ column: { type: Number, default: 3 } })
const container = ref(null)
const width = ref(0)
const columns = computed(() => descriptionColumns(width.value, props.column))
let observer
onMounted(() => {
  width.value = container.value?.clientWidth || 0
  observer = new ResizeObserver(entries => { width.value = entries[0]?.contentRect.width || 0 })
  observer.observe(container.value)
})
onUnmounted(() => observer?.disconnect())
</script>

<style scoped>
.responsive-descriptions { min-width: 0; width: 100%; }
</style>
<style>
.responsive-descriptions .el-descriptions__content { overflow-wrap: anywhere; }
.responsive-descriptions .el-descriptions__label.is-bordered-label { min-width: 80px; white-space: nowrap; }
</style>
