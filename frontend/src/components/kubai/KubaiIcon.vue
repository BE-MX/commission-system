<template>
  <span ref="host" class="kubai-icon" aria-hidden="true" />
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { disposeKubaiIcon, mountKubaiIcon, setKubaiHover } from './runtime'

const props = defineProps({
  name: { type: String, required: true },
  // The row that owns the hover: the whole menu row animates the icon, not just the glyph.
  hoverTarget: { type: String, default: '.el-menu-item, .el-sub-menu__title, .el-dropdown-menu__item' },
})

const host = ref(null)
let instance = null
let pointerTarget = null

// Mouse hover only: touch taps fire false hovers, and keyboard movement through the
// menu repeats too often to animate.
const onPointerEnter = event => { if (event.pointerType === 'mouse') setKubaiHover(instance, true) }
const onPointerLeave = event => { if (event.pointerType === 'mouse') setKubaiHover(instance, false) }

function bind() {
  pointerTarget = host.value?.closest(props.hoverTarget) || host.value
  pointerTarget?.addEventListener('pointerenter', onPointerEnter)
  pointerTarget?.addEventListener('pointerleave', onPointerLeave)
}

function unbind() {
  pointerTarget?.removeEventListener('pointerenter', onPointerEnter)
  pointerTarget?.removeEventListener('pointerleave', onPointerLeave)
  pointerTarget = null
}

function mount() {
  disposeKubaiIcon(instance)
  instance = mountKubaiIcon(props.name, host.value)
  if (!instance && host.value) host.value.innerHTML = ''
}

onMounted(() => { mount(); bind() })
watch(() => props.name, mount)
onBeforeUnmount(() => { unbind(); disposeKubaiIcon(instance); instance = null })
</script>

<style scoped>
.kubai-icon { display: inline-flex; width: 1em; height: 1em; line-height: 1; }
.kubai-icon :deep(svg) { width: 100%; height: 100%; overflow: visible; display: block; }
.kubai-icon :deep(.ol) { fill: none; stroke-width: 2; }
.kubai-icon :deep(.ln) { fill: none; stroke-width: 1.6; stroke-linecap: round; }
</style>
